"""Assemble retrieved material into a numbered context block.

Graph facts and vector passages are labelled separately. The model
needs to know which claims came from a traversal and which came from a
passage, and so does anyone reading the answer.

Every entry gets a stable [n] marker that maps back to a chunk id, so a
citation can be checked rather than trusted.
"""

from dataclasses import dataclass, field

from app.domain.retrieval import RetrievalResult


@dataclass
class ContextEntry:
    marker: int
    kind: str
    chunk_ids: list[str]
    text: str
    filename: str = ""


@dataclass
class BuiltContext:
    entries: list[ContextEntry] = field(default_factory=list)
    block: str = ""

    @property
    def markers(self) -> set[int]:
        return {entry.marker for entry in self.entries}

    def chunk_ids_for(self, marker: int) -> list[str]:
        for entry in self.entries:
            if entry.marker == marker:
                return entry.chunk_ids
        return []

    @property
    def valid_chunk_ids(self) -> set[str]:
        ids: set[str] = set()
        for entry in self.entries:
            ids.update(entry.chunk_ids)
        return ids


def build_context(
    result: RetrievalResult,
    max_facts: int = 8,
    max_passages: int = 5,
    passage_chars: int = 700,
) -> BuiltContext:

    entries: list[ContextEntry] = []
    marker = 0

    seen_statements: set[str] = set()

    for fact in result.facts[:max_facts]:

        key = fact.statement.lower().strip()
        if key in seen_statements or not fact.chunk_ids:
            continue
        seen_statements.add(key)

        marker += 1
        entries.append(
            ContextEntry(
                marker=marker,
                kind="graph",
                chunk_ids=list(dict.fromkeys(fact.chunk_ids)),
                text=fact.statement,
            )
        )

    seen_chunks: set[str] = set()

    for hit in result.passages[:max_passages]:

        if hit.chunk_id in seen_chunks:
            continue
        seen_chunks.add(hit.chunk_id)

        marker += 1
        entries.append(
            ContextEntry(
                marker=marker,
                kind="passage",
                chunk_ids=[hit.chunk_id],
                text=" ".join(hit.text.split())[:passage_chars],
                filename=hit.filename,
            )
        )

    return BuiltContext(entries=entries, block=render(entries))


def render(entries: list[ContextEntry]) -> str:

    graph = [e for e in entries if e.kind == "graph"]
    passages = [e for e in entries if e.kind == "passage"]

    lines: list[str] = []

    if graph:
        lines.append("FACTS FROM THE KNOWLEDGE GRAPH")
        lines.append("")
        for entry in graph:
            lines.append(f"[{entry.marker}] {entry.text}")
        lines.append("")

    if passages:
        lines.append("PASSAGES FROM THE DOCUMENTS")
        lines.append("")
        for entry in passages:
            source = f" ({entry.filename})" if entry.filename else ""
            lines.append(f"[{entry.marker}]{source} {entry.text}")
            lines.append("")

    return "\n".join(lines).strip()
