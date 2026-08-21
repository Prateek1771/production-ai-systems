"""OpenRouter client over its OpenAI-compatible chat endpoint.

Built on httpx, which is already a dependency, rather than adding the
openai package for two HTTP calls.
"""

import json

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.config.settings import settings
from app.llm.groq import _first_json_object


def _is_retryable(error: BaseException) -> bool:
    if isinstance(error, (httpx.TimeoutException, httpx.ConnectError)):
        return True

    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code in {408, 409, 429, 500, 502, 503, 504}

    return False


class OpenRouterClient:

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        timeout: float = 90.0,
    ):
        key = api_key or settings.openrouter_api_key

        if not key:
            raise RuntimeError("OPENROUTER_API_KEY is not set.")

        self.model = model or settings.openrouter_model

        self.client = httpx.Client(
            base_url=settings.openrouter_base_url,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )

        self.prompt_tokens = 0
        self.completion_tokens = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @retry(
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        retry=retry_if_exception(_is_retryable),
        reraise=True,
    )
    def _post(self, body: dict) -> dict:
        response = self.client.post("/chat/completions", json=body)
        response.raise_for_status()
        return response.json()

    def complete_text(self, prompt: str, temperature: float = 0.0) -> str:
        data = self._post(
            {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
            }
        )

        self._record(data)

        return data["choices"][0]["message"]["content"] or ""

    def complete_json(self, prompt: str) -> dict:
        data = self._post(
            {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "response_format": {"type": "json_object"},
            }
        )

        self._record(data)

        content = data["choices"][0]["message"]["content"] or "{}"

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            payload = _first_json_object(content)
            if payload is None:
                raise
            return payload

    def _record(self, data: dict) -> None:
        usage = data.get("usage") or {}
        self.prompt_tokens += usage.get("prompt_tokens") or 0
        self.completion_tokens += usage.get("completion_tokens") or 0

    def close(self) -> None:
        self.client.close()


if __name__ == "__main__":

    client = OpenRouterClient()
    print("model:", client.model)
    print("text :", client.complete_text("Reply with the single word OK."))
    print("json :", client.complete_json('Return JSON: {"ok":true}'))
    print("tokens:", client.total_tokens)
    client.close()
