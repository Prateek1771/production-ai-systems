## Build Plan

```
                         ┌──────────────────────┐
                         │      React UI        │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │       FastAPI        │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │   RAG Orchestrator   │
                         └──────────┬───────────┘
                                    │
                         ┌──────────┴──────────┐
                         │                     │
                         ▼                     ▼
                   Query Router          Question Parser
                         │
                ┌────────┴────────┐
                │                 │
                ▼                 ▼
          Vector Retrieval   Graph Retrieval
                │                 │
                ▼                 ▼
           PostgreSQL          Neo4j
           + pgvector
                │                 │
                └────────┬────────┘
                         ▼
                  Context Builder
                         │
                         ▼
                 Citation Validator
                         │
                         ▼
                    LLM Gateway
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
       Ollama           Groq        OpenRouter
          │
     Qwen / Gemma
                         │
                         ▼
                      Answer
```