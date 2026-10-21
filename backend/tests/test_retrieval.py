"""Retriever tests: offline unit tests plus quality checks on 3 handmade chunks in the local DB."""
from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Sequence
from uuid import uuid4

import httpx
import psycopg
import pytest
from psycopg_pool import AsyncConnectionPool

from backend.tutor.retrieval import OllamaEmbedder, PgHybridRetriever, expand_products
from backend.tutor.schemas import Chunk

TEST_PRODUCT = "zz-retrieval-test"  # isolates fixture rows from the real corpus

FIXTURES = {
    "rls": ("https://example.test/troubleshooting/database-api-42501-errors.md", "missing-table-level-privileges",
            "42501 errors > Missing table-level privileges",
            ("A 42501 `permission denied for table` error means the role has no table-level privilege such as "
             "SELECT or INSERT on that table. Grant the privilege to the anon or authenticated role; Row Level "
             "Security policies are only evaluated after the privilege check passes.")),
    "timeout": ("https://example.test/database/postgres/timeouts.md", "role-level",
                "Timeouts > Role level",
                ("The statement_timeout setting cancels any statement that runs longer than the configured limit. "
                 "It can be changed per role with alter role ... set statement_timeout.")),
    "pooler": ("https://example.test/troubleshooting/supavisor-faq.md", "transaction-mode",
               "Supavisor FAQ > Transaction mode vs session mode",
               ("In transaction mode the pooler hands out a server connection per transaction, so prepared "
                "statements are not supported. Disable them in your client or ORM, or connect in session mode.")),
}


# ----------------------------------------------------------------------------- offline
def test_expand_products_maps_tool_enum_to_stored_values() -> None:
    assert expand_products(None) is None
    assert expand_products([]) is None
    assert expand_products(["kb", "auth"]) == ["kb", "troubleshooting", "auth"]
    assert expand_products(["database", "database"]) == ["database", "cron", "queues"]
    assert expand_products(["zz-unknown"]) == ["zz-unknown"]


async def test_ollama_embedder_uses_nomic_query_prefix() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"embeddings": [[0.5] * 768]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    emb = await OllamaEmbedder(base_url="http://ollama.test", client=client).embed_query("why 42501")
    assert seen == {"model": "nomic-embed-text", "input": ["search_query: why 42501"]}
    assert len(emb) == 768


# ----------------------------------------------------------------------------- local DB + Ollama
@pytest.fixture
async def fixture_chunks(db_url: str, ollama_up: None) -> AsyncIterator[dict[str, str]]:
    embed_doc = httpx.AsyncClient(timeout=60)
    ids: dict[str, str] = {}
    source_ids = []
    with psycopg.connect(db_url, autocommit=True) as conn:
        for key, (url, anchor, path, content) in FIXTURES.items():
            r = await embed_doc.post("http://localhost:11434/api/embed", json={
                "model": "nomic-embed-text", "input": [f"search_document: {path}\n{content}"]})
            r.raise_for_status()
            sid, cid = uuid4(), uuid4()
            source_ids.append(sid)
            conn.execute("insert into tutor.docs_source (id, url, tier, product) values (%s, %s, 1, %s)",
                         (sid, url, TEST_PRODUCT))
            conn.execute(
                "insert into tutor.docs_chunk (id, source_id, ord, heading_path, anchor, content, content_hash,"
                " meta, embedding) values (%s, %s, 0, %s, %s, %s, %s, %s, %s::extensions.vector)",
                (cid, sid, path, anchor, content, hashlib.sha256(content.encode()).hexdigest(),
                 json.dumps({"product": TEST_PRODUCT}), str(r.json()["embeddings"][0])))
            ids[key] = str(cid)
    await embed_doc.aclose()
    try:
        yield ids
    finally:
        with psycopg.connect(db_url, autocommit=True) as conn:
            conn.execute("delete from tutor.docs_source where id = any(%s)", (source_ids,))


async def _search(pool: AsyncConnectionPool, query: str, k: int = 3) -> list[Chunk]:
    return await PgHybridRetriever(pool, OllamaEmbedder()).search(query, k=k, products=[TEST_PRODUCT])


@pytest.mark.parametrize(("query", "expected"), [("42501", "rls"), ("statement_timeout", "timeout")])
async def test_exact_identifier_ranks_lexical_hit_first(
    pool: AsyncConnectionPool, fixture_chunks: dict[str, str], query: str, expected: str
) -> None:
    hits = await _search(pool, query)
    assert str(hits[0].chunk_id) == fixture_chunks[expected]


async def test_paraphrase_finds_rls_chunk_in_top3(pool: AsyncConnectionPool, fixture_chunks: dict[str, str]) -> None:
    hits = await _search(pool, "why does my insert say permission denied")
    assert fixture_chunks["rls"] in [str(h.chunk_id) for h in hits[:3]]


async def test_hits_carry_citation_fields(pool: AsyncConnectionPool, fixture_chunks: dict[str, str]) -> None:
    hit = (await _search(pool, "prepared statements transaction mode pooler"))[0]
    assert str(hit.chunk_id) == fixture_chunks["pooler"]
    assert hit.cite_url == "https://example.test/troubleshooting/supavisor-faq.md#transaction-mode"
    assert hit.tier == 1 and hit.score > 0


class ReverseReranker:
    def __init__(self) -> None:
        self.seen = 0

    async def rerank(self, query: str, chunks: list[Chunk], k: int) -> list[Chunk]:
        self.seen = len(chunks)
        return list(reversed(chunks))[:k]


async def test_reranker_sees_candidate_pool_and_cuts_to_k(
    pool: AsyncConnectionPool, fixture_chunks: dict[str, str]
) -> None:
    rr = ReverseReranker()
    products: Sequence[str] = [TEST_PRODUCT]
    hits = await PgHybridRetriever(pool, OllamaEmbedder(), rr).search("42501", k=1, products=products)
    assert rr.seen == 3  # pool of 30 requested, only 3 fixture rows exist (needs iterative scan)
    assert len(hits) == 1
