"""Benchmark hybrid retrieval against a vector-only baseline, by hop count.

The claim being tested is specific: parity on single-hop questions, and a
widening gap as hops increase. If that curve does not appear, the graph
half of this project is not earning its build cost and the honest thing
is to report that.

Two modes measured separately:
  vector   pgvector similarity only, no graph
  hybrid   router picks the path, graph and vector fused

Retrieval is scored by document recall rather than chunk recall. Gold
labels name documents, which stay valid when chunk boundaries change.
"""

import json
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path

from app.domain.retrieval import Route
from app.generation.citations import Answerer
from app.generation.context import build_context
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.router import QueryRouter
from app.vector.store import VectorStore


BENCHMARK_PATH = (
    Path(__file__).parents[3] / "data" / "benchmark" / "questions.json"
)


@dataclass
class Outcome:
    question_id: str
    category: str
    mode: str
    recall: float
    hit: bool
    answered: bool
    correct: bool
    refused: bool
    latency_ms: float
    route: str = ""


@dataclass
class Summary:
    mode: str
    by_category: dict[str, dict] = field(default_factory=dict)
    overall: dict = field(default_factory=dict)


def load_questions(path: Path | None = None) -> list[dict]:
    payload = json.loads((path or BENCHMARK_PATH).read_text(encoding="utf-8"))
    return payload["questions"]


def document_recall(retrieved: set[str], gold: list[str]) -> tuple[float, bool]:
    """Fraction of gold documents that appear, and whether any did."""

    if not gold:
        return 1.0, True

    found = {name for name in gold if name in retrieved}
    return len(found) / len(gold), bool(found)


def answer_is_correct(answer: str, question: dict) -> bool:
    """Substring match on required tokens. Crude but inspectable.

    A model-graded score would be less brittle and also unfalsifiable
    without a second labelled set, so this stays dumb on purpose.
    """

    if not question["answerable"]:
        return False

    needles = question.get("answer_contains") or []

    if not needles:
        # Nothing asserted about wording, so any non-refusal counts.
        return True

    lowered = answer.lower()
    return all(needle.lower() in lowered for needle in needles)


def run_vector_only(
    question: dict,
    store: VectorStore,
    answerer: Answerer | None,
    top_k: int,
) -> Outcome:

    started = time.perf_counter()

    hits = store.search(question["question"], limit=top_k)
    documents = {hit.filename for hit in hits}

    recall, hit = document_recall(documents, question["gold_documents"])

    from app.domain.retrieval import RetrievalResult

    result = RetrievalResult(route=Route.VECTOR, passages=hits)

    # Retrieval-only mode. Embeddings are local and entity linking is
    # string matching, so recall costs no API tokens. Only generation
    # does, which matters when a daily quota is spent.
    if answerer is None:
        return Outcome(
            question_id=question["id"],
            category=question["category"],
            mode="vector",
            recall=recall,
            hit=hit,
            answered=False,
            correct=False,
            refused=False,
            latency_ms=(time.perf_counter() - started) * 1000,
            route="vector",
        )

    validated = answerer.answer(question["question"], build_context(result))

    return Outcome(
        question_id=question["id"],
        category=question["category"],
        mode="vector",
        recall=recall,
        hit=hit,
        answered=not validated.refused,
        correct=(
            validated.refused
            if not question["answerable"]
            else answer_is_correct(validated.answer, question)
        ),
        refused=validated.refused,
        latency_ms=(time.perf_counter() - started) * 1000,
        route="vector",
    )


def run_hybrid(
    question: dict,
    retriever: HybridRetriever,
    answerer: Answerer | None,
    top_k: int,
) -> Outcome:

    started = time.perf_counter()

    result = retriever.retrieve(question["question"], limit=top_k, log=False)

    documents = {hit.filename for hit in result.passages}
    # Graph facts cite chunk ids, so map them back to filenames.
    documents |= _documents_for_chunks(
        {c for fact in result.facts for c in fact.chunk_ids}
    )

    recall, hit = document_recall(documents, question["gold_documents"])

    if answerer is None:
        return Outcome(
            question_id=question["id"],
            category=question["category"],
            mode="hybrid",
            recall=recall,
            hit=hit,
            answered=False,
            correct=False,
            refused=False,
            latency_ms=(time.perf_counter() - started) * 1000,
            route=str(result.route),
        )

    validated = answerer.answer(question["question"], build_context(result))

    return Outcome(
        question_id=question["id"],
        category=question["category"],
        mode="hybrid",
        recall=recall,
        hit=hit,
        answered=not validated.refused,
        correct=(
            validated.refused
            if not question["answerable"]
            else answer_is_correct(validated.answer, question)
        ),
        refused=validated.refused,
        latency_ms=(time.perf_counter() - started) * 1000,
        route=str(result.route),
    )


_CHUNK_CACHE: dict[str, str] = {}


def _documents_for_chunks(chunk_ids: set[str]) -> set[str]:
    from sqlalchemy import text

    from app.infrastructure.postgres import engine

    missing = [c for c in chunk_ids if c not in _CHUNK_CACHE]

    if missing:
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT chunk_id, metadata->>'filename' AS filename "
                    "FROM chunks WHERE chunk_id = ANY(:ids)"
                ),
                {"ids": missing},
            ).fetchall()
        for row in rows:
            _CHUNK_CACHE[row.chunk_id] = row.filename

    return {_CHUNK_CACHE[c] for c in chunk_ids if c in _CHUNK_CACHE}


def summarise(outcomes: list[Outcome], mode: str) -> Summary:
    summary = Summary(mode=mode)

    relevant = [o for o in outcomes if o.mode == mode]

    for category in sorted({o.category for o in relevant}):
        group = [o for o in relevant if o.category == category]
        summary.by_category[category] = {
            "n": len(group),
            "recall": round(statistics.mean(o.recall for o in group), 3),
            "hit_rate": round(statistics.mean(1.0 if o.hit else 0.0 for o in group), 3),
            "accuracy": round(
                statistics.mean(1.0 if o.correct else 0.0 for o in group), 3
            ),
            "p95_ms": round(
                sorted(o.latency_ms for o in group)[
                    min(len(group) - 1, int(0.95 * len(group)))
                ],
                1,
            ),
        }

    if relevant:
        latencies = sorted(o.latency_ms for o in relevant)
        summary.overall = {
            "n": len(relevant),
            "recall": round(statistics.mean(o.recall for o in relevant), 3),
            "accuracy": round(
                statistics.mean(1.0 if o.correct else 0.0 for o in relevant), 3
            ),
            "median_ms": round(statistics.median(latencies), 1),
            "p95_ms": round(
                latencies[min(len(latencies) - 1, int(0.95 * len(latencies)))], 1
            ),
        }

    return summary


def render_table(vector: Summary, hybrid: Summary) -> str:
    order = [
        "single_hop",
        "two_hop",
        "three_hop",
        "aggregation",
        "out_of_scope",
    ]

    lines = [
        "| category | n | vector acc | hybrid acc | delta | vector recall | hybrid recall |",
        "|---|---|---|---|---|---|---|",
    ]

    for category in order:
        v = vector.by_category.get(category)
        h = hybrid.by_category.get(category)
        if not v or not h:
            continue
        delta = h["accuracy"] - v["accuracy"]
        lines.append(
            f"| {category} | {v['n']} | {v['accuracy']:.2f} | "
            f"{h['accuracy']:.2f} | {delta:+.2f} | "
            f"{v['recall']:.2f} | {h['recall']:.2f} |"
        )

    if vector.overall and hybrid.overall:
        delta = hybrid.overall["accuracy"] - vector.overall["accuracy"]
        lines.append(
            f"| **all** | {vector.overall['n']} | "
            f"{vector.overall['accuracy']:.2f} | "
            f"{hybrid.overall['accuracy']:.2f} | {delta:+.2f} | "
            f"{vector.overall['recall']:.2f} | "
            f"{hybrid.overall['recall']:.2f} |"
        )

    return "\n".join(lines)


def render_recall_table(vector: Summary, hybrid: Summary) -> str:
    """Retrieval quality only. No generation, so no accuracy column."""

    order = ["single_hop", "two_hop", "three_hop", "aggregation", "out_of_scope"]

    lines = [
        "| category | n | vector recall | hybrid recall | delta | vector hit | hybrid hit |",
        "|---|---|---|---|---|---|---|",
    ]

    for category in order:
        v = vector.by_category.get(category)
        h = hybrid.by_category.get(category)
        if not v or not h:
            continue
        lines.append(
            f"| {category} | {v['n']} | {v['recall']:.2f} | {h['recall']:.2f} | "
            f"{h['recall'] - v['recall']:+.2f} | "
            f"{v['hit_rate']:.2f} | {h['hit_rate']:.2f} |"
        )

    if vector.overall and hybrid.overall:
        lines.append(
            f"| **all** | {vector.overall['n']} | {vector.overall['recall']:.2f} | "
            f"{hybrid.overall['recall']:.2f} | "
            f"{hybrid.overall['recall'] - vector.overall['recall']:+.2f} | | |"
        )

    return "\n".join(lines)


def run(
    limit: int | None = None,
    top_k: int = 5,
    categories: list[str] | None = None,
    retrieval_only: bool = False,
) -> tuple[list[Outcome], Summary, Summary]:

    questions = load_questions()

    if categories:
        questions = [q for q in questions if q["category"] in categories]

    if limit:
        questions = questions[:limit]

    store = VectorStore()
    retriever = HybridRetriever(router=QueryRouter(use_llm=False))
    answerer = None if retrieval_only else Answerer()

    outcomes: list[Outcome] = []

    for index, question in enumerate(questions, start=1):
        print(f"  {index:>3}/{len(questions)} {question['id']:<7} {question['question'][:52]}")

        for runner in (
            lambda: run_vector_only(question, store, answerer, top_k),
            lambda: run_hybrid(question, retriever, answerer, top_k),
        ):
            try:
                outcomes.append(runner())
            except Exception as error:
                print(f"        FAILED {type(error).__name__}")

    return outcomes, summarise(outcomes, "vector"), summarise(outcomes, "hybrid")


if __name__ == "__main__":

    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--categories", nargs="*", default=None)
    parser.add_argument("--out", default=None)
    parser.add_argument(
        "--retrieval-only",
        action="store_true",
        help="recall and latency without generation, so no API tokens",
    )
    args = parser.parse_args()

    outcomes, vector, hybrid = run(
        limit=args.limit,
        top_k=args.top_k,
        categories=args.categories,
        retrieval_only=args.retrieval_only,
    )

    print()
    if args.retrieval_only:
        print(render_recall_table(vector, hybrid))
    else:
        print(render_table(vector, hybrid))
    print()
    print(f"vector  median {vector.overall.get('median_ms')} ms, "
          f"p95 {vector.overall.get('p95_ms')} ms")
    print(f"hybrid  median {hybrid.overall.get('median_ms')} ms, "
          f"p95 {hybrid.overall.get('p95_ms')} ms")

    if args.out:
        Path(args.out).write_text(
            json.dumps(
                {
                    "vector": {"by_category": vector.by_category, "overall": vector.overall},
                    "hybrid": {"by_category": hybrid.by_category, "overall": hybrid.overall},
                    "outcomes": [o.__dict__ for o in outcomes],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\nwrote {args.out}")
