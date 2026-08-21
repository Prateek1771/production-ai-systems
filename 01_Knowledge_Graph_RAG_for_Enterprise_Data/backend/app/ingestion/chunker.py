import re
from hashlib import sha256

from app.domain.chunk import Chunk
from app.domain.document import Document


class ParagraphChunker:

    def __init__(
        self,
        max_characters: int = 800,
        overlap_characters: int = 100,
    ):
        self.max_characters = max_characters
        self.overlap_characters = overlap_characters

    def chunk(self, document: Document) -> list[Chunk]:

        paragraphs = self._split_paragraphs(document.content)

        chunks: list[Chunk] = []
        current_parts: list[str] = []
        current_length = 0

        for paragraph in paragraphs:

            # A paragraph too large to ever fit in one chunk.
            if len(paragraph) > self.max_characters:

                # Don't lose what we were accumulating.
                if current_parts:
                    chunks.append(
                        self._create_chunk(
                            document,
                            current_parts,
                            len(chunks),
                        )
                    )

                    current_parts = []
                    current_length = 0

                for part in self._split_large_paragraph(paragraph):
                    chunks.append(
                        self._create_chunk(
                            document,
                            [part],
                            len(chunks),
                        )
                    )

                continue

            # It fits, but not alongside what we already have.
            if (
                current_parts
                and current_length + len(paragraph) > self.max_characters
            ):
                chunks.append(
                    self._create_chunk(
                        document,
                        current_parts,
                        len(chunks),
                    )
                )

                current_parts = self._get_overlap(current_parts)

                current_length = sum(
                    len(part) for part in current_parts
                )

            current_parts.append(paragraph)
            current_length += len(paragraph)

        if current_parts:
            chunks.append(
                self._create_chunk(
                    document,
                    current_parts,
                    len(chunks),
                )
            )

        return chunks

    @staticmethod
    def _split_paragraphs(text: str) -> list[str]:

        paragraphs = re.split(r"\n\s*\n", text)

        return [
            paragraph.strip()
            for paragraph in paragraphs
            if paragraph.strip()
        ]

    def _split_large_paragraph(
        self,
        paragraph: str,
    ) -> list[str]:

        parts = []
        start = 0

        while start < len(paragraph):

            end = min(
                start + self.max_characters,
                len(paragraph),
            )

            part = paragraph[start:end].strip()

            if part:
                parts.append(part)

            if end == len(paragraph):
                break

            start = end - self.overlap_characters

        return parts

    def _get_overlap(
        self,
        parts: list[str],
    ) -> list[str]:

        overlap = []
        total = 0

        for part in reversed(parts):

            if total + len(part) > self.overlap_characters:
                break

            overlap.insert(0, part)
            total += len(part)

        return overlap

    @staticmethod
    def _create_chunk(
        document: Document,
        parts: list[str],
        index: int,
    ) -> Chunk:

        text = "\n\n".join(parts)

        raw_id = (
            f"{document.document_id}:"
            f"{index}:"
            f"{text}"
        )

        chunk_id = sha256(
            raw_id.encode("utf-8")
        ).hexdigest()

        return Chunk(
            chunk_id=chunk_id,
            document_id=document.document_id,
            chunk_index=index,
            text=text,
            metadata={
                "filename": document.filename,
                "source": document.source,
                "character_count": len(text),
            },
        )
