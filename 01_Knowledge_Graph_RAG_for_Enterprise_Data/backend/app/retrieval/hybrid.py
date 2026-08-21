"""Run the chosen retrieval paths and merge them into one result.

Vector search returns passages with cosine similarity. Graph traversal
returns paths with a hand-assigned score. Those numbers are not
comparable, so fusion uses Reciprocal Rank Fusion, which only looks at
rank position and sidesteps the problem entirely.
"""

import time

from app.domain.retrieval import GraphFact, RetrievalResult, Route, SearchHit
from app.retrieval.graph import GraphRetriever, link_entities
from app.retrieval.router import (
    QueryRouter,
    log_decision,
    new_trace_id,
)
from app.vector.store import VectorStore


RRF_K = 60


def reciprocal_rank_fusion(
    ranked_lists: list[list[str]],
    k: int = RRF_K,
) -> dict[str, float]:
    """score(d) = sum over lists of 1 / (k + rank(d)).

    k dampens the top-rank advantage. 60 is the value from the original
    paper and is not tuned here.
    """

    scores: dict[str, float] = {}

    for ranked in ranked_lists:
        for rank, key in enumerate(ranked, start=1):
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)

    return scores


class HybridRetriever:

    def __init__(
        self,
        store: VectorStore | None = None,
        graph: GraphRetriever | None = None,
        router: QueryRouter | None = None,
    ):
        self.store = store or VectorStore()
        self.graph = graph or GraphRetriever()
        self.router = router or QueryRouter()

    def retrieve(
        self,
        question: str,
        limit: int = 5,
        route: Route | None = None,
        trace_id: str | None = None,
        log: bool = True,
    ) -> RetrievalResult:

        trace_id = trace_id or new_trace_id()
        started = time.perf_counter()

        used_llm = False
        confidence = 1.0

        if route is None:
            route, confidence, used_llm = self.router.route(question)

        facts: list[GraphFact] = []

        # Passages are always fetched. Measured: routing to graph-only
        # and returning no passages dropped document recall from 0.85 to
        # 0.66 across 60 questions, and by 0.34 on two-hop questions,
        # because 23 of them took that route. A traversal is an addition
        # to the passage set, never a replacement for it. The cost of the
        # safety net is one embedding and one indexed query, about 270ms.
        passages: list[SearchHit] = self.store.search(question, limit=limit)

        if route in (Route.GRAPH, Route.HYBRID):
            facts = self.graph.retrieve(question, limit=limit * 3)

        # The entity linker found nothing, so a graph route had nothing
        # to traverse and this is really a vector answer.
        fallback = route is Route.GRAPH and not facts

        if route in (Route.GRAPH, Route.HYBRID):
            passages, facts = self._fuse(passages, facts, limit)

        linked = (
            [entity.name for entity in link_entities(question)]
            if route is not Route.VECTOR
            else []
        )

        result = RetrievalResult(
            route=route,
            passages=passages,
            facts=facts[:limit] if facts else [],
            question_entities=linked,
            confidence=confidence,
            fallback=fallback or used_llm,
        )

        if log:
            log_decision(
                trace_id=trace_id,
                question=question,
                route=route,
                confidence=confidence,
                fallback=fallback,
                hit_count=len(result.chunk_ids),
                latency_ms=(time.perf_counter() - started) * 1000,
            )

        return result

    def _fuse(
        self,
        passages: list[SearchHit],
        facts: list[GraphFact],
        limit: int,
    ) -> tuple[list[SearchHit], list[GraphFact]]:
        """Rank both sources by the chunks they point at."""

        vector_ranking = [hit.chunk_id for hit in passages]

        graph_ranking: list[str] = []
        for fact in facts:
            for chunk_id in fact.chunk_ids:
                if chunk_id not in graph_ranking:
                    graph_ranking.append(chunk_id)

        scores = reciprocal_rank_fusion([vector_ranking, graph_ranking])

        passages = sorted(
            passages,
            key=lambda hit: -scores.get(hit.chunk_id, 0.0),
        )[:limit]

        # A fact whose chunks nothing else surfaced still matters, so
        # rank facts by their best chunk rather than dropping them.
        facts = sorted(
            facts,
            key=lambda fact: (
                -max((scores.get(c, 0.0) for c in fact.chunk_ids), default=0.0),
                fact.hops,
            ),
        )

        return passages, facts


if __name__ == "__main__":

    retriever = HybridRetriever(router=QueryRouter(use_llm=False))

    for question in [
        "Who runs NVIDIA?",
        "Which cloud provider does OpenAI use?",
        "How is Microsoft connected to OpenAI?",
    ]:
        print("=" * 78)
        print("Q:", question)
        result = retriever.retrieve(question, log=False)
        print(f"route={result.route} confidence={result.confidence:.2f}")
        print(f"entities={result.question_entities}")
        print()

        for fact in result.facts[:4]:
            print(f"  FACT [{fact.hops}h] {fact.statement}")

        for hit in result.passages[:3]:
            preview = " ".join(hit.text.split())[:56]
            print(f"  PASS {hit.similarity:.3f} {hit.filename:<20} {preview}")

        print(f"  citable chunks: {len(result.chunk_ids)}")
        print()
