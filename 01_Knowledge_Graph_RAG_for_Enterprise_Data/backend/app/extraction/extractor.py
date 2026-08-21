import json
from collections import Counter

from sqlalchemy import text

from app.extraction.schemas import (
    ENTITY_TYPE_HINTS,
    RELATION_SIGNATURES,
    Extraction,
    validate_extraction,
)
from app.infrastructure.postgres import engine
from app.llm.base import LLMClient, LLMGateway


def _entity_type_block() -> str:
    return "\n".join(
        f"- {entity_type.value}: {hint}"
        for entity_type, hint in ENTITY_TYPE_HINTS.items()
    )


def _relation_block() -> str:
    return "\n".join(
        f"- {relation.value}: {source.value} -> {target.value}"
        for relation, (source, target) in RELATION_SIGNATURES.items()
    )


# Built from the enums so the prompt and the validator can never
# disagree. Add a relation type and the prompt gains it automatically.
PROMPT = """Extract entities and relationships from the text.

Entity types, use ONLY these:
{entity_types}

Relation types, use ONLY these, and respect the direction shown:
{relations}

Rules:
- Every relation source and target must appear in your entities list,
  spelled identically.
- Never relate an entity to itself.
- Extract only what the text states. Do not add outside knowledge.
- Give each item a confidence between 0 and 1.
- Discard anything that does not fit. Do not invent types.

Return JSON in exactly this shape:
{{"entities":[{{"name":"","type":"","confidence":0.0}}],
"relations":[{{"source":"","type":"","target":"","confidence":0.0}}]}}

Text:
{text}
"""


SELECT_PENDING = """
SELECT c.chunk_id, c.text AS chunk_text
FROM chunks c
LEFT JOIN chunk_extractions e USING (chunk_id)
WHERE e.chunk_id IS NULL
ORDER BY c.document_id, c.chunk_index
LIMIT :limit
"""


INSERT_EXTRACTION = """
INSERT INTO chunk_extractions (chunk_id, payload, model)
VALUES (:chunk_id, CAST(:payload AS jsonb), :model)
ON CONFLICT (chunk_id) DO NOTHING
"""


SELECT_ALL_PAYLOADS = """
SELECT chunk_id, payload
FROM chunk_extractions
"""


def build_prompt(chunk_text: str) -> str:
    return PROMPT.format(
        entity_types=_entity_type_block(),
        relations=_relation_block(),
        text=chunk_text,
    )


def extract_pending(
    batch_size: int = 10,
    client: "LLMClient | None" = None,
) -> tuple[int, int]:
    """Extract every chunk with no stored payload. Returns (done, failed).

    Takes any client satisfying the LLMClient protocol. Groq's 200k
    tokens-per-day cap is easy to hit, and being able to hand this an
    OpenRouter client instead is the reason the gateway exists.
    """

    client = client or LLMGateway()

    done = 0
    failed = 0

    while True:

        with engine.connect() as connection:
            rows = connection.execute(
                text(SELECT_PENDING),
                {"limit": batch_size},
            ).fetchall()

        if not rows:
            return done, failed

        for row in rows:

            try:
                payload = client.complete_json(build_prompt(row.chunk_text))
            except Exception as error:
                failed += 1
                print(f"  FAILED {row.chunk_id[:12]} {type(error).__name__}")
                continue

            # Commit per chunk. A 20 minute run inside one transaction
            # would lose everything to a failure at the end.
            with engine.begin() as connection:
                connection.execute(
                    text(INSERT_EXTRACTION),
                    {
                        "chunk_id": row.chunk_id,
                        "payload": json.dumps(payload),
                        "model": client.model,
                    },
                )

            done += 1
            print(f"  {done:>4} {row.chunk_id[:12]}")


def validate_all() -> tuple[int, int, list[str]]:
    """Re-validate every stored payload. Free, no API calls."""

    entities = 0
    relations = 0
    rejected: list[str] = []

    with engine.connect() as connection:
        rows = connection.execute(text(SELECT_ALL_PAYLOADS)).fetchall()

    for row in rows:
        result: Extraction = validate_extraction(row.payload)
        entities += len(result.entities)
        relations += len(result.relations)
        rejected.extend(result.rejected)

    return entities, relations, rejected


def reject_histogram(rejected: list[str]) -> Counter:
    return Counter(
        reason.split(": ", 1)[-1][:52] for reason in rejected
    )


if __name__ == "__main__":

    import os
    import time

    provider = os.environ.get("EXTRACT_PROVIDER", "gateway").lower()

    if provider == "openrouter":
        from app.llm.openrouter import OpenRouterClient

        client: LLMClient = OpenRouterClient()
    elif provider == "groq":
        from app.llm.groq import GroqClient

        client = GroqClient(verbose_pacing=True)
    elif provider == "ollama":
        from app.llm.ollama import OllamaClient

        client = OllamaClient()
    else:
        # include_local so a bulk run finishes even with both hosted
        # providers exhausted. Slow beats not at all.
        client = LLMGateway(include_local=True)

    print(f"provider  : {type(client).__name__} ({getattr(client, 'model', '?')})")

    started = time.perf_counter()
    done, failed = extract_pending(client=client)
    elapsed = time.perf_counter() - started

    print()
    print(f"extracted : {done}")
    print(f"failed    : {failed}")
    print(f"tokens    : {getattr(client, 'total_tokens', 0)}")
    print(f"wall clock: {elapsed / 60:.1f} min")

    entities, relations, rejected = validate_all()

    print()
    print(f"entities kept  : {entities}")
    print(f"relations kept : {relations}")
    print(f"rejected       : {len(rejected)}")
    print()

    for reason, count in reject_histogram(rejected).most_common(12):
        print(f"  {count:>4}  {reason}")
