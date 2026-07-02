from sentence_transformers import SentenceTransformer

# Loaded lazily on first actual use instead of at import time. Eagerly
# instantiating this at module load meant every single startup — even
# one that never touches RAG/documents — paid the full memory cost of
# loading PyTorch + the model weights before the app ever opened a
# port. On memory-constrained hosts (e.g. a 512MB free-tier instance)
# that alone was enough to OOM-kill the process during startup, before
# uvicorn ever got a chance to bind. Deferring the load means the app
# can start and serve everything that isn't document search/upload
# without paying that cost at all, and only pays it once, on first use.
_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


def create_embeddings(chunks):

    embeddings = _get_model().encode(
        chunks,
        convert_to_numpy=True
    )

    return embeddings

def create_query_embedding(query):

    embedding = _get_model().encode(
        query,
        convert_to_numpy=True
    )

    return embedding