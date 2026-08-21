"""Write resolved entities and relations into Neo4j.

Everything uses MERGE rather than CREATE so re-running ingestion is a
no-op instead of duplicating the graph. Every relationship carries the
chunk_id that asserted it, which is what makes a graph answer citable.
"""

from collections import defaultdict

from sqlalchemy import text as sql

from app.extraction.resolver import EntityResolver, ResolvedEntity
from app.extraction.schemas import RelationType, validate_extraction
from app.graph.client import run_read, run_write
from app.infrastructure.postgres import engine


CONSTRAINTS = [
    """
    CREATE CONSTRAINT entity_id_unique IF NOT EXISTS
    FOR (e:Entity) REQUIRE e.entity_id IS UNIQUE
    """,
    """
    CREATE CONSTRAINT chunk_id_unique IF NOT EXISTS
    FOR (c:Chunk) REQUIRE c.chunk_id IS UNIQUE
    """,
    """
    CREATE INDEX entity_name_index IF NOT EXISTS
    FOR (e:Entity) ON (e.name)
    """,
    """
    CREATE INDEX entity_norm_index IF NOT EXISTS
    FOR (e:Entity) ON (e.normalized)
    """,
]


MERGE_ENTITIES = """
UNWIND $rows AS row
MERGE (e:Entity {entity_id: row.entity_id})
SET e.name        = row.name,
    e.entity_type = row.entity_type,
    e.normalized  = row.normalized,
    e.aliases     = row.aliases,
    e.mentions    = row.mentions
"""


MERGE_CHUNKS = """
UNWIND $rows AS row
MERGE (c:Chunk {chunk_id: row.chunk_id})
SET c.document_id = row.document_id,
    c.filename    = row.filename,
    c.chunk_index = row.chunk_index
"""


MERGE_MENTIONS = """
UNWIND $rows AS row
MATCH (e:Entity {entity_id: row.entity_id})
MATCH (c:Chunk  {chunk_id:  row.chunk_id})
MERGE (e)-[m:MENTIONED_IN]->(c)
SET m.confidence = row.confidence
"""


# Relationship type cannot be parameterised in Cypher, so the type is
# interpolated from the RelationType enum and never from model output.
# Everything else is a bound parameter.
MERGE_RELATION_TEMPLATE = """
UNWIND $rows AS row
MATCH (a:Entity {{entity_id: row.source_id}})
MATCH (b:Entity {{entity_id: row.target_id}})
MERGE (a)-[r:{relation_type}]->(b)
ON CREATE SET r.chunk_ids = [row.chunk_id],
              r.confidence = row.confidence
ON MATCH  SET r.chunk_ids =
                  CASE WHEN row.chunk_id IN r.chunk_ids
                       THEN r.chunk_ids
                       ELSE r.chunk_ids + row.chunk_id END,
              r.confidence =
                  CASE WHEN row.confidence > coalesce(r.confidence, 0)
                       THEN row.confidence ELSE r.confidence END
"""


SELECT_PAYLOADS = """
SELECT e.chunk_id,
       e.payload,
       c.document_id,
       c.chunk_index,
       c.metadata->>'filename' AS filename
FROM chunk_extractions e
JOIN chunks c USING (chunk_id)
ORDER BY c.document_id, c.chunk_index
"""


UPSERT_CHUNK_ENTITY = """
INSERT INTO chunk_entities (chunk_id, entity_id, entity_name, entity_type)
VALUES (:chunk_id, :entity_id, :entity_name, :entity_type)
ON CONFLICT (chunk_id, entity_id) DO NOTHING
"""


def create_constraints() -> None:
    for statement in CONSTRAINTS:
        run_write(statement)


def build_graph_payload():
    """Read stored extractions, resolve entities, and shape the writes."""

    with engine.connect() as connection:
        rows = connection.execute(sql(SELECT_PAYLOADS)).fetchall()

    mentions: list[tuple[str, str]] = []
    per_chunk = []

    for row in rows:
        result = validate_extraction(row.payload)
        per_chunk.append((row, result))
        for entity in result.entities:
            mentions.append((str(entity.type), entity.name))

    resolver = EntityResolver()
    lookup = resolver.resolve(mentions)

    entities: dict[str, ResolvedEntity] = {}
    chunk_rows: dict[str, dict] = {}
    mention_rows: list[dict] = []
    relation_rows: dict[str, list[dict]] = defaultdict(list)
    chunk_entity_rows: list[dict] = []
    skipped_relations = 0

    for row, result in per_chunk:

        chunk_rows[row.chunk_id] = {
            "chunk_id": row.chunk_id,
            "document_id": row.document_id,
            "filename": row.filename,
            "chunk_index": row.chunk_index,
        }

        local: dict[str, ResolvedEntity] = {}

        for entity in result.entities:
            resolved = lookup[(str(entity.type), entity.name)]
            entities[resolved.entity_id] = resolved
            local[entity.name] = resolved

            mention_rows.append(
                {
                    "entity_id": resolved.entity_id,
                    "chunk_id": row.chunk_id,
                    "confidence": entity.confidence,
                }
            )

            chunk_entity_rows.append(
                {
                    "chunk_id": row.chunk_id,
                    "entity_id": resolved.entity_id,
                    "entity_name": resolved.name,
                    "entity_type": resolved.entity_type,
                }
            )

        for relation in result.relations:
            source = local.get(relation.source)
            target = local.get(relation.target)

            # Resolution can collapse two names onto one node, which
            # turns a valid edge into a self-loop. Drop those.
            if not source or not target or source.entity_id == target.entity_id:
                skipped_relations += 1
                continue

            relation_rows[str(relation.type)].append(
                {
                    "source_id": source.entity_id,
                    "target_id": target.entity_id,
                    "chunk_id": row.chunk_id,
                    "confidence": relation.confidence,
                }
            )

    return (
        entities,
        list(chunk_rows.values()),
        mention_rows,
        relation_rows,
        chunk_entity_rows,
        skipped_relations,
    )


def write_graph() -> dict:

    create_constraints()

    (
        entities,
        chunk_rows,
        mention_rows,
        relation_rows,
        chunk_entity_rows,
        skipped,
    ) = build_graph_payload()

    entity_rows = [
        {
            "entity_id": e.entity_id,
            "name": e.name,
            "entity_type": e.entity_type,
            "normalized": e.name.lower(),
            "aliases": e.aliases,
            "mentions": e.mentions,
        }
        for e in entities.values()
    ]

    run_write(MERGE_ENTITIES, rows=entity_rows)
    run_write(MERGE_CHUNKS, rows=chunk_rows)
    run_write(MERGE_MENTIONS, rows=mention_rows)

    edges = 0
    for relation_type, rows in relation_rows.items():
        # The type comes from our enum, never from the model.
        assert relation_type in set(RelationType), relation_type
        run_write(
            MERGE_RELATION_TEMPLATE.format(relation_type=relation_type),
            rows=rows,
        )
        edges += len(rows)

    with engine.begin() as connection:
        if chunk_entity_rows:
            connection.execute(sql(UPSERT_CHUNK_ENTITY), chunk_entity_rows)

    return {
        "entities": len(entity_rows),
        "chunks": len(chunk_rows),
        "mentions": len(mention_rows),
        "relation_assertions": edges,
        "relation_types": len(relation_rows),
        "skipped_relations": skipped,
        "chunk_entity_links": len(chunk_entity_rows),
    }


def graph_counts() -> dict:
    return run_read(
        """
        MATCH (e:Entity) WITH count(e) AS entities
        MATCH (c:Chunk)  WITH entities, count(c) AS chunks
        OPTIONAL MATCH ()-[m:MENTIONED_IN]->()
        WITH entities, chunks, count(m) AS mentions
        OPTIONAL MATCH (:Entity)-[r]->(:Entity)
        RETURN entities, chunks, mentions, count(r) AS relations
        """
    )[0]


if __name__ == "__main__":

    summary = write_graph()

    print("WRITE SUMMARY")
    for key, value in summary.items():
        print(f"  {key:<22} {value}")

    print()
    print("GRAPH COUNTS")
    for key, value in graph_counts().items():
        print(f"  {key:<22} {value}")
