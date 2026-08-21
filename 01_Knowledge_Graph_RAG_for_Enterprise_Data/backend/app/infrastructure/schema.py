from sqlalchemy import text

from app.infrastructure.postgres import engine


EMBEDDING_DIMENSIONS = 768


CREATE_EXTENSION = """
CREATE EXTENSION IF NOT EXISTS vector
"""


CREATE_DOCUMENTS = """
CREATE TABLE IF NOT EXISTS documents (
    document_id   TEXT PRIMARY KEY,
    filename      TEXT NOT NULL,
    source        TEXT NOT NULL,
    title         TEXT NOT NULL,
    content       TEXT NOT NULL,
    content_hash  TEXT NOT NULL,
    metadata      JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


CREATE_CHUNKS = f"""
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id      TEXT PRIMARY KEY,
    document_id   TEXT NOT NULL
                  REFERENCES documents (document_id)
                  ON DELETE CASCADE,
    chunk_index   INTEGER NOT NULL,
    text          TEXT NOT NULL,
    metadata      JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    embedding     vector({EMBEDDING_DIMENSIONS}),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (document_id, chunk_index)
)
"""


CREATE_CHUNKS_DOCUMENT_INDEX = """
CREATE INDEX IF NOT EXISTS chunks_document_id_idx
    ON chunks (document_id)
"""


CREATE_CHUNK_EXTRACTIONS = """
CREATE TABLE IF NOT EXISTS chunk_extractions (
    chunk_id    TEXT PRIMARY KEY
                REFERENCES chunks (chunk_id)
                ON DELETE CASCADE,
    payload     JSONB NOT NULL,
    model       TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


# Which resolved entities each chunk mentions. The spec calls the shared
# chunk id "the whole trick": it lets a vector hit jump into the graph
# neighbourhood, and a graph path jump back to citable text.
CREATE_CHUNK_ENTITIES = """
CREATE TABLE IF NOT EXISTS chunk_entities (
    chunk_id    TEXT NOT NULL
                REFERENCES chunks (chunk_id)
                ON DELETE CASCADE,
    entity_id   TEXT NOT NULL,
    entity_name TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    PRIMARY KEY (chunk_id, entity_id)
)
"""


CREATE_CHUNK_ENTITIES_ENTITY_INDEX = """
CREATE INDEX IF NOT EXISTS chunk_entities_entity_id_idx
    ON chunk_entities (entity_id)
"""


CREATE_ROUTING_DECISIONS = """
CREATE TABLE IF NOT EXISTS routing_decisions (
    trace_id    TEXT PRIMARY KEY,
    question    TEXT NOT NULL,
    route       TEXT NOT NULL,
    confidence  DOUBLE PRECISION,
    fallback    BOOLEAN NOT NULL DEFAULT false,
    hit_count   INTEGER,
    latency_ms  DOUBLE PRECISION,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


STATEMENTS = [
    CREATE_EXTENSION,
    CREATE_DOCUMENTS,
    CREATE_CHUNKS,
    CREATE_CHUNKS_DOCUMENT_INDEX,
    CREATE_CHUNK_EXTRACTIONS,
    CREATE_CHUNK_ENTITIES,
    CREATE_CHUNK_ENTITIES_ENTITY_INDEX,
    CREATE_ROUTING_DECISIONS,
]


def create_schema() -> None:

    with engine.begin() as connection:

        for statement in STATEMENTS:
            connection.execute(text(statement))


if __name__ == "__main__":

    create_schema()

    print("schema created")

    with engine.connect() as connection:

        for table in ("documents", "chunks"):

            count = connection.execute(
                text(f"SELECT count(*) FROM {table}")
            ).scalar()

            print(f"{table}: {count} rows")
