import json
from pathlib import Path

from sqlalchemy import Connection, text

from app.domain.chunk import Chunk
from app.domain.document import Document
from app.infrastructure.postgres import engine
from app.ingestion.pipeline import IngestionPipeline
from app.vector.embeddings import EmbeddingClient


SELECT_CONTENT_HASH = """
SELECT content_hash
FROM documents
WHERE document_id = :document_id
"""


DELETE_DOCUMENT = """
DELETE FROM documents
WHERE document_id = :document_id
"""


INSERT_DOCUMENT = """
INSERT INTO documents (
    document_id,
    filename,
    source,
    title,
    content,
    content_hash,
    metadata
)
VALUES (
    :document_id,
    :filename,
    :source,
    :title,
    :content,
    :content_hash,
    CAST(:metadata AS jsonb)
)
"""


INSERT_CHUNK = """
INSERT INTO chunks (
    chunk_id,
    document_id,
    chunk_index,
    text,
    metadata
)
VALUES (
    :chunk_id,
    :document_id,
    :chunk_index,
    :text,
    CAST(:metadata AS jsonb)
)
ON CONFLICT (chunk_id) DO NOTHING
"""


SELECT_MISSING_EMBEDDINGS = """
SELECT chunk_id, text AS chunk_text
FROM chunks
WHERE embedding IS NULL
ORDER BY document_id, chunk_index
LIMIT :limit
"""


UPDATE_EMBEDDING = """
UPDATE chunks
SET embedding = CAST(:embedding AS vector)
WHERE chunk_id = :chunk_id
"""


def to_vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(repr(value) for value in vector) + "]"


def upsert_document(
    connection: Connection,
    document: Document,
) -> bool:
    """Insert or replace a document. True if anything was written."""

    existing_hash = connection.execute(
        text(SELECT_CONTENT_HASH),
        {"document_id": document.document_id},
    ).scalar()

    if existing_hash == document.content_hash:
        return False

    if existing_hash is not None:
        # Content changed. Remove the old row and let
        # ON DELETE CASCADE clear its stale chunks.
        connection.execute(
            text(DELETE_DOCUMENT),
            {"document_id": document.document_id},
        )

    connection.execute(
        text(INSERT_DOCUMENT),
        {
            "document_id": document.document_id,
            "filename": document.filename,
            "source": document.source,
            "title": document.title,
            "content": document.content,
            "content_hash": document.content_hash,
            "metadata": json.dumps(document.metadata),
        },
    )

    return True


def insert_chunks(
    connection: Connection,
    chunks: list[Chunk],
) -> int:

    if not chunks:
        return 0

    connection.execute(
        text(INSERT_CHUNK),
        [
            {
                "chunk_id": chunk.chunk_id,
                "document_id": chunk.document_id,
                "chunk_index": chunk.chunk_index,
                "text": chunk.text,
                "metadata": json.dumps(chunk.metadata),
            }
            for chunk in chunks
        ],
    )

    return len(chunks)


def ingest_corpus(directory: Path) -> tuple[int, int, int]:
    """Returns (documents written, documents skipped, chunks written)."""

    results = IngestionPipeline().process_directory(directory)

    written = 0
    skipped = 0
    chunk_count = 0

    # ponytail: one transaction for the whole corpus. Fine at 23
    # documents. Move to per-document transactions if a single
    # bad file should not roll back the rest.
    with engine.begin() as connection:

        for document, chunks in results:

            if upsert_document(connection, document):
                chunk_count += insert_chunks(connection, chunks)
                written += 1
            else:
                skipped += 1

    return written, skipped, chunk_count


def backfill_embeddings(batch_size: int = 32) -> int:

    client = EmbeddingClient(batch_size=batch_size)

    total = 0

    while True:

        with engine.begin() as connection:

            rows = connection.execute(
                text(SELECT_MISSING_EMBEDDINGS),
                {"limit": batch_size},
            ).fetchall()

            if not rows:
                return total

            vectors = client.embed_texts(
                [row.chunk_text for row in rows]
            )

            connection.execute(
                text(UPDATE_EMBEDDING),
                [
                    {
                        "chunk_id": row.chunk_id,
                        "embedding": to_vector_literal(vector),
                    }
                    for row, vector in zip(rows, vectors)
                ],
            )

            total += len(rows)

            print(f"embedded {total} chunks")


if __name__ == "__main__":

    data_directory = Path(__file__).parents[3] / "data" / "raw"

    written, skipped, chunk_count = ingest_corpus(data_directory)

    print(f"documents written : {written}")
    print(f"documents skipped : {skipped}")
    print(f"chunks written    : {chunk_count}")

    embedded = backfill_embeddings()

    print(f"embeddings added  : {embedded}")
