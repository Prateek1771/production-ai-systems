# Lesson 2. Persisting chunks in Postgres

## Where we are

Lesson 1 worked. Your corpus now chunks like this:

```text
23 documents  →  134 chunks  →  largest chunk: 800 chars
```

Nothing exceeds the limit, so the oversized-paragraph branch fires correctly.

All 134 chunks live in a Python list that dies when the test process exits.
Nothing is persisted. This lesson fixes that.

### Something I noticed in your data

```text
alphabet_inc.txt      7 chunks    4007 bytes
sam_altman.txt        8 chunks    4017 bytes
...
microsoft.txt         2 chunks    1425 bytes   ←
nvidia.txt            2 chunks    1124 bytes   ←
openai.txt            2 chunks    1124 bytes   ←
satya_nadella.txt     2 chunks    1204 bytes   ←
```

Four documents run about a third the size of the others. They're the four you
wrote first, before you settled on how much text per file. Leave them for now,
but remember it. When we measure retrieval in Arc E, questions about Microsoft,
NVIDIA, OpenAI, and Satya Nadella will underperform, and it will look like a
retrieval bug when the real problem is the corpus. Better ranking cannot fix a
thin source document.

---

## The shape we're building

```text
┌─────────────────────────────────────────┐
│ documents                               │
│  document_id  TEXT  PK   ← sha256       │
│  filename, source, title                │
│  content, content_hash                  │
│  metadata     JSONB                     │
└──────────────────┬──────────────────────┘
                   │  1 : N   ON DELETE CASCADE
┌──────────────────▼──────────────────────┐
│ chunks                                  │
│  chunk_id     TEXT  PK   ← sha256       │
│  document_id  TEXT  FK                  │
│  chunk_index  INT                       │
│  text         TEXT                      │
│  metadata     JSONB                     │
│  embedding    vector(768)   ← NULL now  │
└─────────────────────────────────────────┘
```

Two tables, mirroring the two dataclasses in `app/domain/`. I want the
database shape and the domain shape to agree, so the persistence layer stays a
translation and nothing more. Once they diverge you start writing mapping
logic, and mapping logic is where the bugs live.

---

## Five decisions in this schema

### 1. Text primary keys, not SERIAL

Almost every tutorial hands you `id SERIAL PRIMARY KEY`. We're using the
sha256 hex string the application already computed.

This is why we made those IDs deterministic in Lesson 1.

```text
SERIAL                          sha256 from the app
──────                          ───────────────────
INSERT, then read back the ID   ID known before touching the DB
re-ingest → duplicate rows      re-ingest → conflicts on the PK,
  with different IDs              which we turn into a no-op
the ID means nothing            the ID fingerprints the content
```

With a content-derived primary key, `ON CONFLICT DO NOTHING` gives us
idempotent ingestion for free. With SERIAL we'd have to invent a separate
uniqueness rule and enforce it ourselves. That boring 64-character text key
buys us most of Lesson 4.

The cost is real, so let's name it. A 64-byte key is bigger than a 4-byte int,
so the indexes get larger. At 134 chunks, or at 134 million, the trade still
holds.

### 2. The embedding column is nullable, and it lives on chunks

We create the column now and leave every value NULL until Lesson 3.

That splits ingestion into two phases you can restart independently.

```text
phase 1: chunks → rows            fast, deterministic, no network
phase 2: rows → embeddings        slow, calls Ollama 134 times, can fail
```

If phase 2 dies on chunk 97, phase 1's work survives, and we resume by asking
`WHERE embedding IS NULL`. Write the chunk and its embedding in one transaction
instead, and a network blip rolls back the whole corpus.

That `WHERE embedding IS NULL` query is the resume mechanism. Nullable here
isn't sloppiness, it's the state machine.

### 3. vector(768), and why the number isn't negotiable

768 is the output dimension of `nomic-embed-text`. Not a tuning knob. A
property of the model.

pgvector fixes the dimension when you define the column, then rejects any
insert of the wrong length. I like that rejection. The day you switch embedding
models you find out at the database boundary instead of silently retrieving
garbage. A vector column is a contract with one specific model.

Swap models later and you have to drop this column and rebuild it. That's
correct. Old and new vectors aren't comparable, so keeping them side by side
would be worse than losing them.

### 4. metadata as JSONB

Our dataclasses carry `metadata: dict`. JSONB stores that as-is, without us
inventing a column per key.

Here's the rule we're following. Anything we filter or join on gets a real
column. Everything else goes in JSONB. `filename` matters for citations, so it
gets a column. `file_size` is trivia, so it lives in the blob. When a JSONB key
turns out to be something you filter on in every query, that's the signal to
promote it.

JSONB rather than JSON, because Postgres parses it on write, so reads are fast
and you can index it.

### 5. No vector index yet

You might expect an HNSW index in this lesson. It arrives in Lesson 5, on
purpose.

Build HNSW on an empty table and then insert 134 rows, and you get a slower
build and a worse graph than if you load the rows first and build the index
once at the end. An approximate-nearest-neighbour index takes its structure
from how the data is actually distributed, and an empty table has no
distribution.

Load first. Index second.

---

## Why raw SQL instead of the ORM

We have SQLAlchemy installed and we're going to use exactly one part of it, the
`Engine`, for connection pooling and safe parameter binding. No
`declarative_base`, no model classes, no `session.add()`.

```text
what the ORM gives us            what we actually need
─────────────────────            ─────────────────────
object identity tracking         no,  our IDs come from sha256
lazy relationship loading        no,  we query chunks directly
dialect portability              no,  we are betting on pgvector
change detection / dirty state   no,  ingestion is insert-only
──────────────────────────────────────────────────────────────
connection pooling               yes  ← Engine
parameterised queries            yes  ← Engine
```

Two of eleven. And the things we do need, `CREATE EXTENSION vector`, the `<=>`
cosine operator, `WITH (m = 16, ef_construction = 64)` on the index, are all
things the ORM either can't express or makes us smuggle through `text()`
anyway.

The trade-off is honest, so here it is. We hand-write our INSERTs now, so a
typo in a column name becomes a runtime error instead of something your editor
catches. I'll take that over fighting an abstraction on every query for the
rest of the project. Use SQLAlchemy Core, skip the ORM.

We still never build SQL by string interpolation. Every value goes through
bound parameters. That's SQL injection defence, not elegance, and it applies
whether or not you use an ORM.

---

## Step 1. Write the schema

Create a new file:

```text
backend/app/infrastructure/schema.py
```

```python
from sqlalchemy import text

from app.infrastructure.postgres import engine


EMBEDDING_DIMENSIONS = 768


CREATE_EXTENSION = """
CREATE EXTENSION IF NOT EXISTS vector
"""


CREATE_DOCUMENTS = """
CREATE TABLE IF NOT EXISTS documents (
    document_id   TEXT PRIMARY KEY,
    filename      TEXT NOT NULL,
    source        TEXT NOT NULL,
    title         TEXT NOT NULL,
    content       TEXT NOT NULL,
    content_hash  TEXT NOT NULL,
    metadata      JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


CREATE_CHUNKS = f"""
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id      TEXT PRIMARY KEY,
    document_id   TEXT NOT NULL
                  REFERENCES documents (document_id)
                  ON DELETE CASCADE,
    chunk_index   INTEGER NOT NULL,
    text          TEXT NOT NULL,
    metadata      JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    embedding     vector({EMBEDDING_DIMENSIONS}),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (document_id, chunk_index)
)
"""


CREATE_CHUNKS_DOCUMENT_INDEX = """
CREATE INDEX IF NOT EXISTS chunks_document_id_idx
    ON chunks (document_id)
"""


STATEMENTS = [
    CREATE_EXTENSION,
    CREATE_DOCUMENTS,
    CREATE_CHUNKS,
    CREATE_CHUNKS_DOCUMENT_INDEX,
]


def create_schema() -> None:

    with engine.begin() as connection:

        for statement in STATEMENTS:
            connection.execute(text(statement))


if __name__ == "__main__":

    create_schema()

    print("schema created")

    with engine.connect() as connection:

        for table in ("documents", "chunks"):

            count = connection.execute(
                text(f"SELECT count(*) FROM {table}")
            ).scalar()

            print(f"{table}: {count} rows")
```

### Details worth pausing on

**engine.begin(), not engine.connect().** `connect()` hands you a connection
you have to commit yourself. `begin()` opens a transaction, commits on clean
exit, and rolls back on exception. For DDL you want all or nothing. If
`CREATE TABLE chunks` fails, you don't want a half-built schema with
`documents` present and `chunks` missing. Postgres is one of the few databases
with transactional DDL, so use it.

This is the most common way people lose an afternoon with SQLAlchemy. You use
`connect()`, run an INSERT, see no error, then find no rows. The write happened
and got rolled back at close. Reads use `connect()`. Writes use `begin()`.

**The doubled braces in CREATE_CHUNKS.** It's an f-string, so
`{EMBEDDING_DIMENSIONS}` needs interpolating and `'{}'::jsonb` needs leaving
alone. `{{}}` is how you write a literal `{}` inside an f-string. Drop one
brace and you get a confusing `KeyError`.

**UNIQUE (document_id, chunk_index).** The primary key already stops duplicate
`chunk_id` values. This constraint catches a different bug, two different
chunks both claiming to be chunk 3 of the same document. That's the corruption
a broken `len(chunks)` counter produces, and it would quietly break citation
ordering. We checked ordering by eye in Lesson 1. From here the database
enforces it.

**ON DELETE CASCADE.** Delete a document and its chunks go with it. Without
this, re-ingesting an edited file leaves orphaned chunks that still surface in
search results and cite a document that no longer exists. An orphaned row in a
RAG system is a wrong answer with a confident citation.

**CREATE EXTENSION IF NOT EXISTS vector.** The `pgvector/pgvector:pg16` image
ships the extension binary but doesn't enable it in your database. This line is
what makes `vector(768)` a valid type. It needs superuser, which the `rag` user
has in this container.

---

## Step 2. Run it

From `backend/`:

```bash
python -m app.infrastructure.schema
```

Expected:

```text
schema created
documents: 0 rows
chunks: 0 rows
```

`ModuleNotFoundError: No module named 'app'` means you're not in `backend/`, or
the venv isn't active.

---

## Verify

### 1. Run it a second time

```bash
python -m app.infrastructure.schema
```

Same output, no error. Every statement is `IF NOT EXISTS`, so the script is
idempotent and safe to run on every boot, in a container entrypoint, or in CI.
This is the real check for this lesson. A schema script you're afraid to run
twice is a schema script you'll be afraid to run in production.

### 2. Inspect the real table

```bash
docker exec -it rag-postgres psql -U rag -d rag -c "\d chunks"
```

Look for:

```text
 embedding    | vector(768) |
```

If it says `vector` with no dimension, or the command errors on the type, the
extension didn't get created. Check that `CREATE_EXTENSION` comes first in
`STATEMENTS`.

Confirm the foreign key at the bottom too:

```text
Foreign-key constraints:
    "chunks_document_id_fkey" FOREIGN KEY (document_id)
        REFERENCES documents(document_id) ON DELETE CASCADE
```

### 3. Prove the extension is live

```bash
docker exec -it rag-postgres psql -U rag -d rag -c "SELECT '[1,2,3]'::vector;"
```

```text
 vector
---------
 [1,2,3]
```

That's pgvector parsing a vector literal. The extension works.

### 4. Prove the dimension is enforced

```bash
docker exec -it rag-postgres psql -U rag -d rag \
  -c "INSERT INTO chunks (chunk_id, document_id, chunk_index, text, embedding)
      VALUES ('x', 'y', 0, 'z', '[1,2,3]');"
```

This has to fail. You'll hit one of two errors, and either one is a pass:

```text
ERROR:  expected 768 dimensions, not 3
```

or

```text
ERROR:  insert or update on table "chunks" violates foreign key constraint
```

Both are the schema defending itself. A successful insert here means something
is wrong.

---

## Then say "next"

```text
Chunks in memory       done
      │
      ▼
PostgreSQL schema      done   ← you are here
      │
      ▼
nomic-embed-text              ← Lesson 3
  134 chunks → 134 vectors of 768 floats
      │
      ▼
rows written                  ← Lesson 4
      │
      ▼
first search                  ← Lesson 5
```

Lesson 3 is the embedding client. Wrapping Ollama, batching the calls, and
retrying with `tenacity` when it times out. It's the first time this project
talks to a model.
