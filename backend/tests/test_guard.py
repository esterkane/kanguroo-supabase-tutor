"""guard.py: each invariant fires on a violation and stays quiet on the compliant version."""
from __future__ import annotations

import json
from typing import Any

import pytest

from backend.tests.test_orchestrator import FakeClient, FakeStream, message, run, text_reply
from backend.tutor import guard as g
from backend.tutor import orchestrator as o
from backend.tutor.schemas import TutorTurn

SRC = "https://supabase.com/docs/guides/database/postgres/row-level-security.md"
CTX = g.GuardContext(sources={SRC: 1, "https://stackoverflow.com/q/1": 4})
Q = "Welche Kontrolle prüfst du zuerst?"


def turn(text: str = f"GRANT und RLS sind getrennt [1].\n\n{Q}", **kw: Any) -> TutorTurn:
    base: dict[str, Any] = {
        "mode": "lesson", "language": "de", "persona_on": True, "speech": "Kurz gesagt. " + Q, "text": text,
        "next_question": Q, "citations": [{"n": 1, "url": SRC + "#policies", "title": "RLS", "tier": 1}]}
    return TutorTurn.model_validate(base | kw)


def codes(t: TutorTurn, ctx: g.GuardContext = CTX) -> dict[str, str]:
    return {f.code: f.severity for f in g.check(t, ctx)}


def test_compliant_turn_is_clean() -> None:
    assert g.check(turn(), CTX) == []


# ----------------------------------------------------------------------------- questions
def test_question_rules() -> None:
    assert codes(turn(next_question=None))["NO_QUESTION"] == "block"
    assert "NO_QUESTION" not in codes(turn(mode="incident", next_question=None,
                                           incident={"symptom": "slow"}))
    assert codes(turn(next_question="A? Oder B?"))["MULTI_QUESTION"] == "block"
    many = f"Warum? Wieso? Weshalb?\n\n{Q} [1]"
    assert codes(turn(text=many))["MULTI_QUESTION"] == "warn"
    assert codes(turn(text="GRANT und RLS [1]."))["QUESTION_NOT_IN_TEXT"] == "warn"
    reworded = turn(next_question="Welche der beiden Kontrollen, GRANT oder RLS-Policy, prüfst du zuerst?",
                    text="GRANT und RLS [1].\n\nWelche der beiden Kontrollen, GRANT (Tabellenprivileg) oder "
                         "RLS-Policy, würdest du als Erstes prüfen, und warum? Ein Satz genügt.")
    assert "QUESTION_NOT_IN_TEXT" not in codes(reworded)


# ----------------------------------------------------------------------------- citations
def test_citation_rules() -> None:
    assert codes(turn(citations=[]))["CITATION_MARKER_MISSING"] == "block"
    extra = [{"n": 1, "url": SRC, "title": "RLS", "tier": 1}, {"n": 2, "url": SRC, "title": "RLS", "tier": 1}]
    assert codes(turn(citations=extra))["CITATION_UNUSED"] == "warn"
    invented = [{"n": 1, "url": "https://supabase.com/docs/made-up", "title": "x", "tier": 1}]
    assert codes(turn(citations=invented))["CITATION_NOT_FROM_TOOL"] == "block"
    inflated = [{"n": 1, "url": "https://stackoverflow.com/q/1", "title": "x", "tier": 1}]
    found = codes(turn(citations=inflated))
    assert found["CITATION_TIER_INFLATED"] == "block" and found["COMMUNITY_UNLABELLED"] == "block"
    labelled = turn(text=f"Ein Community-Bericht (tier 4) beschreibt das [1].\n\n{Q}",
                    citations=[{"n": 1, "url": "https://stackoverflow.com/q/1", "title": "x", "tier": 4}])
    assert g.check(labelled, CTX) == []


def test_collect_sources_reads_search_and_web_results() -> None:
    msgs: list[dict[str, Any]] = [
        {"role": "user", "content": "Hallo"},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "a", "content": json.dumps(
                {"results": [{"url": SRC + "#policies", "tier": 1}]})},
            {"type": "tool_result", "tool_use_id": "b", "content":
                '<untrusted_source url="https://github.com/supabase/cli/issues/1?a=1&amp;b=2" tier="2" date="x">'},
            {"type": "tool_result", "tool_use_id": "c", "is_error": True, "content": json.dumps(
                {"results": [{"url": "https://evil.test", "tier": 1}]})},
        ]},
    ]
    assert g.collect_sources(msgs) == {SRC: 1, "https://github.com/supabase/cli/issues/1?a=1&b=2": 2}


# ----------------------------------------------------------------------------- claims
@pytest.mark.parametrize("sentence", [
    "Der Pro plan kostet $25 im Monat.", "Supabase läuft auf Postgres 17.", "Das Limit liegt bei bis zu 500 MB.",
])
def test_uncited_claims_block(sentence: str) -> None:
    assert codes(turn(text=f"{sentence}\n\n{Q}", citations=[]))["UNCITED_CLAIM"] == "block"


@pytest.mark.parametrize("sentence", [
    "Der Pro plan kostet $25 im Monat [1].", "Supabase läuft auf Postgres 17 (unverified — verify live).",
    "Fiktive Zahlen: 200,000 calls at 45 ms.", "For example, the composite index helps here [1].",
])
def test_cited_or_labelled_claims_pass(sentence: str) -> None:
    assert "UNCITED_CLAIM" not in codes(turn(text=f"{sentence}\n\n{Q}"))


def test_claims_inside_code_and_tables_are_ignored() -> None:
    text = f"Siehe Tabelle [1].\n\n| Plan | Preis |\n|---|---|\n| Pro | $25 |\n\n```sql\nselect version();\n```\n\n{Q}"
    assert "UNCITED_CLAIM" not in codes(turn(text=text))


# ----------------------------------------------------------------------------- secrets
@pytest.mark.parametrize("secret", [
    "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoic2VydmljZV9yb2xlIn0.abcdefghijklmnop",
    "sb_secret_N7UND0UgjKTVK-Uodkm0Hg_xSvEMPvz",
    "postgresql://postgres.abc:Hunter2Secret!@aws-0-eu.pooler.supabase.com:6543/postgres",
])
def test_secrets_block_and_get_redacted(secret: str) -> None:
    t = turn(text=f"Nimm `{secret}` [1].\n\n{Q}")
    assert codes(t)["SECRET_LEAK"] == "block"
    redacted = g.redact_secrets(t)
    assert "[REDACTED]" in redacted.text and "Hunter2" not in redacted.text and "N7UND0" not in redacted.text


@pytest.mark.parametrize("ok", [
    "postgresql://postgres:postgres@127.0.0.1:54322/postgres",
    "postgresql://postgres.[ref]:[YOUR-PASSWORD]@aws-0-eu.pooler.supabase.com:6543/postgres",
    "Der service_role Key bleibt auf dem Server.",
])
def test_placeholders_and_mentions_are_fine(ok: str) -> None:
    assert "SECRET_LEAK" not in codes(turn(text=f"{ok} [1]\n\n{Q}"))


# ----------------------------------------------------------------------------- SQL
@pytest.mark.parametrize("sql", [
    "drop table public.orders;", "truncate lab01.orders;", "delete from public.orders;",
    "update public.orders set total = 0;", "alter table public.orders disable row level security;",
])
def test_destructive_sql_needs_risk_block(sql: str) -> None:
    bare = f"So [1]:\n\n```sql\n{sql}\n```\n\n{Q}"
    assert codes(turn(text=bare))["DESTRUCTIVE_SQL_UNFLAGGED"] == "block"
    flagged = f"> ⚠ Risk: data loss; lab only. Rollback: reinstall the lab [1].\n\n```sql\n{sql}\n```\n\n{Q}"
    assert "DESTRUCTIVE_SQL_UNFLAGGED" not in codes(turn(text=flagged))


@pytest.mark.parametrize("sql", [
    "delete from public.orders where id = 1;", "update public.orders set total = 0 where id = 1;",
    "select * from pg_policies;", "create index on public.orders (customer_id);",
])
def test_safe_sql_passes(sql: str) -> None:
    assert "DESTRUCTIVE_SQL_UNFLAGGED" not in codes(turn(text=f"So [1]:\n\n```sql\n{sql}\n```\n\n{Q}"))


def test_persona_in_code_warns() -> None:
    text = f"So [1]:\n\n```sql\n-- Kleinkünstler, hier:\nselect 1;\n```\n\n{Q}"
    assert codes(turn(text=text))["PERSONA_IN_CODE"] == "warn"


# ----------------------------------------------------------------------------- incident, speech, execution
def test_incident_speech_and_execution_rules() -> None:
    assert codes(turn(mode="incident", next_question=None))["INCIDENT_MODEL_MISSING"] == "block"
    assert codes(turn(speech=" ".join(["wort"] * 61)))["SPEECH_TOO_LONG"] == "block"
    assert codes(turn(speech="Lies https://supabase.com nach."))["SPEECH_HAS_MARKUP"] == "block"
    claim = turn(text=f"Ich habe das gerade ausgeführt und es klappt [1].\n\n{Q}")
    assert codes(claim)["CLAIMED_EXECUTION"] == "block"
    assert "CLAIMED_EXECUTION" not in codes(claim, g.GuardContext(sources=CTX.sources, ran_lab_sql=True))


def test_repair_message_lists_only_blocking_findings() -> None:
    msg = g.repair_message(g.check(turn(next_question=None, citations=[]), CTX))
    assert msg.startswith("[app message, not from the learner]")
    assert "NO_QUESTION" in msg and "CITATION_MARKER_MISSING" in msg and "QUESTION_NOT_IN_TEXT" not in msg


# ----------------------------------------------------------------------------- orchestrator integration
async def test_blocking_finding_triggers_one_rewrite() -> None:
    uncited = text_reply("Der Pro plan kostet $25 im Monat.")
    fixed = text_reply("Der Preis steht auf der Pricing-Seite (unverified — verify live).")
    client = FakeClient([uncited, fixed])
    events = await run(client)
    rewrites = [e for e in events if isinstance(e, o.Rewrite)]
    assert [r.codes for r in rewrites] == [["UNCITED_CLAIM"]]
    final = events[-1]
    assert isinstance(final, o.Final) and final.turn.guard_flags == []
    assert final.turn.text.startswith("Der Preis steht")
    repair = client.requests[1]["messages"][-1]
    assert repair["role"] == "user" and "UNCITED_CLAIM" in repair["content"]


async def test_second_violation_is_flagged_and_secrets_redacted() -> None:
    leak = "Nimm sb_secret_N7UND0UgjKTVK-Uodkm0Hg_xSvEMPvz."
    client = FakeClient([text_reply(leak), text_reply(leak)])
    final = (await run(client))[-1]
    assert isinstance(final, o.Final)
    assert "SECRET_LEAK" in final.turn.guard_flags
    assert "sb_secret_" not in final.turn.text and "[REDACTED]" in final.turn.text
    assert len(client.requests) == 2  # exactly one rewrite attempt


async def test_refusal_and_unstructured_turns_are_redacted_too() -> None:
    raw = "Nimm sb_secret_N7UND0UgjKTVK-Uodkm0Hg_xSvEMPvz"
    client = FakeClient([FakeStream([raw], message([{"type": "text", "text": raw}])),
                         FakeStream([raw], message([{"type": "text", "text": raw}]))])
    final = (await run(client))[-1]
    assert isinstance(final, o.Final) and final.turn.guard_flags == ["unstructured"]
    assert "sb_secret_" not in final.turn.text
