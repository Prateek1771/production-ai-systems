from sqlalchemy import text

from app.config.settings import settings
from app.domain.retrieval import SearchHit
from app.infrastructure.postgres import engine
from app.vector.embeddings import EmbeddingClient
from app.vector.repository import to_vector_literal


SEARCH_CHUNKS = """
SELECT
    chunk_id,
    document_id,
    chunk_index,
    text,
    metadata->>'filename' AS filename,
    1 - (embedding <=> CAST(:query AS vector)) AS similarity
FROM chunks
WHERE embedding IS NOT NULL
ORDER BY embedding <=> CAST(:query AS vector)
LIMIT :limit
"""


CREATE_HNSW_INDEX = """
CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw_idx
    ON chunks
    USING hnsw (embedding vector_cosine_ops)
"""


class VectorStore:

    def __init__(
        self,
        client: EmbeddingClient | None = None,
        ef_search: int | None = None,
    ):
        self.client = client or EmbeddingClient()
        self.ef_search = (
            ef_search if ef_search is not None else settings.hnsw_ef_search
        )

    def search(
        self,
        question: str,
        limit: int = 5,
        ef_search: int | None = None,
    ) -> list[SearchHit]:

        query_vector = to_vector_literal(
            self.client.embed_query(question)
        )

        return self.search_vector(query_vector, limit, ef_search)

    def search_vector(
        self,
        query_vector: str,
        limit: int = 5,
        ef_search: int | None = None,
    ) -> list[SearchHit]:
        """Takes an already-formatted vector literal, so callers that
        embed once can run several searches without re-embedding."""

        with engine.connect() as connection:

            # hnsw.ef_search trades recall against latency. SET LOCAL
            # needs a transaction, so this one is session-scoped and
            # dies with the connection.
            connection.execute(
                text(f"SET hnsw.ef_search = {int(ef_search or self.ef_search)}")
            )

            rows = connection.execute(
                text(SEARCH_CHUNKS),
                {
                    "query": query_vector,
                    "limit": limit,
                },
            ).fetchall()

        return [
            SearchHit(
                chunk_id=row.chunk_id,
                document_id=row.document_id,
                filename=row.filename,
                chunk_index=row.chunk_index,
                text=row.text,
                similarity=float(row.similarity),
            )
            for row in rows
        ]


def create_index() -> None:
    with engine.begin() as connection:
        connection.execute(text(CREATE_HNSW_INDEX))


if __name__ == "__main__":

    create_index()

    store = VectorStore()

    questions = [
        "Who runs NVIDIA?",
        "What is Anthropic focused on?",
        "Which cloud provider does OpenAI use?",
    ]

    for question in questions:

        print()
        print("=" * 78)
        print("Q:", question)
        print()

        for hit in store.search(question, limit=5):

            preview = " ".join(hit.text.split())[:60]

            print(
                f"  {hit.similarity:.4f}  "
                f"{hit.filename:<22} #{hit.chunk_index}  "
                f"{preview}"
            )
