from pathlib import Path

from app.domain.chunk import Chunk
from app.domain.document import Document
from app.ingestion.chunker import ParagraphChunker
from app.ingestion.loader import TextDocumentLoader


class IngestionPipeline:

    def __init__(self):
        self.loader = TextDocumentLoader()
        self.chunker = ParagraphChunker()

    def process_file(
        self,
        file_path: Path,
    ) -> tuple[Document, list[Chunk]]:

        document = self.loader.load(file_path)

        chunks = self.chunker.chunk(document)

        return document, chunks

    def process_directory(
        self,
        directory: Path,
    ) -> list[tuple[Document, list[Chunk]]]:

        results = []

        for file_path in sorted(directory.glob("*.txt")):

            document, chunks = self.process_file(
                file_path
            )

            results.append(
                (document, chunks)
            )

        return results