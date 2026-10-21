"""Offline tests for scripts/ingest_llms.py (no network, no DB)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ingest_llms as ing

INDEX = """# Supabase Docs
Full documentation: https://supabase.com/llms-full.txt

## Documentation
- [Auth](https://supabase.com/docs/guides/auth.md)
- [CLI](https://supabase.com/llms/cli.txt)
- [Dart](https://supabase.com/llms/dart.txt)
## Pricing
- https://supabase.com/pricing.md
## API and agent resources
- https://supabase.com/openapi.json
- https://mcp.supabase.com/mcp
"""

MD = """# Row Level Security
Intro paragraph about RLS.

## Policies
Policies are rules. """ + ("word " * 500) + """

```sql
create policy p on t for select using ((select auth.uid()) = user_id);
```

### Performance
Add an index on user_id.
"""


def test_parse_index_links_and_skips():
    urls = [u for u, _ in ing.parse_index(INDEX, "https://supabase.com/llms.txt")]
    assert "https://supabase.com/llms-full.txt" in urls
    assert "https://supabase.com/docs/guides/auth.md" in urls
    assert not any("openapi.json" in u or "mcp.supabase.com" in u for u in urls)


def test_profile_support_skips_mobile_sdks():
    urls = ing.parse_index(INDEX, "https://supabase.com/llms.txt")
    sel = [u for u, _ in ing.select(urls, "support", None)]
    assert not any(u.endswith("dart.txt") for u in sel)
    assert any(u.endswith("cli.txt") for u in sel)


def test_product_mapping():
    assert ing.product_of("https://supabase.com/docs/guides/auth.md") == "auth"
    assert ing.product_of("https://supabase.com/llms/cli.txt") == "cli"
    assert ing.product_of("https://supabase.com/pricing.md") == "pricing"
    assert ing.product_of("https://supabase.com/llms-full.txt") == "full"


def test_chunker_keeps_fences_and_heading_path():
    chunks = ing.chunk_markdown(MD, "database", "/docs/guides/database.md")
    assert chunks, "no chunks"
    assert all(c.heading_path.startswith("Row Level Security") for c in chunks)
    code_chunks = [c for c in chunks if "```sql" in c.content]
    assert code_chunks and all(c.content.count("```") % 2 == 0 for c in code_chunks)
    perf = [c for c in chunks if c.heading_path.endswith("Performance")]
    assert perf and perf[0].anchor == "performance"
    assert all(ing.approx_tokens(c.content) <= ing.MAX_TOKENS + 200 for c in chunks)
