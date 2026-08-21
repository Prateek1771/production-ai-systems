from dataclasses import dataclass, field


@dataclass
class Chunk:
    chunk_id: str
    document_id: str
    chunk_index: int
    text: str
    metadata: dict = field(default_factory=dict)