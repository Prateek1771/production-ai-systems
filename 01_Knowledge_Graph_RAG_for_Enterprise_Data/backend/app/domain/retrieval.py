from dataclasses import dataclass, field
from enum import StrEnum


@dataclass
class SearchHit:
    chunk_id: str
    document_id: str
    filename: str
    chunk_index: int
    text: str
    similarity: float


@dataclass
class GraphFact:
    """One traversal result, verbalised and carrying its provenance."""

    statement: str
    chunk_ids: list[str]
    hops: int
    relation_path: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    score: float = 0.0


class Route(StrEnum):
    VECTOR = "vector"
    GRAPH = "graph"
    HYBRID = "hybrid"


@dataclass
class RetrievalResult:
    """What the router hands to context building."""

    route: Route
    passages: list[SearchHit] = field(default_factory=list)
    facts: list[GraphFact] = field(default_factory=list)
    question_entities: list[str] = field(default_factory=list)
    confidence: float = 0.0
    fallback: bool = False

    @property
    def chunk_ids(self) -> set[str]:
        ids = {hit.chunk_id for hit in self.passages}
        for fact in self.facts:
            ids.update(fact.chunk_ids)
        return ids
