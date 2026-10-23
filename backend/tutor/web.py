"""Web search adapter (T2.4, ADR-007): one interface over sanctioned search APIs, with evidence tiers, dates and
redaction in both directions.

- Outbound: the query leaves this machine, so keys, JWTs, connection strings, e-mail addresses, IPs, UUIDs and
  Supabase project refs are removed first (`redact_query`). The tool result says what was removed.
- Tiers follow the master instructions' evidence hierarchy: 1 Supabase, 2 Supabase GitHub source and releases,
  3 PostgreSQL and other upstream primary docs, 4 community (also Supabase GitHub issues and discussions).
- Dates: the provider's page date when it has one; a result older than ~18 months is marked stale (and an
  undated one too, for version-sensitive reasons) so the tutor treats it as history, not current behaviour.
- Inbound: snippets are stripped of HTML, secrets are redacted, length is capped. Results stay untrusted data.

Providers: Brave Search and Tavily (adapted from opportunity-intelligence/src/oi/providers/search.py), a fixture
provider for tests and evals. Enabled with TUTOR_WEB_SEARCH=on plus a key.
"""
from __future__ import annotations

import html
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

from backend.tutor.guard import SECRET_PATTERNS

SNIPPET_CHARS = 400
MAX_RESULTS = 6
STALE_DAYS = 548  # ~18 months: older answers about versions, CLI syntax, limits or bugs are history
VERSION_SENSITIVE = {"pricing", "limits", "versions", "cli_syntax_changed", "current_bug"}


@dataclass(frozen=True)
class WebResult:
    url: str
    title: str
    snippet: str
    published: date | None = None


class WebSearch(Protocol):
    async def search(self, query: str) -> list[WebResult]: ...


class WebSearchError(RuntimeError):
    pass


# ----------------------------------------------------------------------------- tiers
UPSTREAM_DOCS = ("postgresql.org", "postgrest.org", "docs.deno.com", "deno.land", "docs.docker.com")
COMMUNITY_PATHS = re.compile(r"^/supabase/[^/]+/(issues|discussions|pull)(/|$)")


def source_tier(url: str) -> int:
    """Evidence tier by URL (master instructions, EVIDENCE HIERARCHY)."""
    parsed = urlparse(url)
    host, path = (parsed.hostname or "").lower(), parsed.path.lower()
    if host == "supabase.com" or host.endswith(".supabase.com"):
        return 4 if path.startswith("/contribute") else 1
    if host == "github.com" and path.startswith("/supabase/"):
        return 4 if COMMUNITY_PATHS.match(path) else 2  # issues and discussions are experiences, not source
    if any(host == d or host.endswith("." + d) for d in UPSTREAM_DOCS):
        return 3
    return 4


# ----------------------------------------------------------------------------- redaction
@dataclass(frozen=True)
class Redaction:
    query: str
    removed: tuple[str, ...] = ()  # kinds, e.g. ("jwt", "email")


QUERY_REDACTIONS: list[tuple[str, re.Pattern[str], str]] = [
    ("connection string", re.compile(r"postgres(?:ql)?://\S+", re.IGNORECASE), "postgres connection string"),
    ("jwt", re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"), ""),
    ("api key", re.compile(r"\b(?:sb_(?:secret|publishable)_[A-Za-z0-9_-]{8,}|sk-(?:ant-|proj-)?[A-Za-z0-9_-]{16,})"), ""),
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b"), ""),
    ("project ref", re.compile(r"\b(db\.)?[a-z0-9]{20}\.(supabase\.(?:co|in))\b", re.IGNORECASE), r"\1<project>.\2"),
    ("project ref", re.compile(r"\bpostgres\.[a-z0-9]{20}\b"), "postgres.<project>"),  # pooler user name
    ("uuid", re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE), ""),
    ("ip address", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), ""),
    ("token", re.compile(r"\b[A-Za-z0-9_-]{40,}\b"), ""),
]


def redact_query(query: str, extra_secrets: list[str] | None = None) -> Redaction:
    """Remove what must not reach a search provider; keep the technical words that make the query useful."""
    removed: list[str] = []
    for secret in extra_secrets or []:  # e.g. what the learner pasted this turn
        if secret and secret in query:
            query = query.replace(secret, " ")
            removed.append("pasted secret")
    for kind, pattern, replacement in QUERY_REDACTIONS:
        query, n = pattern.subn(replacement, query)
        removed += [kind] * n
    return Redaction(re.sub(r"\s+", " ", query).strip(), tuple(dict.fromkeys(removed)))


TAG = re.compile(r"<[^>]+>")


def clean_snippet(text: str) -> str:
    text = html.unescape(TAG.sub("", text))
    for pattern in SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= SNIPPET_CHARS else text[:SNIPPET_CHARS].rsplit(" ", 1)[0] + " …"


# ----------------------------------------------------------------------------- annotation
@dataclass(frozen=True)
class Annotated:
    result: WebResult
    tier: int
    age_days: int | None
    stale: bool


def annotate(results: list[WebResult], reason: str, today: date | None = None) -> list[Annotated]:
    """Tier, age and staleness per result; official tiers first, provider order within a tier."""
    today = today or date.today()
    out = []
    for r in results[:MAX_RESULTS]:
        age = (today - r.published).days if r.published else None
        # Old is old for any question; undated only matters where versions and current behaviour are the point.
        stale = (age is not None and age > STALE_DAYS) or (age is None and reason in VERSION_SENSITIVE)
        out.append(Annotated(WebResult(r.url, clean_snippet(r.title), clean_snippet(r.snippet), r.published),
                             source_tier(r.url), age, stale))
    return sorted(out, key=lambda a: a.tier)


# ----------------------------------------------------------------------------- providers
def _parse_date(value: Any) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value).date()  # 3.11+ parses a trailing Z
    except ValueError:
        return None


class BraveSearch:
    """Brave Search API. `page_age` is the page's own date when Brave knows it."""
    name = "brave"
    ENDPOINT = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, api_key: str, client: httpx.AsyncClient) -> None:
        self.key = api_key
        self.client = client

    async def search(self, query: str) -> list[WebResult]:
        try:
            res = await self.client.get(self.ENDPOINT, params={"q": query, "count": MAX_RESULTS}, timeout=20,
                                        headers={"X-Subscription-Token": self.key, "Accept": "application/json"})
        except httpx.HTTPError as e:
            raise WebSearchError(f"brave: {type(e).__name__}") from e
        if res.status_code >= 400:
            raise WebSearchError(f"brave HTTP {res.status_code}")
        hits = ((res.json().get("web") or {}).get("results")) or []
        return [WebResult(str(h["url"]), str(h.get("title", "")), str(h.get("description", "")),
                          _parse_date(h.get("page_age"))) for h in hits if h.get("url")]


class TavilySearch:
    """Tavily search API (basic depth = one credit). `published_date` is only sometimes present."""
    name = "tavily"
    ENDPOINT = "https://api.tavily.com/search"

    def __init__(self, api_key: str, client: httpx.AsyncClient) -> None:
        self.key = api_key
        self.client = client

    async def search(self, query: str) -> list[WebResult]:
        try:
            res = await self.client.post(self.ENDPOINT, timeout=20, headers={"Authorization": f"Bearer {self.key}"},
                                         json={"query": query, "max_results": MAX_RESULTS, "search_depth": "basic"})
        except httpx.HTTPError as e:
            raise WebSearchError(f"tavily: {type(e).__name__}") from e
        if res.status_code >= 400:
            raise WebSearchError(f"tavily HTTP {res.status_code}")
        return [WebResult(str(h["url"]), str(h.get("title", "")), str(h.get("content", "")),
                          _parse_date(h.get("published_date"))) for h in res.json().get("results") or []
                if h.get("url")]


@dataclass
class FixtureSearch:
    """Offline provider for tests and evals: the first fixture whose key appears in the query wins."""
    name = "fixture"
    results: dict[str, list[WebResult]] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    async def search(self, query: str) -> list[WebResult]:
        self.calls.append(query)
        q = query.lower()
        return next((hits for key, hits in self.results.items() if key.lower() in q), [])


def web_from_env(client: httpx.AsyncClient | None = None) -> BraveSearch | TavilySearch | None:
    """TUTOR_WEB_SEARCH=on plus BRAVE_SEARCH_API_KEY or TAVILY_API_KEY (TUTOR_WEB_PROVIDER picks one)."""
    if os.environ.get("TUTOR_WEB_SEARCH", "off") != "on":
        return None
    prefer = os.environ.get("TUTOR_WEB_PROVIDER", "")
    if prefer not in ("", "brave", "tavily"):
        raise ValueError(f"TUTOR_WEB_PROVIDER={prefer!r}: brave | tavily")
    keys = {"brave": os.environ.get("BRAVE_SEARCH_API_KEY", ""), "tavily": os.environ.get("TAVILY_API_KEY", "")}
    for name in [prefer] if prefer else ["brave", "tavily"]:
        if keys[name]:
            http = client or httpx.AsyncClient()
            return BraveSearch(keys[name], http) if name == "brave" else TavilySearch(keys[name], http)
    return None
