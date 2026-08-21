"""Intentionally empty.

The scaffold put a `vector.py` here next to `graph.py` and `hybrid.py` for
symmetry, and symmetry is not a reason for a module to exist. Vector
retrieval already has a home in `app/vector/store.py`, where the SQL and
the `hnsw.ef_search` setting live next to each other. A file here would
be a re-export, which costs an import and a jump and returns nothing.

If vector retrieval ever needs question-side logic that does not belong
next to the SQL, such as query rewriting or a score threshold that
depends on the router's decision, that logic goes here and this note
goes away.

See `app.vector.store.VectorStore.search`.
"""
