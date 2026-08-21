"""The provider interface, and a gateway that falls back between providers.

This file deliberately did not exist until there were two real
implementations. A Protocol with one implementation is indirection that
costs a file and returns nothing, and an interface designed against a
single provider is usually the wrong shape when the second arrives.

Groq and OpenRouter are both configured, so now it earns its place.

Protocol rather than ABC because neither client inherits from anything:
structural typing checks the shape without forcing a base class on code
that already works.
"""

from typing import Protocol, runtime_checkable

from app.config.settings import settings


@runtime_checkable
class LLMClient(Protocol):
    model: str

    def complete_text(self, prompt: str, temperature: float = 0.0) -> str: ...

    def complete_json(self, prompt: str) -> dict: ...


class LLMGateway:
    """Try providers in order. First one that answers wins."""

    def __init__(
        self,
        clients: list[LLMClient] | None = None,
        include_local: bool = False,
    ):
        self.clients = (
            clients
            if clients is not None
            else default_clients(include_local=include_local)
        )

        if not self.clients:
            raise RuntimeError(
                "No LLM provider configured. Set GROQ_API_KEY or "
                "OPENROUTER_API_KEY in backend/.env."
            )

        self.failovers = 0
        self.last_provider = ""

    def complete_text(self, prompt: str, temperature: float = 0.0) -> str:
        return self._call("complete_text", prompt, temperature=temperature)

    def complete_json(self, prompt: str) -> dict:
        return self._call("complete_json", prompt)

    def _call(self, method: str, prompt: str, **kwargs):
        errors: list[str] = []

        for index, client in enumerate(self.clients):
            try:
                value = getattr(client, method)(prompt, **kwargs)
                self.last_provider = type(client).__name__
                if index:
                    self.failovers += 1
                return value
            except Exception as error:
                errors.append(f"{type(client).__name__}: {type(error).__name__}")

        raise RuntimeError(f"all providers failed ({'; '.join(errors)})")

    @property
    def total_tokens(self) -> int:
        return sum(getattr(c, "total_tokens", 0) for c in self.clients)


def default_clients(include_local: bool = False) -> list[LLMClient]:
    """Fastest first, then most reliable, then the one with no quota.

    Groq is 0.7s per call and free up to 200k tokens per day. OpenRouter
    is slower and costs fractions of a cent. Ollama is minutes per call
    on a CPU-only box but has no limit at all, so it is opt-in: you want
    it for an unattended bulk job, not on a request path where it would
    turn a 2 second query into a 3 minute one.
    """

    clients: list[LLMClient] = []

    if settings.groq_api_key:
        from app.llm.groq import GroqClient

        clients.append(GroqClient())

    if settings.openrouter_api_key:
        from app.llm.openrouter import OpenRouterClient

        clients.append(OpenRouterClient())

    if include_local:
        from app.llm.ollama import OllamaClient

        clients.append(OllamaClient())

    return clients


if __name__ == "__main__":

    gateway = LLMGateway()

    print("providers:", [type(c).__name__ for c in gateway.clients])
    print("text     :", gateway.complete_text("Reply with the single word OK."))
    print("served by:", gateway.last_provider)

    # Both clients satisfy the Protocol without inheriting from it.
    for client in gateway.clients:
        print(f"  {type(client).__name__:<20} isinstance(LLMClient) =",
              isinstance(client, LLMClient))
