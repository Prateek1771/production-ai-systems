"""A closed library of parameterised Cypher templates.

The spec is explicit that the model must never emit Cypher. It picks a
template name and fills parameters; the query text itself is written
here and reviewed once. That is a security control, and it also makes
results reproducible rather than dependent on what the model felt like
generating.

Every template returns chunk_ids so a graph answer can be cited.
"""

from enum import StrEnum


class QueryTemplate(StrEnum):
    ENTITY_LOOKUP = "entity_lookup"
    NEIGHBOURS = "neighbours"
    TWO_HOP = "two_hop"
    THREE_HOP = "three_hop"
    SHARED_NEIGHBOUR = "shared_neighbour"
    RELATION_OF_TYPE = "relation_of_type"
    COUNT_BY_RELATION = "count_by_relation"
    NEIGHBOURHOOD_GRAPH = "neighbourhood_graph"


# Resolve a surface form to nodes. Matches canonical name, the
# lowercase form, or any stored alias.
ENTITY_LOOKUP = """
MATCH (e:Entity)
WHERE toLower(e.name) = toLower($name)
   OR e.normalized = toLower($name)
   OR any(a IN e.aliases WHERE toLower(a) = toLower($name))
RETURN e.entity_id AS entity_id,
       e.name AS name,
       e.entity_type AS entity_type,
       e.aliases AS aliases,
       e.mentions AS mentions
ORDER BY e.mentions DESC
LIMIT $limit
"""


# Fuzzy fallback when an exact or alias match finds nothing.
ENTITY_SEARCH = """
MATCH (e:Entity)
WHERE e.normalized CONTAINS toLower($name)
   OR toLower($name) CONTAINS e.normalized
RETURN e.entity_id AS entity_id,
       e.name AS name,
       e.entity_type AS entity_type,
       e.aliases AS aliases,
       e.mentions AS mentions
ORDER BY e.mentions DESC
LIMIT $limit
"""


NEIGHBOURS = """
MATCH (a:Entity {entity_id: $entity_id})-[r]->(b:Entity)
RETURN a.name AS source, type(r) AS relation, b.name AS target,
       b.entity_type AS target_type, r.chunk_ids AS chunk_ids,
       r.confidence AS confidence, 1 AS hops
UNION
MATCH (a:Entity {entity_id: $entity_id})<-[r]-(b:Entity)
RETURN b.name AS source, type(r) AS relation, a.name AS target,
       a.entity_type AS target_type, r.chunk_ids AS chunk_ids,
       r.confidence AS confidence, 1 AS hops
"""


TWO_HOP = """
MATCH path = (a:Entity {entity_id: $entity_id})-[r1]-(mid:Entity)-[r2]-(b:Entity)
WHERE b.entity_id <> a.entity_id AND mid.entity_id <> b.entity_id
RETURN a.name AS start,
       type(r1) AS relation_1, mid.name AS middle,
       type(r2) AS relation_2, b.name AS end,
       b.entity_type AS end_type,
       r1.chunk_ids + r2.chunk_ids AS chunk_ids,
       2 AS hops
LIMIT $limit
"""


THREE_HOP = """
MATCH path = (a:Entity {entity_id: $entity_id})-[r1]-(m1:Entity)-[r2]-(m2:Entity)-[r3]-(b:Entity)
WHERE b.entity_id <> a.entity_id
  AND m1.entity_id <> m2.entity_id
  AND m2.entity_id <> a.entity_id
  AND b.entity_id <> m1.entity_id
RETURN a.name AS start,
       type(r1) AS relation_1, m1.name AS middle_1,
       type(r2) AS relation_2, m2.name AS middle_2,
       type(r3) AS relation_3, b.name AS end,
       r1.chunk_ids + r2.chunk_ids + r3.chunk_ids AS chunk_ids,
       3 AS hops
LIMIT $limit
"""


# What connects two named entities. This is the shape that answers
# "which cloud provider does OpenAI use", where the answer sits on a
# path rather than in a passage.
SHARED_NEIGHBOUR = """
MATCH path = (a:Entity {entity_id: $source_id})-[r1]-(mid:Entity)-[r2]-(b:Entity {entity_id: $target_id})
RETURN a.name AS start,
       type(r1) AS relation_1, mid.name AS middle,
       mid.entity_type AS middle_type,
       type(r2) AS relation_2, b.name AS end,
       r1.chunk_ids + r2.chunk_ids AS chunk_ids,
       2 AS hops
LIMIT $limit
"""


# The relation type is validated against the RelationType enum before
# it reaches the format call. Never interpolate raw model output.
RELATION_OF_TYPE_TEMPLATE = """
MATCH (a:Entity)-[r:{relation_type}]->(b:Entity)
WHERE $entity_id IS NULL
   OR a.entity_id = $entity_id
   OR b.entity_id = $entity_id
RETURN a.name AS source, type(r) AS relation, b.name AS target,
       b.entity_type AS target_type, r.chunk_ids AS chunk_ids,
       1 AS hops
LIMIT $limit
"""


COUNT_BY_RELATION = """
MATCH (a:Entity {entity_id: $entity_id})-[r]-(b:Entity)
RETURN type(r) AS relation, count(DISTINCT b) AS degree,
       collect(DISTINCT b.name)[0..12] AS examples
ORDER BY degree DESC
"""


# Feeds the frontend graph view.
NEIGHBOURHOOD_GRAPH = """
MATCH (a:Entity)
WHERE a.entity_id IN $entity_ids
OPTIONAL MATCH (a)-[r]-(b:Entity)
WITH collect(DISTINCT a) + collect(DISTINCT b) AS nodes,
     collect(DISTINCT r) AS rels
UNWIND nodes AS n
WITH collect(DISTINCT {
        id: n.entity_id, name: n.name,
        entity_type: n.entity_type, mentions: n.mentions
     }) AS node_rows, rels
RETURN node_rows AS nodes,
       [r IN rels WHERE r IS NOT NULL | {
           source: startNode(r).entity_id,
           target: endNode(r).entity_id,
           relation: type(r)
       }] AS edges
"""


CHUNKS_FOR_ENTITY = """
MATCH (e:Entity {entity_id: $entity_id})-[:MENTIONED_IN]->(c:Chunk)
RETURN c.chunk_id AS chunk_id, c.filename AS filename,
       c.chunk_index AS chunk_index
LIMIT $limit
"""


TEMPLATES: dict[QueryTemplate, str] = {
    QueryTemplate.ENTITY_LOOKUP: ENTITY_LOOKUP,
    QueryTemplate.NEIGHBOURS: NEIGHBOURS,
    QueryTemplate.TWO_HOP: TWO_HOP,
    QueryTemplate.THREE_HOP: THREE_HOP,
    QueryTemplate.SHARED_NEIGHBOUR: SHARED_NEIGHBOUR,
    QueryTemplate.COUNT_BY_RELATION: COUNT_BY_RELATION,
    QueryTemplate.NEIGHBOURHOOD_GRAPH: NEIGHBOURHOOD_GRAPH,
}
