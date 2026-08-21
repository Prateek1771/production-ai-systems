"""Validate that every citation in an answer resolves to retrieved context.

This is the step that eliminates invented sources. The spec puts it
plainly: require a citation per claim, then check every citation against
what was actually retrieved, and reject when it does not resolve.

An answer that cites [7] when only [1] through [5] were retrieved is
not a formatting problem. It means the model produced a claim it cannot
support, and shipping it with a plausible-looking marker is worse than
refusing.
"""

import re
from dataclasses import dataclass, field

from app.generation.context import BuiltContext
from app.generation.prompts import (
    ANSWER_PROMPT,
    INSUFFICIENT,
    REFUSAL,
    REPAIR_PROMPT,
)
from app.llm.groq import GroqClient


CITATION_PATTERN = re.compile(r"\[(\d+)\]")

# A sentence that states a fact. Skips the refusal and empty fragments.
SENTENCE_PATTERN = re.compile(r"[^.!?]+[.!?]")


@dataclass
class Citation:
    marker: int
    chunk_ids: list[str]
    kind: str
    text: str


@dataclass
class ValidatedAnswer:
    answer: str
    citations: list[Citation] = field(default_factory=list)
    invalid_markers: list[int] = field(default_factory=list)
    uncited_sentences: list[str] = field(default_factory=list)
    repaired: bool = False
    refused: bool = False

    @property
    def chunk_ids(self) -> list[str]:
        ids: list[str] = []
        for citation in self.citations:
            for chunk_id in citation.chunk_ids:
                if chunk_id not in ids:
                    ids.append(chunk_id)
        return ids


def extract_markers(answer: str) -> list[int]:
    return [int(m) for m in CITATION_PATTERN.findall(answer)]


def find_uncited_sentences(answer: str) -> list[str]:
    """Factual sentences with no citation at all."""

    uncited = []

    for sentence in SENTENCE_PATTERN.findall(answer):
        stripped = sentence.strip()

        if len(stripped) < 25:
            continue
        if INSUFFICIENT in stripped:
            continue
        if CITATION_PATTERN.search(stripped):
            continue

        uncited.append(stripped)

    return uncited


def validate(answer: str, context: BuiltContext) -> ValidatedAnswer:

    if INSUFFICIENT in answer or not answer.strip():
        return ValidatedAnswer(answer=REFUSAL, refused=True)

    valid = context.markers
    used = extract_markers(answer)

    invalid = sorted({m for m in used if m not in valid})

    citations = [
        Citation(
            marker=entry.marker,
            chunk_ids=entry.chunk_ids,
            kind=entry.kind,
            text=entry.text,
        )
        for entry in context.entries
        if entry.marker in set(used)
    ]

    return ValidatedAnswer(
        answer=answer.strip(),
        citations=citations,
        invalid_markers=invalid,
        uncited_sentences=find_uncited_sentences(answer),
    )


def describe_problem(result: ValidatedAnswer) -> str | None:
    """What is wrong with this answer's citations, if anything.

    Three failures, all the same underlying problem of a claim nothing
    backs: a marker pointing at context that was never retrieved, no
    markers at all, and factual sentences left uncited.
    """

    if result.invalid_markers:
        return (
            "it cited "
            + ", ".join(f"[{m}]" for m in result.invalid_markers)
            + ", which were never retrieved"
        )

    if not result.citations:
        return "it contained no citations at all"

    if result.uncited_sentences:
        return (
            f"{len(result.uncited_sentences)} factual sentence(s) had no "
            "citation"
        )

    return None


class Answerer:

    def __init__(self, client: GroqClient | None = None):
        self._client = client

    @property
    def client(self) -> GroqClient:
        if self._client is None:
            self._client = GroqClient()
        return self._client

    def answer(
        self,
        question: str,
        context: BuiltContext,
        allow_repair: bool = True,
    ) -> ValidatedAnswer:

        if not context.entries:
            return ValidatedAnswer(answer=REFUSAL, refused=True)

        raw = self.client.complete_text(
            ANSWER_PROMPT.format(context=context.block, question=question)
        )

        result = validate(raw, context)

        if result.refused or not allow_repair:
            return result

        problem = describe_problem(result)

        if problem is None:
            return result

        # One repair attempt. If the citations are still unusable,
        # refuse rather than shipping a claim nothing backs.
        repaired_raw = self.client.complete_text(
            REPAIR_PROMPT.format(
                problem=problem,
                valid=", ".join(str(m) for m in sorted(context.markers)),
                context=context.block,
                question=question,
                answer=result.answer,
            )
        )

        repaired = validate(repaired_raw, context)
        repaired.repaired = True

        if describe_problem(repaired) is not None:
            return ValidatedAnswer(
                answer=REFUSAL,
                refused=True,
                repaired=True,
                invalid_markers=repaired.invalid_markers,
                uncited_sentences=repaired.uncited_sentences,
            )

        return repaired
