"""Graph retrieval: question text in, verbalised facts with citations out.

Entity linking is done by matching the question against known entity
names and aliases rather than by asking a model. That is free, and at
8000 tokens per minute free tokens are the scarce resource. The corpus
entities are proper nouns, which is exactly the case string matching
handles well.
"""

import re
from dataclasses import dataclass
from functools import lru_cache

from app.domain.retrieval import GraphFact
from app.extraction.schemas import RelationType, normalize_name
from app.graph import queries
from app.graph.client import run_read


# How each relation reads as English. Raw triples produce awkward
# prompt text, and the spec calls this out specifically.
RELATION_PHRASES: dict[str, str] = {
    "CEO_OF": "is the CEO of",
    "FOUNDED": "founded",
    "WORKS_AT": "works at",
    "PREVIOUSLY_WORKED_AT": "previously worked at",
    "BOARD_MEMBER_OF": "sits on the board of",
    "INVESTED_IN": "has invested in",
    "ACQUIRED": "acquired",
    "PARTNERS_WITH": "partners with",
    "COMPETES_WITH": "competes with",
    "SUPPLIES": "supplies",
    "DEVELOPS": "develops",
    "USES": "uses",
    "OPERATES_IN": "operates in",
    "BASED_ON": "is based on",
    "HEADQUARTERED_IN": "is headquartered in",
}


STOPWORDS = {
    "what", "which", "who", "whom", "whose", "where", "when", "why", "how",
    "the", "a", "an", "is", "are", "was", "were", "do", "does", "did", "of",
    "in", "on", "at", "to", "for", "and", "or", "but", "with", "by", "from",
    "about", "into", "that", "this", "these", "those", "it", "its", "as",
    "company", "companies", "use", "uses", "used", "make", "makes", "run",
    "runs", "lead", "leads", "led", "work", "works", "many", "much", "list",
}


def phrase(relation: str) -> str:
    return RELATION_PHRASES.get(relation, relation.replace("_", " ").lower())


@dataclass
class LinkedEntity:
    entity_id: str
    name: str
    entity_type: str
    matched_on: str


@lru_cache(maxsize=1)
def _entity_index() -> tuple[tuple[str, str, str, str], ...]:
    """(normalized surface form, entity_id, name, entity_type), longest first."""

    rows = run_read(
        """
        MATCH (e:Entity)
        RETURN e.entity_id AS entity_id, e.name AS name,
               e.entity_type AS entity_type, e.aliases AS aliases
        """
    )

    index: list[tuple[str, str, str, str]] = []

    for row in rows:
        forms = [row["name"], *(row["aliases"] or [])]
        for form in forms:
            normalized = normalize_name(form)
            if len(normalized) < 3 or normalized in STOPWORDS:
                continue
            index.append(
                (normalized, row["entity_id"], row["name"], row["entity_type"])
            )

    # Longest first so "google cloud platform" wins over "google".
    index.sort(key=lambda item: -len(item[0]))
    return tuple(index)


def reset_entity_index() -> None:
    _entity_index.cache_clear()


def link_entities(question: str, limit: int = 4) -> list[LinkedEntity]:
    """Find known entities named in the question."""

    normalized_question = normalize_name(question)
    padded = f" {normalized_question} "

    found: list[LinkedEntity] = []
    seen: set[str] = set()
    consumed: list[str] = []

    for form, entity_id, name, entity_type in _entity_index():

        if entity_id in seen:
            continue

        if re.search(rf"(?<!\w){re.escape(form)}(?!\w)", padded) is None:
            continue

        # Skip a shorter form already covered by a longer match.
        if any(form in longer and form != longer for longer in consumed):
            continue

        found.append(
            LinkedEntity(
                entity_id=entity_id,
                name=name,
                entity_type=entity_type,
                matched_on=form,
            )
        )
        seen.add(entity_id)
        consumed.append(form)

        if len(found) >= limit:
            break

    return found


class GraphRetriever:

    def __init__(self, max_hops: int = 2, limit: int = 25):
        self.max_hops = max_hops
        self.limit = limit

    def retrieve(self, question: str, limit: int | None = None) -> list[GraphFact]:

        limit = limit or self.limit
        linked = link_entities(question)

        if not linked:
            return []

        facts: list[GraphFact] = []

        for entity in linked:
            facts.extend(self._one_hop(entity, limit * 4))

        # A question naming two entities is asking what connects them.
        if len(linked) >= 2:
            for i, left in enumerate(linked):
                for right in linked[i + 1 :]:
                    facts.extend(self._between(left, right, limit))

        if self.max_hops >= 2 and len(linked) == 1:
            facts.extend(self._two_hop(linked[0], limit))

        facts = self._rank(facts, linked)

        return self._dedupe(facts)[:limit]

    @staticmethod
    def _rank(
        facts: list[GraphFact],
        linked: list[LinkedEntity],
    ) -> list[GraphFact]:
        """Score by how much of the question a fact actually covers.

        Extraction confidence is the wrong signal: it says the model was
        sure the triple appears in the text, not that the triple answers
        this question, and it is ~1.0 for almost everything. Ranking on
        it buried "Microsoft has invested in OpenAI" under five
        "Microsoft develops Entra ID" facts.
        """

        wanted = {normalize_name(entity.name) for entity in linked}

        for fact in facts:
            touched = {normalize_name(name) for name in fact.entities}
            covered = len(wanted & touched)

            # Covering both named entities is what a connection question
            # is asking for, so it dominates. Confidence only breaks ties.
            fact.score = covered * 10.0 + fact.score - 0.1 * fact.hops

        return facts

    def _one_hop(self, entity: LinkedEntity, limit: int) -> list[GraphFact]:
        rows = run_read(queries.NEIGHBOURS, entity_id=entity.entity_id)

        facts = []
        for row in rows[:limit]:
            facts.append(
                GraphFact(
                    statement=(
                        f"{row['source']} {phrase(row['relation'])} "
                        f"{row['target']}."
                    ),
                    chunk_ids=list(row.get("chunk_ids") or []),
                    hops=1,
                    relation_path=[row["relation"]],
                    entities=[row["source"], row["target"]],
                    score=float(row.get("confidence") or 1.0),
                )
            )
        return facts

    def _two_hop(self, entity: LinkedEntity, limit: int) -> list[GraphFact]:
        rows = run_read(
            queries.TWO_HOP, entity_id=entity.entity_id, limit=limit
        )

        facts = []
        for row in rows:
            facts.append(
                GraphFact(
                    statement=(
                        f"{row['start']} {phrase(row['relation_1'])} "
                        f"{row['middle']}, which {phrase(row['relation_2'])} "
                        f"{row['end']}."
                    ),
                    chunk_ids=list(row.get("chunk_ids") or []),
                    hops=2,
                    relation_path=[row["relation_1"], row["relation_2"]],
                    entities=[row["start"], row["middle"], row["end"]],
                    score=0.7,
                )
            )
        return facts

    def _between(
        self,
        left: LinkedEntity,
        right: LinkedEntity,
        limit: int,
    ) -> list[GraphFact]:
        rows = run_read(
            queries.SHARED_NEIGHBOUR,
            source_id=left.entity_id,
            target_id=right.entity_id,
            limit=limit,
        )

        facts = []
        for row in rows:
            facts.append(
                GraphFact(
                    statement=(
                        f"{row['start']} {phrase(row['relation_1'])} "
                        f"{row['middle']}, which {phrase(row['relation_2'])} "
                        f"{row['end']}."
                    ),
                    chunk_ids=list(row.get("chunk_ids") or []),
                    hops=2,
                    relation_path=[row["relation_1"], row["relation_2"]],
                    entities=[row["start"], row["middle"], row["end"]],
                    score=0.95,
                )
            )
        return facts

    @staticmethod
    def _dedupe(facts: list[GraphFact]) -> list[GraphFact]:
        best: dict[str, GraphFact] = {}

        for fact in facts:
            key = fact.statement.lower()
            if key not in best or fact.score > best[key].score:
                best[key] = fact

        return sorted(best.values(), key=lambda f: (-f.score, f.hops))


def neighbourhood(entity_ids: list[str]) -> dict:
    """Nodes and edges for the frontend graph view."""

    rows = run_read(queries.NEIGHBOURHOOD_GRAPH, entity_ids=entity_ids)

    if not rows:
        return {"nodes": [], "edges": []}

    return {
        "nodes": rows[0].get("nodes") or [],
        "edges": rows[0].get("edges") or [],
    }


def relations_of_type(relation: str, entity_id: str | None = None, limit: int = 25):
    """Guarded interpolation: the type must be a member of our enum."""

    if relation not in set(RelationType):
        raise ValueError(f"unknown relation type: {relation}")

    return run_read(
        queries.RELATION_OF_TYPE_TEMPLATE.format(relation_type=relation),
        entity_id=entity_id,
        limit=limit,
    )


if __name__ == "__main__":

    for question in [
        "Who runs NVIDIA?",
        "Which cloud provider does OpenAI use?",
        "How is Microsoft connected to OpenAI?",
        "What does Anthropic build?",
    ]:
        print("=" * 78)
        print("Q:", question)
        linked = link_entities(question)
        print("linked:", [f"{e.name} ({e.entity_type})" for e in linked])
        print()

        for fact in GraphRetriever().retrieve(question, limit=6):
            print(
                f"  [{fact.hops}h {fact.score:.2f}] {fact.statement} "
                f"({len(fact.chunk_ids)} chunks)"
            )
        print()
