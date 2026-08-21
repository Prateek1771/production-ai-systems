import httpx
import ollama

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config.settings import settings


class EmbeddingClient:

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        batch_size: int = 32,
        timeout: float = 60.0,
    ):
        self.model = model or settings.ollama_embedding_model
        self.batch_size = batch_size

        self.client = ollama.Client(
            host=base_url or settings.ollama_base_url,
            timeout=timeout,
        )

    def embed_texts(
        self,
        texts: list[str],
    ) -> list[list[float]]:

        if not texts:
            return []

        vectors: list[list[float]] = []

        for start in range(0, len(texts), self.batch_size):

            batch = texts[start:start + self.batch_size]

            vectors.extend(self._embed_batch(batch))

        if len(vectors) != len(texts):
            raise RuntimeError(
                f"embedding count mismatch: "
                f"sent {len(texts)}, got {len(vectors)}"
            )

        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(
            (httpx.HTTPError, ollama.ResponseError)
        ),
        reraise=True,
    )
    def _embed_batch(
        self,
        batch: list[str],
    ) -> list[list[float]]:

        response = self.client.embed(
            model=self.model,
            input=batch,
        )

        return [
            list(vector)
            for vector in response.embeddings
        ]


if __name__ == "__main__":

    client = EmbeddingClient()

    vectors = client.embed_texts(
        [
            "NVIDIA designs graphics processing units.",
            "Anthropic is an AI safety company.",
        ]
    )

    print(f"texts embedded : {len(vectors)}")
    print(f"dimensions     : {len(vectors[0])}")
    print(f"first 5 floats : {vectors[0][:5]}")

    single = client.embed_query("Who runs NVIDIA?")

    print(f"embed_query    : {len(single)} floats, flat")
