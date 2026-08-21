from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class Document:
    document_id: str
    filename: str
    source: str
    title: str
    content: str
    content_hash: str
    metadata: dict = field(default_factory=dict)
    created_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )