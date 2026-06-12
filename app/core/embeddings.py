"""Embeddings provider abstraction (local fastembed ↔ Bedrock Titan).

Same `embed_documents` / `embed_query` surface regardless of provider, so the
ingestion pipeline and RAG tools never know which one is active. Swapping is a
config flip (EMBEDDINGS_PROVIDER) — but remember EMBEDDING_DIM and the pgvector
column dimension must match the active model (bge-small = 384, Titan v2 = 1024).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Protocol, runtime_checkable


@runtime_checkable
class Embedder(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


class FastEmbedEmbedder:
    """Local ONNX embeddings via fastembed (no API key required)."""

    def __init__(self, model_name: str) -> None:
        from fastembed import TextEmbedding

        self._model = TextEmbedding(model_name=model_name)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[float(x) for x in vec] for vec in self._model.embed(texts)]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


@lru_cache
def get_embedder() -> Embedder:
    """Return a process-wide singleton embedder (model load is expensive)."""
    from app.core.config import settings

    provider = settings.embeddings_provider.lower()
    if provider == "fastembed":
        return FastEmbedEmbedder(settings.fastembed_model)
    if provider == "bedrock":
        from langchain_aws import BedrockEmbeddings

        # BedrockEmbeddings already exposes embed_documents/embed_query.
        return BedrockEmbeddings(
            model_id=settings.bedrock_embeddings_model_id,
            region_name=settings.aws_region,
        )
    raise ValueError(
        f"Unknown EMBEDDINGS_PROVIDER {settings.embeddings_provider!r} "
        "(use 'fastembed' or 'bedrock')"
    )
