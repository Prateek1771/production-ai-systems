import json
import re
import time


import groq
from tenacity import retry, retry_if_exception, stop_after_attempt

from app.config.settings import settings


def _first_json_object(raw: str) -> dict | None:
    """Pull the first balanced {...} out of a text response."""

    fenced = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M)

    start = fenced.find("{")
    if start == -1:
        return None

    depth = 0
    for index in range(start, len(fenced)):
        if fenced[index] == "{":
            depth += 1
        elif fenced[index] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(fenced[start : index + 1])
                except json.JSONDecodeError:
                    return None

    return None


def _wait_for_error(state) -> float:
    """Two different failures need two different waits.

    A tokens-per-minute 429 needs to sit out most of a minute. A
    json_validate_failed 400 is instant-retryable, and giving it the
    same long wait made a 25% failure rate cost minutes per chunk.
    """

    error = state.outcome.exception() if state.outcome else None

    if isinstance(error, groq.RateLimitError):
        return min(60.0, 15.0 * state.attempt_number)

    return min(4.0, 0.5 * state.attempt_number)


def _is_retryable(error: BaseException) -> bool:
    """Transient Groq failures, including its flaky JSON validator."""

    if isinstance(
        error,
        (
            groq.RateLimitError,
            groq.APIConnectionError,
            groq.APITimeoutError,
            groq.InternalServerError,
        ),
    ):
        return True

    # Groq returns 400 json_validate_failed with an empty
    # failed_generation. Measured at 16-28% of calls, non-deterministic
    # at temperature 0, and the same prompt succeeds on retry. A 400
    # normally means stop, so we match on the message not the status.
    if isinstance(error, groq.BadRequestError):
        return "json_validate_failed" in str(error)

    return False


_DURATION = re.compile(r"(?:(\d+(?:\.\d+)?)h)?(?:(\d+(?:\.\d+)?)m(?!s))?(?:(\d+(?:\.\d+)?)s)?(?:(\d+(?:\.\d+)?)ms)?")


def parse_reset(value: str | None) -> float:
    """Groq sends durations like '577ms', '51.885s', '1h45m7.2s'."""

    if not value:
        return 0.0

    match = _DURATION.fullmatch(value.strip())

    if not match:
        return 0.0

    hours, minutes, seconds, millis = (
        float(group) if group else 0.0 for group in match.groups()
    )

    return hours * 3600 + minutes * 60 + seconds + millis / 1000


class _TokenPacer:
    """Wait on the server's own token accounting rather than modelling it.

    Groq refills continuously (x-ratelimit-reset-tokens comes back as
    577ms, not 60s), so a self-managed 60 second window is the wrong
    shape. Worse, a fresh window on process start knows nothing about
    what the previous run already spent, so it bursts straight into a
    429. Reading remaining and reset off every response is both simpler
    and correct across restarts.
    """

    def __init__(self, floor: int = 1500):
        self.floor = floor
        self.remaining: int | None = None
        self.reset_in = 0.0
        self.limit: int | None = None
        self.slept_seconds = 0.0

    def observe(self, headers) -> None:
        remaining = headers.get("x-ratelimit-remaining-tokens")
        limit = headers.get("x-ratelimit-limit-tokens")

        if remaining is not None:
            try:
                self.remaining = int(remaining)
            except ValueError:
                pass

        if limit is not None:
            try:
                self.limit = int(limit)
            except ValueError:
                pass

        self.reset_in = parse_reset(headers.get("x-ratelimit-reset-tokens"))

    def reserve(self, estimated: int, verbose: bool = False) -> None:
        if self.remaining is None:
            return

        needed = max(estimated, self.floor)

        if self.remaining >= needed:
            return

        wait = min(65.0, max(self.reset_in, 1.0) + 0.5)

        if verbose:
            print(
                f"       pacing {wait:.1f}s "
                f"(server says {self.remaining} tokens left)"
            )

        self.slept_seconds += wait
        time.sleep(wait)

        # Assume the bucket refilled. The next response corrects us.
        self.remaining = self.limit or None


class GroqClient:

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        timeout: float = 60.0,
        verbose_pacing: bool = False,
        reasoning_effort: str | None = None,
    ):
        key = api_key or settings.groq_api_key

        if not key:
            raise RuntimeError(
                "GROQ_API_KEY is not set. Check that backend/.env is "
                "being loaded."
            )

        self.model = model or settings.groq_model
        self.verbose_pacing = verbose_pacing

        # gpt-oss emits reasoning tokens that dominate the bill and make
        # Groq's JSON validator fail far more often. Measured: default
        # effort is 1956 tokens per call with 43% of chunks failing every
        # retry, "low" is 733 tokens and near-zero failures.
        self.reasoning_effort = (
            reasoning_effort
            if reasoning_effort is not None
            else settings.groq_reasoning_effort
        )

        self.salvaged = 0

        self.pacer = _TokenPacer()

        # Rough cost of one call, refined from real usage as we go.
        self._estimate = 1200

        # max_retries=0 because tenacity owns retrying. Leaving the
        # SDK's default of 2 on top would give up to 12 attempts across
        # two independent backoff schedules.
        self.client = groq.Groq(
            api_key=key,
            timeout=timeout,
            max_retries=0,
        )

        self.prompt_tokens = 0
        self.completion_tokens = 0

    def _extra(self) -> dict:
        return (
            {"reasoning_effort": self.reasoning_effort}
            if self.reasoning_effort
            else {}
        )

    def complete_json(self, prompt: str) -> dict:
        """JSON mode, with a plain-text salvage if the validator gives up."""

        try:
            return self._complete_json_strict(prompt)
        except groq.BadRequestError as error:
            if "json_validate_failed" not in str(error):
                raise

        # Groq's validator rejected a generation it never produced,
        # repeatedly. Ask for the same thing without the constraint and
        # pull the JSON out ourselves rather than losing the chunk.
        raw = self.complete_text(
            prompt + "\nReply with JSON only. No prose, no code fences.",
        )

        payload = _first_json_object(raw)

        if payload is None:
            raise ValueError("no JSON object in salvage response")

        self.salvaged += 1
        return payload

    def _create(self, **body):
        """One place where a request is sent, so limits are always read."""

        self.pacer.reserve(self._estimate, self.verbose_pacing)

        raw = self.client.chat.completions.with_raw_response.create(**body)

        self.pacer.observe(raw.headers)

        response = raw.parse()
        self._record(response)

        return response

    @retry(
        stop=stop_after_attempt(4),
        wait=_wait_for_error,
        retry=retry_if_exception(_is_retryable),
        reraise=True,
    )
    def _complete_json_strict(self, prompt: str) -> dict:

        response = self._create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0,
            **self._extra(),
        )

        return json.loads(response.choices[0].message.content or "{}")

    @retry(
        stop=stop_after_attempt(5),
        wait=_wait_for_error,
        retry=retry_if_exception(_is_retryable),
        reraise=True,
    )
    def complete_text(self, prompt: str, temperature: float = 0.0) -> str:

        response = self._create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            **self._extra(),
        )

        return response.choices[0].message.content or ""

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def _record(self, response) -> None:
        usage = getattr(response, "usage", None)

        if not usage:
            return

        used = (usage.prompt_tokens or 0) + (usage.completion_tokens or 0)

        self.prompt_tokens += usage.prompt_tokens or 0
        self.completion_tokens += usage.completion_tokens or 0

        # Track the real cost so pacing tightens or loosens to match.
        self._estimate = max(200, int(0.7 * self._estimate + 0.3 * used))


if __name__ == "__main__":

    client = GroqClient()

    print("model:", client.model)

    result = client.complete_json(
        'Return JSON: {"entities":[{"name":"NVIDIA","type":"Company"}]}'
    )

    print("json  :", result)
    print("text  :", client.complete_text("Reply with the single word OK."))
    print("tokens:", client.prompt_tokens, "+", client.completion_tokens)
