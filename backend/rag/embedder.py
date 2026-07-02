import os

import numpy as np
from huggingface_hub import InferenceClient

# ── Why this changed ──────────────────────────────────────────────────────
# This module used to load a full SentenceTransformer (+ PyTorch) model
# into memory at import time. On a memory-constrained host (e.g. Render's
# free tier, 512MB) that alone was enough to OOM-kill the process before
# it ever finished starting up. Deferring the load to first use (an
# earlier fix) only moved the crash to the first document upload/search
# instead of preventing it -- the same ~model-sized memory spike still had
# to happen somewhere in the same process.
#
# This version calls Hugging Face's hosted Inference API for the exact
# same model instead of running it locally. No local model weights, no
# torch, no meaningful memory footprint for this feature at all -- the
# actual computation happens on Hugging Face's infrastructure, not here.
#
# Requires an HF_TOKEN environment variable (free -- create a "Read"
# access token at https://huggingface.co/settings/tokens). Without it,
# requests are unauthenticated and subject to much lower rate limits --
# workable for local dev, not recommended for a real deployment.

_MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"

_client: InferenceClient | None = None


def _get_client() -> InferenceClient:
    global _client
    if _client is None:
        _client = InferenceClient(
            provider="hf-inference",
            api_key=os.environ.get("HF_TOKEN"),
        )
    return _client


def _embed_one(text: str) -> np.ndarray:
    result = _get_client().feature_extraction(text, model=_MODEL_ID)
    vec = np.asarray(result, dtype=np.float32)
    # Defensive: this endpoint returns one pooled vector per input for
    # sentence-transformers models, but if it ever comes back as a
    # per-token matrix instead (an extra leading dimension), collapse
    # it to a single sentence vector via mean pooling rather than hand
    # back a shape nothing downstream expects.
    if vec.ndim > 1:
        vec = vec.mean(axis=0)
    return vec


def create_embeddings(chunks):
    return np.stack([_embed_one(c) for c in chunks])


def create_query_embedding(query):
    return _embed_one(query)