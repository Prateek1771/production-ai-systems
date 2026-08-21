from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.routes import router
from app.infrastructure.neo4j import verify_connection
from app.infrastructure.postgres import engine
from app.observability.logging import configure_logging


configure_logging()


app = FastAPI(
    title="Enterprise Knowledge Graph RAG",
    version="0.2.0",
)


# The Vite dev server runs on a different origin, so the browser needs
# this to call the API at all.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(router)


@app.get("/health")
def health():
    postgres_ok = False

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            postgres_ok = True
    except Exception:
        postgres_ok = False

    neo4j_ok = verify_connection()

    return {
        "status": "ok" if postgres_ok and neo4j_ok else "degraded",
        "postgres": postgres_ok,
        "neo4j": neo4j_ok,
    }
