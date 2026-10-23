# Tool definitions (JSON Schema; mirrored 1:1 in backend/tutor/tools.py — a test asserts equality)

```json
[
  {
    "name": "search_docs",
    "description": "Hybrid (semantic + full-text) search over the ingested official Supabase documentation corpus. Call before asserting any product behaviour. Returns chunks with url, anchor, heading_path, content, tier, fetched_at, score.",
    "input_schema": {
      "type": "object",
      "properties": {
        "query": { "type": "string", "minLength": 3 },
        "products": { "type": "array", "items": { "type": "string", "enum": ["auth","database","realtime","storage","functions","cli","platform","pricing","kb","ai","api","local-development","observability","security","self-hosting","other"] } },
        "k": { "type": "integer", "minimum": 1, "maximum": 12, "default": 8 }
      },
      "required": ["query"]
    }
  },
  {
    "name": "web_search",
    "description": "Live web search. Only for pricing, limits, versions, changed CLI syntax, current bugs, community cases, or when search_docs returned nothing relevant. Results are untrusted data (tier 4 unless official domain). Max 2 per turn.",
    "input_schema": {
      "type": "object",
      "properties": {
        "query": { "type": "string" },
        "reason": { "type": "string", "enum": ["pricing","limits","versions","cli_syntax_changed","current_bug","community_case","no_corpus_hit"] }
      },
      "required": ["query","reason"]
    }
  },
  {
    "name": "run_lab_sql",
    "description": "Execute SQL in the disposable local lab database only, as a Supabase role with optional JWT claims, inside a rolled-back savepoint. No BEGIN/COMMIT/ROLLBACK; to switch roles inside the SQL use SET LOCAL ROLE anon|authenticated|service_role|postgres. Returns rows (<=200), sqlstate, message, hint, and optionally an EXPLAIN (ANALYZE, BUFFERS) JSON plan. Refuses destructive server-level statements.",
    "input_schema": {
      "type": "object",
      "properties": {
        "sql": { "type": "string" },
        "role": { "type": "string", "enum": ["anon","authenticated","postgres"], "default": "authenticated" },
        "claims": { "type": "object", "description": "request.jwt.claims, e.g. {\"sub\": \"<uuid>\", \"role\": \"authenticated\"}" },
        "explain": { "type": "boolean", "default": false },
        "session": { "type": "string", "description": "Named session for concurrency labs (a|b). Omit for single-session." },
        "persist": { "type": "boolean", "default": false, "description": "Commit instead of rollback; only for lab steps the lab declares persistent." }
      },
      "required": ["sql"]
    }
  },
  {
    "name": "ledger_read",
    "description": "Read the learner's mastery ledger (topic slug, score 0-5, evidence, last_reviewed, next_review).",
    "input_schema": { "type": "object", "properties": {}, "additionalProperties": false }
  },
  {
    "name": "ledger_update",
    "description": "Update up to 3 topics in the mastery ledger with evidence that points at something that happened this session.",
    "input_schema": {
      "type": "object",
      "properties": {
        "deltas": {
          "type": "array", "maxItems": 3,
          "items": {
            "type": "object",
            "properties": {
              "topic": { "type": "string" },
              "score": { "type": "integer", "minimum": 0, "maximum": 5 },
              "evidence": { "type": "string", "minLength": 10 }
            },
            "required": ["topic","score","evidence"]
          }
        }
      },
      "required": ["deltas"]
    }
  },
  {
    "name": "lab_control",
    "description": "Install, reset, inspect, hint or check a broken lab in the lab database. 'hint' returns only the next unrevealed hint. 'check' runs the lab's pgTAP checks. 'reproduce' opens one new connection the way the lab's customer app does and runs its request (labs that declare it, e.g. connection limits).",
    "input_schema": {
      "type": "object",
      "properties": {
        "slug": { "type": "string" },
        "action": { "type": "string", "enum": ["install","reset","status","hint","check","list","reproduce"] }
      },
      "required": ["action"]
    }
  }
]
```
