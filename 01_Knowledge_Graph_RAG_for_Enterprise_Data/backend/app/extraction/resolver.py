"""Collapse name variants of the same entity into one node.

"Microsoft", "Microsoft Corporation" and "Microsoft Corp." must become a
single node or every traversal that starts at one of them misses the
edges attached to the others.

Three passes, cheapest first:
  1. normalise      lowercase, strip punctuation, collapse whitespace
  2. legal suffix   drop Inc / Corp / PBC / Ltd and friends
  3. embedding      cosine similarity above a tuned threshold

Clustering is always within a single entity type, so the Company
"Microsoft" can never merge with the Product "Microsoft Azure".
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from sqlalchemy import text

from app.config.settings import settings
from app.extraction.schemas import build_entity_id, normalize_name
from app.infrastructure.postgres import engine
from app.vector.embeddings import EmbeddingClient


LEGAL_SUFFIXES = {
    "inc",
    "incorporated",
    "corp",
    "corporation",
    "llc",
    "ltd",
    "limited",
    "plc",
    "pbc",
    "lp",
    "sa",
    "nv",
    "ag",
    "gmbh",
    "holdings",
}


@dataclass
class ResolvedEntity:
    entity_id: str
    name: str
    entity_type: str
    aliases: list[str] = field(default_factory=list)
    mentions: int = 0


def strip_legal_suffix(normalized: str) -> str:
    parts = normalized.split()

    while parts and parts[-1] in LEGAL_SUFFIXES:
        parts.pop()

    # A name that is nothing but suffixes keeps its original form.
    return " ".join(parts) or normalized


class _UnionFind:
    def __init__(self):
        self.parent: dict[str, str] = {}

    def find(self, item: str) -> str:
        self.parent.setdefault(item, item)
        root = item
        while self.parent[root] != root:
            root = self.parent[root]
        # path compression
        while self.parent[item] != root:
            self.parent[item], item = root, self.parent[item]
        return root

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class EntityResolver:

    def __init__(
        self,
        threshold: float | None = None,
        client: EmbeddingClient | None = None,
        use_embeddings: bool = True,
    ):
        self.threshold = (
            threshold if threshold is not None else settings.resolution_threshold
        )
        self.client = client
        self.use_embeddings = use_embeddings

    def resolve(
        self,
        mentions: list[tuple[str, str]],
    ) -> dict[tuple[str, str], ResolvedEntity]:
        """mentions is [(entity_type, raw_name), ...] and may repeat.

        Returns a lookup from (entity_type, raw_name) to the resolved
        entity, so callers can map a relation endpoint onto a node.
        """

        counts = Counter(mentions)

        by_type: dict[str, set[str]] = defaultdict(set)
        for entity_type, raw_name in counts:
            by_type[entity_type].add(raw_name)

        lookup: dict[tuple[str, str], ResolvedEntity] = {}

        for entity_type, names in by_type.items():
            for key, resolved in self._resolve_one_type(
                entity_type, sorted(names), counts
            ).items():
                lookup[key] = resolved

        return lookup

    def _resolve_one_type(
        self,
        entity_type: str,
        names: list[str],
        counts: Counter,
    ) -> dict[tuple[str, str], ResolvedEntity]:

        union = _UnionFind()

        # Pass 1 and 2: exact match on the suffix-stripped normal form.
        stripped_of: dict[str, str] = {}
        for name in names:
            stripped = strip_legal_suffix(normalize_name(name))
            stripped_of[name] = stripped
            union.union(f"form:{stripped}", f"name:{name}")

        # Pass 3: embedding similarity between distinct forms.
        if self.use_embeddings and len(names) > 1:
            self._merge_by_embedding(names, stripped_of, union)

        clusters: dict[str, list[str]] = defaultdict(list)
        for name in names:
            clusters[union.find(f"name:{name}")].append(name)

        lookup: dict[tuple[str, str], ResolvedEntity] = {}

        for members in clusters.values():

            # Canonical name is the most mentioned, then the longest,
            # so "Microsoft" beats "Microsoft Corporation" only if the
            # corpus actually favours it.
            canonical = max(
                members,
                key=lambda n: (counts[(entity_type, n)], len(n)),
            )

            total = sum(counts[(entity_type, n)] for n in members)

            resolved = ResolvedEntity(
                entity_id=build_entity_id(entity_type, canonical),
                name=canonical,
                entity_type=entity_type,
                aliases=sorted(n for n in members if n != canonical),
                mentions=total,
            )

            for name in members:
                lookup[(entity_type, name)] = resolved

        return lookup

    def _merge_by_embedding(
        self,
        names: list[str],
        stripped_of: dict[str, str],
        union: _UnionFind,
    ) -> None:

        forms = sorted({stripped_of[name] for name in names})

        if len(forms) < 2:
            return

        client = self.client or EmbeddingClient()
        vectors = dict(zip(forms, client.embed_texts(forms)))

        # No token-containment shortcut. It looked sensible and merged
        # "Dario Amodei" with "Daniela Amodei" and "Riccardo Amodei",
        # who are three different people, plus "Microsoft Azure" with
        # "Azure Sphere". Sharing a token is not being the same entity.
        #
        # Threshold measured on 23 labelled pairs from this corpus:
        #   0.82 -> precision 0.67, recall 0.80  (4 false merges)
        #   0.84 -> precision 1.00, recall 0.80  (0 false merges)
        #   0.90 -> precision 1.00, recall 0.60
        # The worst true-negative pair sits at 0.8355, so 0.86 clears it
        # with margin. A false merge invents facts, a missed merge only
        # splits a node, so precision is worth more than recall here.
        for i, left in enumerate(forms):
            for right in forms[i + 1 :]:

                if cosine(vectors[left], vectors[right]) >= self.threshold:
                    union.union(f"form:{left}", f"form:{right}")


SELECT_PAYLOADS = """
SELECT chunk_id, payload
FROM chunk_extractions
"""


def load_mentions() -> list[tuple[str, str, str]]:
    """Every validated entity mention as (chunk_id, type, name)."""

    from app.extraction.schemas import validate_extraction

    rows_out: list[tuple[str, str, str]] = []

    with engine.connect() as connection:
        rows = connection.execute(text(SELECT_PAYLOADS)).fetchall()

    for row in rows:
        result = validate_extraction(row.payload)
        for entity in result.entities:
            rows_out.append((row.chunk_id, str(entity.type), entity.name))

    return rows_out


if __name__ == "__main__":

    mentions = load_mentions()

    print(f"entity mentions   : {len(mentions)}")
    print(f"distinct raw names: {len({(t, n) for _, t, n in mentions})}")

    resolver = EntityResolver()

    lookup = resolver.resolve([(t, n) for _, t, n in mentions])

    unique = {r.entity_id: r for r in lookup.values()}

    print(f"resolved nodes    : {len(unique)}")
    print()

    merged = sorted(
        (r for r in unique.values() if r.aliases),
        key=lambda r: -r.mentions,
    )

    print(f"clusters with aliases: {len(merged)}")
    print()

    for resolved in merged[:25]:
        print(
            f"  {resolved.entity_type:<11} {resolved.name:<28} "
            f"x{resolved.mentions:<4} <- {', '.join(resolved.aliases)}"
        )
