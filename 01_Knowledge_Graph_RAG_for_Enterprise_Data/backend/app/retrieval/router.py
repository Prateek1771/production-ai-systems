"""Decide whether a question wants passages, paths, or both.

Heuristics run first because they cost nothing and Groq's free tier
gives us 8000 tokens per minute. The LLM classifier is the fallback for
questions the rules cannot call confidently, not the default.

Every decision is logged. The spec is explicit that you cannot
reconstruct routing data later.
"""

import re
import time
import uuid

from sqlalchemy import text as sql

from app.domain.retrieval import Route
from app.infrastructure.postgres import engine
from app.llm.groq import GroqClient
from app.retrieval.graph import link_entities


# Connection, comparison, and multi-hop language. These are the shapes
# similarity search cannot follow.
GRAPH_MARKERS = [
    r"\bconnect(ed|ion|ions)?\b",
    r"\brelated\b",
    r"\brelationship\b",
    r"\bbetween\b",
    r"\bboth\b",
    r"\bpartner(s|ship)?\b",
    r"\bcompetitor(s)?\b",
    r"\bcompete(s)?\b",
    r"\binvest(s|ed|or|ors|ment)?\b",
    r"\bacquire(d|s)?\b",
    r"\bacquisition\b",
    r"\bsuppl(y|ies|ier|iers)\b",
    r"\bwho else\b",
    r"\bhow many\b",
    r"\bcount\b",
    r"\blist all\b",
    r"\bwhich compan(y|ies)\b",
    r"\bboard\b",
    r"\bsupply chain\b",
    r"\bvia\b",
    r"\bthrough\b",
]


# Definitional and single-fact language, which vectors handle well.
VECTOR_MARKERS = [
    r"^what is\b",
    r"^what are\b",
    r"^define\b",
    r"\bdefinition\b",
    r"\bdescribe\b",
    r"\bexplain\b",
    r"\bknown for\b",
    r"\bmission\b",
    r"\bhistory\b",
    r"\bfocus(ed|es)? on\b",
]


CLASSIFY_PROMPT = """Classify the retrieval strategy for a question about
companies, executives, and products.

Answer "graph" when the question is about connections between entities,
multi-step chains, comparisons across entities, or counts over
relationships.

Answer "vector" when the question is a definition, a description, or a
single fact about one entity.

Answer "hybrid" when it needs both a described fact and a connection.

Examples:
Q: What is Anthropic focused on? -> vector
Q: How is Microsoft connected to OpenAI? -> graph
Q: Which cloud provider does OpenAI use? -> graph
Q: Who runs NVIDIA? -> vector
Q: Which companies has Microsoft invested in and who leads them? -> hybrid
Q: How many companies compete with NVIDIA? -> graph
Q: Describe Tesla's business and its main partners. -> hybrid

Return JSON: {{"route":"vector|graph|hybrid","confidence":0.0}}

Q: {question}
"""


LOG_DECISION = """
INSERT INTO routing_decisions
    (trace_id, question, route, confidence, fallback, hit_count, latency_ms)
VALUES
    (:trace_id, :question, :route, :confidence, :fallback, :hit_count, :latency_ms)
ON CONFLICT (trace_id) DO NOTHING
"""


class QueryRouter:

    def __init__(
        self,
        client: GroqClient | None = None,
        use_llm: bool = True,
        low_confidence: float = 0.6,
    ):
        self._client = client
        self.use_llm = use_llm
        self.low_confidence = low_confidence

    @property
    def client(self) -> GroqClient:
        if self._client is None:
            self._client = GroqClient()
        return self._client

    def route(self, question: str) -> tuple[Route, float, bool]:
        """Returns (route, confidence, used_llm)."""

        route, confidence = self._heuristic(question)

        if confidence >= self.low_confidence:
            return route, confidence, False

        if not self.use_llm:
            # Below the bar and no classifier available, so run both.
            return Route.HYBRID, confidence, False

        try:
            route, confidence = self._classify(question)
            return route, confidence, True
        except Exception:
            # A classifier outage must not take retrieval down with it.
            return Route.HYBRID, 0.5, False

    def _heuristic(self, question: str) -> tuple[Route, float]:

        lowered = question.lower().strip()

        graph_hits = sum(
            1 for pattern in GRAPH_MARKERS if re.search(pattern, lowered)
        )
        vector_hits = sum(
            1 for pattern in VECTOR_MARKERS if re.search(pattern, lowered)
        )

        entities = link_entities(question)

        # Two named entities is almost always a connection question.
        if len(entities) >= 2:
            return Route.GRAPH, 0.85 if graph_hits else 0.7

        if graph_hits and vector_hits:
            return Route.HYBRID, 0.7

        if graph_hits >= 2:
            return Route.GRAPH, 0.85

        if graph_hits == 1:
            return Route.GRAPH, 0.65 if entities else 0.5

        if vector_hits:
            return Route.VECTOR, 0.75

        # Nothing matched. Let the classifier decide.
        return Route.VECTOR, 0.4

    def _classify(self, question: str) -> tuple[Route, float]:

        payload = self.client.complete_json(
            CLASSIFY_PROMPT.format(question=question)
        )

        raw = str(payload.get("route", "hybrid")).strip().lower()

        route = Route.HYBRID
        if raw in {r.value for r in Route}:
            route = Route(raw)

        try:
            confidence = float(payload.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5

        return route, min(1.0, max(0.0, confidence))


def log_decision(
    trace_id: str,
    question: str,
    route: Route,
    confidence: float,
    fallback: bool,
    hit_count: int,
    latency_ms: float,
) -> None:
    with engine.begin() as connection:
        connection.execute(
            sql(LOG_DECISION),
            {
                "trace_id": trace_id,
                "question": question,
                "route": str(route),
                "confidence": confidence,
                "fallback": fallback,
                "hit_count": hit_count,
                "latency_ms": latency_ms,
            },
        )


def new_trace_id() -> str:
    return uuid.uuid4().hex


if __name__ == "__main__":

    router = QueryRouter(use_llm=False)

    questions = [
        "Who runs NVIDIA?",
        "What is Anthropic focused on?",
        "Which cloud provider does OpenAI use?",
        "How is Microsoft connected to OpenAI?",
        "How many companies compete with NVIDIA?",
        "Describe Tesla and list its partners.",
        "What is the capital of France?",
    ]

    for question in questions:
        started = time.perf_counter()
        route, confidence, used_llm = router.route(question)
        elapsed = (time.perf_counter() - started) * 1000
        print(
            f"  {str(route):<7} conf={confidence:.2f} "
            f"llm={'y' if used_llm else 'n'} {elapsed:6.1f}ms  {question}"
        )
