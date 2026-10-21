"""Retrieval behind the search_docs tool.

`Retriever` is the seam (ADR-001): the tutor depends only on the protocol, so a host app can plug in
a `QdrantRetriever` for its own corpus. `PgHybridRetriever` calls `tutor.hybrid_search` (RRF of
HNSW cosine + FTS, one row per distinct chunk text) on the local Supabase Postgres.
"""
from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Protocol

import httpx
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from backend.tutor.schemas import Chunk

# search_docs exposes a fixed `products` enum (prompts/tools.md); the corpus stores the URL-derived
# product (scripts/ingest_llms.py: product_of). Each tool value expands to the stored values it covers.
# Unknown values pass through unchanged. Pages kept from llms-full.txt are stored as 'full' and only
# match unfiltered searches, because that file carries no per-page URL to derive a product from.
PRODUCT_ALIASES: dict[str, tuple[str, ...]] = {
    "kb": ("kb", "troubleshooting"),
    "database": ("database", "cron", "queues"),
    "platform": ("platform", "deployment", "hosting"),
    "observability": ("observability", "monitoring-and-debugging"),
    "ai": ("ai", "ai-tools"),
    "api": ("api", "graphql"),
    "other": ("other", "getting-started", "integrations", "resources"),
}

# hnsw.ef_search and hnsw.iterative_scan are pinned on tutor.hybrid_search itself
# (migration 20261021020000), so filtered searches keep their semantic hits for every caller.
RERANK_POOL = 30


class Embedder(Protocol):
    model: str

    async def embed_query(self, text: str) -> list[float]: ...


class Retriever(Protocol):
    async def search(self, query: str, k: int = 8, products: Sequence[str] | None = None) -> list[Chunk]: ...


class Reranker(Protocol):
    async def rerank(self, query: str, chunks: list[Chunk], k: int) -> list[Chunk]: ...


class OllamaEmbedder:
    """nomic-embed-text via Ollama; queries carry the nomic `search_query: ` prefix (chunks use
    `search_document: `, see the ingest script)."""

    model = "nomic-embed-text"

    def __init__(self, base_url: str | None = None, client: httpx.AsyncClient | None = None) -> None:
        self.url = (base_url or os.environ.get("OLLAMA_URL", "http://localhost:11434")) + "/api/embed"
        self.client = client or httpx.AsyncClient(timeout=60)

    async def embed_query(self, text: str) -> list[float]:
        r = await self.client.post(self.url, json={"model": self.model, "input": [f"search_query: {text}"]})
        r.raise_for_status()
        return list(r.json()["embeddings"][0])


class OpenAIEmbedder:
    """text-embedding-3-small truncated to 768 dims so the column type never changes (ADR-003)."""

    model = "text-embedding-3-small@768"

    def __init__(self, api_key: str | None = None, client: httpx.AsyncClient | None = None) -> None:
        self.api_key = api_key or os.environ["OPENAI_API_KEY"]
        self.client = client or httpx.AsyncClient(timeout=60)

    async def embed_query(self, text: str) -> list[float]:
        r = await self.client.post(
            "https://api.openai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": "text-embedding-3-small", "input": [text], "dimensions": 768},
        )
        r.raise_for_status()
        return list(r.json()["data"][0]["embedding"])


def embedder_from_env() -> Embedder:
    provider = os.environ.get("EMBEDDINGS_PROVIDER", "ollama")
    if provider == "ollama":
        return OllamaEmbedder()
    if provider == "openai":
        return OpenAIEmbedder()
    raise ValueError(f"unknown EMBEDDINGS_PROVIDER {provider!r}")


def expand_products(products: Sequence[str] | None) -> list[str] | None:
    if not products:
        return None
    out: list[str] = []
    for p in products:
        for stored in PRODUCT_ALIASES.get(p, (p,)):
            if stored not in out:
                out.append(stored)
    return out


class PgHybridRetriever:
    """search_docs over tutor.hybrid_search. The pool must point at the local tutor database."""

    def __init__(self, pool: AsyncConnectionPool, embedder: Embedder, reranker: Reranker | None = None) -> None:
        self.pool = pool
        self.embedder = embedder
        self.reranker = reranker

    async def search(self, query: str, k: int = 8, products: Sequence[str] | None = None) -> list[Chunk]:
        embedding = await self.embedder.embed_query(query)
        fetch_k = max(k, RERANK_POOL) if self.reranker else k
        async with self.pool.connection() as conn:
            cur = conn.cursor(row_factory=dict_row)
            await cur.execute(
                "select * from tutor.hybrid_search(%s, %s::extensions.vector, %s, %s)",
                (query, str(embedding), fetch_k, expand_products(products)),
            )
            chunks = [Chunk(**row) for row in await cur.fetchall()]
        if self.reranker:
            return await self.reranker.rerank(query, chunks, k)
        return chunks
