"""Request and response shapes for the HTTP API."""

from pydantic import BaseModel, Field

from app.domain.retrieval import Route


class QueryRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=20)
    route: Route | None = None
    include_graph: bool = True


class CitationOut(BaseModel):
    marker: int
    kind: str
    chunk_ids: list[str]
    text: str


class PassageOut(BaseModel):
    chunk_id: str
    filename: str
    chunk_index: int
    similarity: float
    text: str


class FactOut(BaseModel):
    statement: str
    hops: int
    chunk_ids: list[str]
    relation_path: list[str]


class GraphNodeOut(BaseModel):
    id: str
    name: str
    entity_type: str | None = None
    mentions: int | None = None


class GraphEdgeOut(BaseModel):
    source: str
    target: str
    relation: str


class GraphOut(BaseModel):
    nodes: list[GraphNodeOut] = []
    edges: list[GraphEdgeOut] = []


class QueryResponse(BaseModel):
    trace_id: str
    question: str
    answer: str
    refused: bool
    repaired: bool
    route: Route
    confidence: float
    question_entities: list[str] = []
    citations: list[CitationOut] = []
    passages: list[PassageOut] = []
    facts: list[FactOut] = []
    graph: GraphOut | None = None
    stages: dict[str, float] = {}
    total_ms: float = 0.0


class IngestRequest(BaseModel):
    directory: str | None = None
    embed: bool = True
    extract: bool = False
    build_graph: bool = False


class IngestResponse(BaseModel):
    documents_written: int
    documents_skipped: int
    chunks_written: int
    embeddings_added: int = 0
    extractions_added: int = 0
    graph: dict = {}


class ChunkOut(BaseModel):
    chunk_id: str
    document_id: str
    filename: str
    chunk_index: int
    text: str


class StatsResponse(BaseModel):
    documents: int
    chunks: int
    embedded: int
    extracted: int
    entities: int
    relations: int
    mentions: int
