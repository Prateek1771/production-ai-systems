from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Enterprise Graph RAG"
    environment: str = "development"

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "rag"
    postgres_user: str = "rag"
    postgres_password: str = "rag"

    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "password"

    ollama_base_url: str = "http://localhost:11434"
    ollama_chat_model: str = "qwen3:8b"
    ollama_embedding_model: str = "nomic-embed-text"

    groq_api_key: str | None = None
    groq_model: str = "openai/gpt-oss-20b"
    # Free tier caps tokens per minute, not requests. Read the real
    # value from the x-ratelimit-limit-tokens response header.
    groq_tokens_per_minute: int = 8000
    # gpt-oss is a reasoning model. "low" cuts a call from ~1956 tokens
    # to ~733 and stops Groq's JSON validator failing on long output.
    groq_reasoning_effort: str | None = "low"

    openrouter_api_key: str | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "openai/gpt-oss-20b"

    anthropic_api_key: str | None = None

    # Retrieval tuning. Measured in Lesson 11.
    retrieval_top_k: int = 5
    hnsw_ef_search: int = 40
    resolution_threshold: float = 0.86

    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=Path(__file__).parents[2] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()