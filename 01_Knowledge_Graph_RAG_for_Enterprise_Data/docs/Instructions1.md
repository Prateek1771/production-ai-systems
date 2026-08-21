# Lesson 1. A chunker that survives real documents

## Where we are

```text
data/raw/*.txt          ✅ 23 documents
TextDocumentLoader      ✅ file → Document
ParagraphChunker        ⚠️  works, but has a hole
IngestionPipeline       ✅ directory → [(Document, [Chunk])]
Postgres + Neo4j        ✅ both containers healthy
nomic-embed-text        ✅ pulled
```

Everything after this line is unbuilt. Before we put a single row in
Postgres, the chunker has to be correct, because **chunk boundaries are
baked into the embeddings, the chunk IDs, and every citation we will ever
show a user.** Re-chunking later means re-embedding everything and
invalidating every stored ID. This is the cheapest moment to get it right.

---

## The hole in the current chunker

Our loop reads:

```python
if current_paragraphs and current_length + paragraph_length > self.max_characters:
```

Read that condition carefully. It decides *whether to start a new chunk
before adding this paragraph*. It never asks whether the paragraph **fits at
all**.

So given `max_characters=800` and a 2,400-character paragraph:

```text
current_paragraphs = []        ← empty, so the guard is False
                               ← we skip the flush entirely
current_paragraphs.append(paragraph)
                               ← a 2,400-char chunk is now inevitable
```

The `and current_paragraphs` clause, which exists to avoid emitting an empty
chunk, also silently lets any oversized paragraph straight through. We produce a chunk
three times our limit, and nothing complains.

That matters concretely:

```text
oversized chunk
   → one embedding vector for 2,400 characters of mixed topics
   → the vector is an average of everything in it
   → it ranks mediocre for every query and wins none
   → and when it does win, the citation points at 3 paragraphs
     instead of the 1 that actually answered the question
```

An embedding is a fixed-size summary. Feed it more text and it says less
about all of it. An oversized chunk does not merely risk a token limit. It
**dilute**.

---

## The policy we're implementing

```text
1. Prefer paragraph boundaries        ← paragraphs are real semantic units
2. Respect the maximum size           ← no exceptions, including rule 1
3. Split oversized paragraphs         ← the new capability
4. Carry a small overlap              ← so a fact spanning a boundary survives
5. Deterministic chunk IDs            ← re-ingest must be a no-op
6. Preserve document metadata         ← every chunk knows its source
7. Preserve chunk ordering            ← chunk_index is stable
```

Rules 1 and 2 conflict, and rule 2 wins. That is the whole design decision.

The flow becomes:

```text
paragraph arrives
      │
      ├── bigger than max on its own?
      │        │
      │        ├── flush whatever we were accumulating
      │        └── hard-split it into max-sized parts, each its own chunk
      │
      └── fits?
               │
               ├── would it overflow the current chunk?
               │        └── flush, then seed the next chunk with the overlap
               │
               └── append it, keep accumulating
```

---

## We are also dropping the chunk size

Change `max_characters` from `1800` to `800`, and `overlap_characters` from
`200` to `100`.

Not because 800 is a magic number. Because our sample documents are small.
At 1,800 we were getting ~3 chunks per document, and 3 chunks per document
cannot exercise top-k retrieval, ranking, or multi-hop citations. We need
enough chunks for retrieval to have a real choice to make.

```text
before                        after
──────                        ─────
Document                      Document
   ├── Chunk 0  ~1500            ├── Chunk 0  ~800
   ├── Chunk 1  ~1700            ├── Chunk 1  ~780
   └── Chunk 2  ~1400            ├── Chunk 2  ~800
                                 ├── Chunk 3  ~760
                                 ├── ...
                                 └── Chunk N
```

We'll revisit this number in Arc E once Recall@K can actually measure whether
it was a good choice. For now it's a deliberate development-corpus setting,
not a production one.

---

## Step 1. Replace the chunker

Open:

```text
backend/app/ingestion/chunker.py
```

Replace the **entire file** with this:

```python
import re
from hashlib import sha256

from app.domain.chunk import Chunk
from app.domain.document import Document


class ParagraphChunker:

    def __init__(
        self,
        max_characters: int = 800,
        overlap_characters: int = 100,
    ):
        self.max_characters = max_characters
        self.overlap_characters = overlap_characters

    def chunk(self, document: Document) -> list[Chunk]:

        paragraphs = self._split_paragraphs(document.content)

        chunks: list[Chunk] = []
        current_parts: list[str] = []
        current_length = 0

        for paragraph in paragraphs:

            # A paragraph too large to ever fit in one chunk.
            if len(paragraph) > self.max_characters:

                # Don't lose what we were accumulating.
                if current_parts:
                    chunks.append(
                        self._create_chunk(
                            document,
                            current_parts,
                            len(chunks),
                        )
                    )

                    current_parts = []
                    current_length = 0

                for part in self._split_large_paragraph(paragraph):
                    chunks.append(
                        self._create_chunk(
                            document,
                            [part],
                            len(chunks),
                        )
                    )

                continue

            # It fits, but not alongside what we already have.
            if (
                current_parts
                and current_length + len(paragraph) > self.max_characters
            ):
                chunks.append(
                    self._create_chunk(
                        document,
                        current_parts,
                        len(chunks),
                    )
                )

                current_parts = self._get_overlap(current_parts)

                current_length = sum(
                    len(part) for part in current_parts
                )

            current_parts.append(paragraph)
            current_length += len(paragraph)

        if current_parts:
            chunks.append(
                self._create_chunk(
                    document,
                    current_parts,
                    len(chunks),
                )
            )

        return chunks

    @staticmethod
    def _split_paragraphs(text: str) -> list[str]:

        paragraphs = re.split(r"\n\s*\n", text)

        return [
            paragraph.strip()
            for paragraph in paragraphs
            if paragraph.strip()
        ]

    def _split_large_paragraph(
        self,
        paragraph: str,
    ) -> list[str]:

        parts = []
        start = 0

        while start < len(paragraph):

            end = min(
                start + self.max_characters,
                len(paragraph),
            )

            part = paragraph[start:end].strip()

            if part:
                parts.append(part)

            if end == len(paragraph):
                break

            start = end - self.overlap_characters

        return parts

    def _get_overlap(
        self,
        parts: list[str],
    ) -> list[str]:

        overlap = []
        total = 0

        for part in reversed(parts):

            if total + len(part) > self.overlap_characters:
                break

            overlap.insert(0, part)
            total += len(part)

        return overlap

    @staticmethod
    def _create_chunk(
        document: Document,
        parts: list[str],
        index: int,
    ) -> Chunk:

        text = "\n\n".join(parts)

        raw_id = (
            f"{document.document_id}:"
            f"{index}:"
            f"{text}"
        )

        chunk_id = sha256(
            raw_id.encode("utf-8")
        ).hexdigest()

        return Chunk(
            chunk_id=chunk_id,
            document_id=document.document_id,
            chunk_index=index,
            text=text,
            metadata={
                "filename": document.filename,
                "source": document.source,
                "character_count": len(text),
            },
        )
```

### Two details worth pausing on

**`if end == len(paragraph): break`** in `_split_large_paragraph`.

Without it, consider the last slice. We set `start = end - overlap`. If the
remaining tail is shorter than `overlap_characters`, `start` moves *backwards*
past where we already were, and the loop re-slices the same text forever. The
guard says: once we've consumed the paragraph, stop. Test the loop's exit
condition, not just its body. A `while` with arithmetic in the step is exactly
where infinite loops live.

**`raw_id` includes the chunk text, not just the index.**

```python
raw_id = f"{document.document_id}:{index}:{text}"
```

This makes the ID a function of *content*. Same document, same position, same
text → same `chunk_id`, forever. Which means re-running ingestion is an upsert
that changes nothing, and edited text produces a new ID we can detect. We will
lean on this hard in Lesson 4.

---

## Step 2. Fix the directory typo

`backend/app/retrival/` should be `retrieval/`. Every file in it is empty, so
this is free right now. It stops being free the moment we start importing from
it in Arc C.

From `backend/`, in PowerShell:

```powershell
Rename-Item app/retrival app/retrieval
```

Confirm:

```powershell
Get-ChildItem app/retrieval
```

You should see `__init__.py`, `graph.py`, `hybrid.py`, `router.py`,
`vector.py`.

---

## Step 3. Fill `.env.example`

`.env.example` is currently empty. Its job is to document every environment
variable the app reads, with safe placeholder values, so anyone cloning the
repo knows what to set. `.env` is gitignored; `.env.example` is committed.

Every key below mirrors a field in `app/config/settings.py`, and pydantic-settings
matches them case-insensitively.

Create `.env.example` at the project root with:

```dotenv
# Application
APP_NAME=Enterprise Graph RAG
ENVIRONMENT=development

# PostgreSQL (matches docker-compose.yml)
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=rag
POSTGRES_USER=rag
POSTGRES_PASSWORD=rag

# Neo4j (matches docker-compose.yml)
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password

# Ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_CHAT_MODEL=qwen3:8b
OLLAMA_EMBEDDING_MODEL=nomic-embed-text

# Optional hosted LLM providers, leave blank to use Ollama only
GROQ_API_KEY=
OPENROUTER_API_KEY=
ANTHROPIC_API_KEY=
```

Note the defaults in `settings.py` already match the docker-compose values, so
the app runs with no `.env` at all. That's intentional: local development
should need zero setup. The `.env` file is for when you deviate.

---

## Verify

From `backend/`:

```bash
pytest -s tests/test_ingestion.py
```

What to look for, in order:

**1. Chunk counts went up.**

```text
DOCUMENT: alphabet_inc.txt
CHUNKS: 6
```

Anywhere in the 4–12 range per document is healthy. The exact number is not
the goal.

**2. No chunk exceeds 800 characters.**

```text
Chunk 0
Characters: 742
Chunk 1
Characters: 800
Chunk 2
Characters: 689
```

If you see anything over 800, the oversized-paragraph branch isn't firing, so
check the `continue` at the end of it.

**3. `chunk_index` is sequential from 0, with no gaps**, in every document.
Gaps mean the `len(chunks)` counter got out of step with the list.

**4. The test still passes.** It asserts every chunk has a non-empty
`chunk_id`, non-empty text, and the right `document_id`.

Then run it a second time and compare a `chunk_id` between the two runs. It
must be identical. If it isn't, determinism is broken and Lesson 4 will
quietly duplicate every row in the database.

---

## Then say "next"

Once your chunk counts look sane, we start Arc B:

```text
Chunks
   │
   ├──────────────► PostgreSQL          ← Lesson 2 (schema)
   │                 documents, chunks
   │
   └──────────────► nomic-embed-text    ← Lesson 3
                           │
                           ▼
                       embeddings
                           │
                           ▼
                        pgvector        ← Lesson 5
                           │
                           ▼
                  first real search
```

Lesson 2 is the Postgres schema: two tables, the `vector` extension, and why
we're writing raw SQL instead of reaching for the ORM.
