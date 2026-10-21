---
name: llms-txt-ingest
description: Fetch the Supabase docs corpus from https://supabase.com/llms.txt (llms-full.txt, llms/*.txt, guides/*.md, pricing.md, kb sitemap), chunk by headings, embed, and upsert into tutor.docs_chunk with freshness metadata. Use for scripts/ingest_llms.py, refresh jobs, chunking rules.
---

# Ingesting the Supabase docs corpus

## Index structure (verified 2026-10-21)
`https://supabase.com/llms.txt` is a ~58-line index. Its intro links
`https://supabase.com/llms-full.txt` (the whole docs in one file). Sections:
- `## Documentation` → `https://supabase.com/docs/guides/<area>.md` (ai, api, auth, cron,
  database, deployment, functions, getting-started, graphql, integrations,
  local-development, observability, platform, queues, realtime, resources, security,
  self-hosting, storage) and reference sub-files `https://supabase.com/llms/{js,dart,swift,kotlin,python,csharp,server,cli,api}.txt`
- Knowledge base: `https://supabase.com/kb/sitemap.md`
- `## Pricing` → `https://supabase.com/pricing.md`
- `## Product overviews` → `index.md, database.md, auth.md, storage.md, realtime.md, edge-functions.md, modules/{cron,queues,vector}.md`
- `## API and agent resources` → `openapi.json`, MCP server `https://mcp.supabase.com/mcp`

Re-parse the index on every run; do not hardcode the list. Anything that disappears from
the index is marked `status='retired'`, not deleted (old citations must still resolve).

## Source selection (default profile `support`)
Ingest: `llms-full.txt`, `llms/cli.txt`, `llms/js.txt`, `llms/server.txt`, `llms/api.txt`,
`llms/python.txt`, all `docs/guides/*.md`, `pricing.md`, product overviews, and the KB
sitemap's linked pages (depth 1, same host). Skip dart/swift/kotlin/csharp unless
`--profile all`.

Depth-1 expansion (default; `--no-expand` to skip): every `https://supabase.com/docs/guides/...`
link in the seed docs (incl. `llms-full.txt`) is fetched as its `.md` twin, and every KB link in
the KB sitemap (`/kb/sitemap.md` 308-redirects to `/kb/markdown/sitemap.md`). As of 2026-10-21
that is ~974 extra pages; the guide index pages themselves are only tables of contents.

`llms-full.txt` has no per-page URLs, so pages fetched under their own URL are canonical:
split it on `---` lines followed by a `# Title` line (fence tracking fails on the 7 MB file),
drop pages whose H1 matches a fetched page, and ingest only the rest (~143 pages).
Index entries must all succeed (exit 1); dead links inside the docs are reported, not fatal.

## Fetching
- `httpx` with a 30 s timeout, `User-Agent: kaenguru-tutor-ingest/0.1 (+local dev)`,
  ETag/`If-None-Match` + content hash; skip unchanged documents.
- Rate-limit politely: ≤4 concurrent, 200 ms between requests to the same host.
- Store raw bytes under `data/corpus/<sha256>.md` (gitignored) for reproducible re-chunking.

## Chunking
- Split on Markdown headings (`#`, `##`, `###`); target 400–900 tokens, overlap 80 tokens
  by carrying the last paragraph forward. Never split inside a fenced code block or a table.
- `heading_path` = `H1 > H2 > H3`; `anchor` = GitHub-style slug of the last heading.
- Keep a `meta` JSON: `{"source_file": ..., "lang": "sql|ts|bash|...", "has_code": bool,
  "product": "auth|database|realtime|storage|functions|cli|platform|pricing|kb|other"}`
  derived from the URL path. `product` powers `source_filter` in `search_docs`.
- Prepend `heading_path` to the text that is embedded (not to `content`) to improve recall.

## Embeddings
- `EMBEDDINGS_PROVIDER=ollama` → `nomic-embed-text` (768d) via `http://localhost:11434/api/embeddings`,
  prefix `search_document: ` for chunks and `search_query: ` for queries (nomic convention).
- `EMBEDDINGS_PROVIDER=openai` → `text-embedding-3-small` with `dimensions=768` so the column
  type never changes. Record provider+model on `docs_source.embedding_model`; refuse to mix
  models in one corpus version (`--corpus-version` bumps and re-embeds everything).

## Upsert
`insert ... on conflict (source_id, ord) do update` within one transaction per source;
`docs_source.fetched_at = now()` only after all chunks committed. Then
`analyze tutor.docs_chunk;`.

## Script contract (`scripts/ingest_llms.py`)
```
--index URL            default https://supabase.com/llms.txt
--profile support|all  default support
--dry-run              fetch+chunk, print stats, no DB writes
--only <url-substring> ingest one document
--corpus-version N     force re-embed
--limit N              first N docs (for tests)
```
Exit non-zero if any Tier-1 source failed; print a table: url, status, chunks, changed.

## Refresh
`make refresh` runs the script. Phase 1.12 adds a weekly `pg_cron` job calling
FastAPI `/internal/refresh` via `pg_net` (local only; guarded by a shared token in `.env`).
