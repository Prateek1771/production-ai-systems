"""Local Ollama chat client. The last-resort provider.

Slow on this machine (no GPU, roughly 3 tokens per second) but it has no
quota, which is the one thing the hosted providers cannot offer. When
Groq's 200k daily cap is spent and OpenRouter is unreliable, this
finishes the job overnight instead of not at all.

Small local models produce genuinely bad extractions: reversed edges,
invented entity types, self-loops. That is survivable here only because
`validate_extraction` rejects all three mechanically.
"""

import json

import httpx
import ollama
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config.settings import settings
from app.llm.groq import _first_json_object


class OllamaClient:

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float = 600.0,
    ):
        self.model = model or settings.ollama_chat_model

        # Generous timeout: an 800 character chunk takes minutes on CPU.
        self.client = ollama.Client(
            host=base_url or settings.ollama_base_url,
            timeout=timeout,
        )

        self.prompt_tokens = 0
        self.completion_tokens = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, ollama.ResponseError)),
        reraise=True,
    )
    def _chat(self, prompt: str, temperature: float, as_json: bool):
        response = self.client.chat(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            format="json" if as_json else None,
            think=False,
            options={"temperature": temperature},
        )

        self._record(response)

        return response.message.content or ""

    def complete_text(self, prompt: str, temperature: float = 0.0) -> str:
        return self._chat(prompt, temperature, as_json=False)

    def complete_json(self, prompt: str) -> dict:
        raw = self._chat(prompt, 0.0, as_json=True)

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            payload = _first_json_object(raw)
            if payload is None:
                raise
            return payload

    def _record(self, response) -> None:
        self.prompt_tokens += getattr(response, "prompt_eval_count", 0) or 0
        self.completion_tokens += getattr(response, "eval_count", 0) or 0


if __name__ == "__main__":

    import time

    client = OllamaClient()

    print("model:", client.model)

    started = time.perf_counter()
    print("json :", client.complete_json('Return JSON: {"ok":true}'))
    print("took : %.1fs" % (time.perf_counter() - started))
    print("tokens:", client.total_tokens)
