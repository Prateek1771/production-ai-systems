"""HTTP surface. One orchestrator function, wired to /query."""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from sqlalchemy import text as sql

from app.api.schemas import (
    ChunkOut,
    CitationOut,
    FactOut,
    GraphOut,
    IngestRequest,
    IngestResponse,
    PassageOut,
    QueryRequest,
    QueryResponse,
    StatsResponse,
)
from app.domain.retrieval import Route
from app.generation.citations import Answerer
from app.generation.context import build_context
from app.infrastructure.postgres import engine
from app.observability.logging import Trace, log
from app.retrieval.graph import link_entities, neighbourhood
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.router import log_decision


router = APIRouter()

_retriever: HybridRetriever | None = None
_answerer: Answerer | None = None


def get_retriever() -> HybridRetriever:
    global _retriever
    if _retriever is None:
        _retriever = HybridRetriever()
    return _retriever


def get_answerer() -> Answerer:
    global _answerer
    if _answerer is None:
        _answerer = Answerer()
    return _answerer


@router.post("/query", response_model=QueryResponse)
def query(request: QueryRequest) -> QueryResponse:

    trace = Trace()
    retriever = get_retriever()

    with trace.stage("retrieve"):
        result = retriever.retrieve(
            request.question,
            limit=request.top_k,
            route=request.route,
            trace_id=trace.trace_id,
            log=False,
        )

    with trace.stage("build_context"):
        context = build_context(result, max_passages=request.top_k)

    with trace.stage("generate"):
        validated = get_answerer().answer(request.question, context)

    graph_payload = None

    if request.include_graph and result.question_entities:
        with trace.stage("graph_view"):
            entity_ids = [
                entity.entity_id
                for entity in link_entities(request.question)
            ]
            if entity_ids:
                graph_payload = neighbourhood(entity_ids)

    trace.note(
        route=str(result.route),
        confidence=result.confidence,
        chunks=len(result.chunk_ids),
        citations=len(validated.citations),
        refused=validated.refused,
        repaired=validated.repaired,
    )
    trace.emit()

    log_decision(
        trace_id=trace.trace_id,
        question=request.question,
        route=result.route,
        confidence=result.confidence,
        fallback=result.fallback,
        hit_count=len(result.chunk_ids),
        latency_ms=trace.total_ms,
    )

    return QueryResponse(
        trace_id=trace.trace_id,
        question=request.question,
        answer=validated.answer,
        refused=validated.refused,
        repaired=validated.repaired,
        route=result.route,
        confidence=result.confidence,
        question_entities=result.question_entities,
        citations=[
            CitationOut(
                marker=c.marker,
                kind=c.kind,
                chunk_ids=c.chunk_ids,
                text=c.text,
            )
            for c in validated.citations
        ],
        passages=[
            PassageOut(
                chunk_id=p.chunk_id,
                filename=p.filename,
                chunk_index=p.chunk_index,
                similarity=round(p.similarity, 4),
                text=p.text,
            )
            for p in result.passages
        ],
        facts=[
            FactOut(
                statement=f.statement,
                hops=f.hops,
                chunk_ids=f.chunk_ids,
                relation_path=f.relation_path,
            )
            for f in result.facts
        ],
        graph=GraphOut(**graph_payload) if graph_payload else None,
        stages=trace.stages,
        total_ms=trace.total_ms,
    )


@router.get("/chunks/{chunk_id}", response_model=ChunkOut)
def get_chunk(chunk_id: str) -> ChunkOut:
    """Resolve a citation to the text it points at."""

    with engine.connect() as connection:
        row = connection.execute(
            sql(
                "SELECT chunk_id, document_id, chunk_index, text, "
                "metadata->>'filename' AS filename "
                "FROM chunks WHERE chunk_id = :chunk_id"
            ),
            {"chunk_id": chunk_id},
        ).one_or_none()

    if row is None:
        raise HTTPException(status_code=404, detail="unknown chunk")

    return ChunkOut(
        chunk_id=row.chunk_id,
        document_id=row.document_id,
        filename=row.filename,
        chunk_index=row.chunk_index,
        text=row.text,
    )


@router.get("/graph/neighbourhood", response_model=GraphOut)
def graph_neighbourhood(name: str, depth: int = 1) -> GraphOut:
    linked = link_entities(name)

    if not linked:
        return GraphOut(nodes=[], edges=[])

    payload = neighbourhood([e.entity_id for e in linked])
    return GraphOut(**payload)


@router.get("/stats", response_model=StatsResponse)
def stats() -> StatsResponse:
    from app.graph.repository import graph_counts

    with engine.connect() as connection:
        row = connection.execute(
            sql(
                """
                SELECT
                  (SELECT count(*) FROM documents) AS documents,
                  (SELECT count(*) FROM chunks) AS chunks,
                  (SELECT count(*) FROM chunks WHERE embedding IS NOT NULL) AS embedded,
                  (SELECT count(*) FROM chunk_extractions) AS extracted
                """
            )
        ).one()

    try:
        graph = graph_counts()
    except Exception:
        graph = {"entities": 0, "relations": 0, "mentions": 0}

    return StatsResponse(
        documents=row.documents,
        chunks=row.chunks,
        embedded=row.embedded,
        extracted=row.extracted,
        entities=graph.get("entities", 0),
        relations=graph.get("relations", 0),
        mentions=graph.get("mentions", 0),
    )


@router.post("/ingest", response_model=IngestResponse)
def ingest(request: IngestRequest) -> IngestResponse:
    from app.extraction.extractor import extract_pending
    from app.graph.repository import write_graph
    from app.vector.repository import backfill_embeddings, ingest_corpus

    directory = Path(
        request.directory
        or Path(__file__).parents[3] / "data" / "raw"
    )

    if not directory.is_dir():
        raise HTTPException(status_code=400, detail=f"no such directory: {directory}")

    written, skipped, chunks = ingest_corpus(directory)

    embeddings = backfill_embeddings() if request.embed else 0
    extractions = extract_pending()[0] if request.extract else 0
    graph = write_graph() if request.build_graph else {}

    log(
        "ingest",
        documents=written,
        skipped=skipped,
        chunks=chunks,
        embeddings=embeddings,
        extractions=extractions,
    )

    return IngestResponse(
        documents_written=written,
        documents_skipped=skipped,
        chunks_written=chunks,
        embeddings_added=embeddings,
        extractions_added=extractions,
        graph=graph,
    )
