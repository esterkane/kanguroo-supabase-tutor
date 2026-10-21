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


FULL = """# Supabase

## Pricing

# Supabase Pricing

Plans.

---

# Row Level Security

```yaml
---
key: value
```

Policies text.

---

# Only In Full

Body.
"""


def test_split_pages_uses_title_after_separator() -> None:
    pages = ing.split_pages(FULL)
    assert [ing.page_title(p) for p in pages] == ["supabase", "row level security", "only in full"]
    assert "key: value" in pages[1]  # `---` inside YAML is not a separator


def test_drop_duplicate_pages_keeps_unmatched() -> None:
    text, dropped = ing.drop_duplicate_pages(FULL, {"row level security"})
    assert dropped == 1
    assert "Policies text" not in text and "Only In Full" in text


def test_canonical_md() -> None:
    assert ing.canonical_md("https://supabase.com/docs/guides/auth/passwords#x") == \
        "https://supabase.com/docs/guides/auth/passwords.md"
    assert ing.canonical_md("https://supabase.com/docs/guides/auth.md") == "https://supabase.com/docs/guides/auth.md"
    assert ing.canonical_md("https://supabase.com/docs/guides/img/diagram.png") is None


def test_discover_follows_kb_links_only_from_kb() -> None:
    guide = ing.Doc(url="https://supabase.com/docs/guides/auth.md", tier=1, product="auth",
                    text="[a](https://supabase.com/docs/guides/auth/jwts) [k](https://supabase.com/kb/x.md)")
    kb = ing.Doc(url="https://supabase.com/kb/sitemap.md", tier=1, product="kb",
                 text="- [T](https://supabase.com/kb/troubleshooting/high-cpu.md)")
    assert ing.discover([guide, kb]) == [
        "https://supabase.com/docs/guides/auth/jwts.md",
        "https://supabase.com/kb/troubleshooting/high-cpu.md",
    ]


def test_discover_skips_kb_copy_of_docs_troubleshooting() -> None:
    guide = ing.Doc(url="https://supabase.com/docs/guides/troubleshooting.md", tier=1, product="troubleshooting",
                    text="[x](https://supabase.com/docs/guides/troubleshooting/high-cpu.md)")
    kb = ing.Doc(url="https://supabase.com/kb/sitemap.md", tier=1, product="kb",
                 text="[x](https://supabase.com/kb/troubleshooting/high-cpu.md) [y](https://supabase.com/kb/troubleshooting/only-kb.md)")
    assert ing.discover([guide, kb]) == [
        "https://supabase.com/docs/guides/troubleshooting/high-cpu.md",
        "https://supabase.com/kb/troubleshooting/only-kb.md",
    ]
