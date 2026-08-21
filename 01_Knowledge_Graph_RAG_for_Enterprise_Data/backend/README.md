# Backend

FastAPI service for hybrid knowledge graph and vector RAG. Postgres with
pgvector holds passages and embeddings, Neo4j holds entities and relations, and
both key on the same `chunk_id` so an answer can be traced back to its source
text.

## Running it

Start the databases from the project root:

```bash
docker compose up -d
```

Then from `backend/`:

```bash
python -m app.infrastructure.schema        # create tables, idempotent
python -m app.vector.repository            # ingest + embed the corpus
python -m app.extraction.extractor         # LLM extraction, resumable
python -m app.graph.repository             # build the graph, idempotent
python -m app.vector.store                 # build the HNSW index
uvicorn app.main:app --reload
```

Every one of those is safe to re-run. Ingestion skips unchanged documents,
embedding resumes from `WHERE embedding IS NULL`, extraction resumes from a
`LEFT JOIN` against `chunk_extractions`, and the graph uses `MERGE`.

## Layout

```text
app/
  config/settings.py        every knob, defaults matching docker-compose
  infrastructure/           engine, driver, schema DDL
  domain/                   dataclasses: Document, Chunk, Entity, SearchHit
  ingestion/                loader, paragraph chunker, pipeline
  vector/                   embeddings, upserts, similarity search
  extraction/               closed schema, validator, LLM extractor, resolver
  graph/                    Neo4j client, MERGE writes, Cypher templates
  retrieval/                router, graph retrieval, hybrid fusion
  generation/               context builder, prompts, citation validator
  llm/                      Groq, OpenRouter, provider gateway
  observability/            structured logs, per-stage timings
  evaluation/               benchmark harness
```

## API

```text
POST /query                 question in, cited answer out
GET  /chunks/{chunk_id}     resolve a citation to its text
GET  /graph/neighbourhood   nodes and edges for the UI
GET  /stats                 row and node counts
POST /ingest                run the pipeline
GET  /health                per-dependency status
```

## Things that will bite you

**Groq's free tier caps 200,000 tokens per day**, and no response header
reports it. `x-ratelimit-remaining-tokens` describes only the per-minute
bucket, so it will read 7,900 free while every call fails. The limit appears
only in the 429 body. Budget before a bulk run: extraction costs about 733
tokens per chunk with `reasoning_effort="low"`.

**`reasoning_effort="low"` is not just cheaper.** `gpt-oss` is a reasoning
model, and its output tokens also drive Groq's `json_validate_failed` rate.
Default effort measured 1,956 tokens per call with 43% of chunks failing every
retry; low effort measured 733 tokens and near zero failures.

**`json_validate_failed` is a 400, not a 429.** It is transient and should be
retried immediately. Giving it the long wait a rate limit needs turns a 25%
failure rate into minutes of dead time per item. See `_wait_for_error`.

**Order vector searches by the raw distance operator.** `ORDER BY embedding <=>
q` uses the HNSW index. `ORDER BY 1 - (embedding <=> q) DESC` returns identical
rows 250 times slower, because wrapping the operator in arithmetic stops the
planner matching it to the index. The index opclass must also match the
operator you query with.

**psycopg will not adapt a `dict` to JSONB or a `list` to `vector`.** Pass
`json.dumps(...)` with `CAST(:x AS jsonb)`, and a vector literal string with
`CAST(:x AS vector)`. A bare list does insert into a `vector` column, then the
`<=>` operator refuses it, so the bug surfaces a lesson later than its cause.

**Entity resolution merges on embedding similarity above 0.86.** That threshold
is measured, not guessed: 0.84 gives precision 1.00 and recall 0.80 on 23
labelled pairs from this corpus, and 0.82 drops precision to 0.67. There is no
token-containment shortcut, because one merged `Dario Amodei`, `Daniela
Amodei`, and `Riccardo Amodei` into a single person.

## Tests

```bash
pytest tests/ -q
```

Most modules also run standalone as a self-check:

```bash
python -m app.extraction.schemas      # validator against real bad model output
python -m app.llm.base                # provider gateway and failover
python -m app.retrieval.router        # routing heuristics
python -m app.observability.logging   # trace and stage timings
```

## Benchmark

```bash
python -m app.evaluation.benchmark --out ../docs/benchmark.json
```

Compares hybrid retrieval against a vector-only baseline over 60 questions
stratified by hop count. The question set is at `data/benchmark/questions.json`
and is model-authored, which is weaker evidence than human labels and is
stated as such in the root README.
