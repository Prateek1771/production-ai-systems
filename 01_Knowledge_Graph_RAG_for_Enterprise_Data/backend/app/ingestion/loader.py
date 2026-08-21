from hashlib import sha256
from pathlib import Path

from app.domain.document import Document


class TextDocumentLoader:

    def load(self, file_path: Path) -> Document:
        content = file_path.read_text(
            encoding="utf-8",
            errors="replace",
        ).strip()

        return Document(
            document_id=self._generate_document_id(file_path),
            filename=file_path.name,
            source="local",
            title=file_path.stem.replace("_", " ").title(),
            content=content,
            content_hash=self._generate_content_hash(content),
            metadata={
                "file_path": str(file_path),
                "file_size": file_path.stat().st_size,
            },
        )

    @staticmethod
    def _generate_document_id(file_path: Path) -> str:
        value = f"local:{file_path.name}"

        return sha256(
            value.encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _generate_content_hash(content: str) -> str:
        return sha256(
            content.encode("utf-8")
        ).hexdigest()