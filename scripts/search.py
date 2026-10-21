#!/usr/bin/env python3
"""Ask the ingested corpus a question via tutor.hybrid_search (debugging aid for retrieval).

Embeds the query with the same provider as the ingest (nomic `search_query:` prefix for Ollama).

Usage:
  uv run python scripts/search.py "permission denied for table 42501"
  uv run python scripts/search.py -k 3 --product auth "jwt expiry"
"""
from __future__ import annotations

import argparse
import os

import httpx
import psycopg
from db import admin_url


def embed_query(text: str) -> list[float]:
    provider = os.environ.get("EMBEDDINGS_PROVIDER", "ollama")
    if provider != "ollama":
        raise SystemExit("only EMBEDDINGS_PROVIDER=ollama is wired up here")
    url = os.environ.get("OLLAMA_URL", "http://localhost:11434") + "/api/embed"
    r = httpx.post(url, json={"model": "nomic-embed-text", "input": [f"search_query: {text}"]}, timeout=60)
    r.raise_for_status()
    return r.json()["embeddings"][0]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("query")
    ap.add_argument("-k", type=int, default=5, help="results to return")
    ap.add_argument("--product", action="append", help="restrict to meta.product (repeatable)")
    args = ap.parse_args()

    emb = str(embed_query(args.query))
    with psycopg.connect(admin_url()) as conn:
        rows = conn.execute(
            "select score, url, anchor, heading_path, left(regexp_replace(content, '\\s+', ' ', 'g'), 160)"
            " from tutor.hybrid_search(%s, %s::extensions.vector, %s, %s)",
            (args.query, emb, args.k, args.product),
        ).fetchall()
    for score, url, anchor, path, snippet in rows:
        print(f"{score:.4f}  {url}{'#' + anchor if anchor else ''}\n        {path}\n        {snippet}\n")


if __name__ == "__main__":
    main()
