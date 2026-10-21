"""prompt.py: block order, caching boundaries, persona retargeting, session state."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import get_args

import pytest
import yaml

from backend.tutor import prompt as p
from backend.tutor.ledger import LedgerEntry

ROOT = Path(__file__).resolve().parents[2]


def entry(topic: str, score: int, days_ago: int, evidence: str = "observed in lab 01") -> LedgerEntry:
    return LedgerEntry(topic=topic, phase="D", title=topic, score=score, evidence=evidence,
                       last_reviewed=datetime(2026, 10, 21, tzinfo=UTC) - timedelta(days=days_ago), next_review=None)


def test_system_is_one_cached_static_block() -> None:
    blocks = p.system_blocks(persona_on=True)
    assert len(blocks) == 1 and blocks[0]["cache_control"] == {"type": "ephemeral"}
    static = blocks[0]["text"]
    order = ["# SUPABASE & POSTGRESQL — KÄNGURU", "# PERSONA VOICE DETAIL", "# RUNTIME CONTRACT",
             "# TutorTurn schema", "# REFERENCE TUTORING PATH", "# CURRICULUM TOPIC SLUGS"]
    positions = [static.index(marker) for marker in order]
    assert positions == sorted(positions)
    assert all(static[pos - len(p.SEP):pos] == p.SEP for pos in positions[1:])  # each part starts after SEP
    assert "# SESSION STATE" not in static and "# MODE:" not in static


def test_turn_system_text_is_mode_then_state() -> None:
    text = p.turn_system_text(p.SessionState(mode="incident", objective="locks"))
    assert text.startswith("# MODE: incident")
    assert text.index(p.SEP) < text.index("# SESSION STATE")
    assert "- Objective: locks" in text


def test_system_does_not_depend_on_per_turn_state() -> None:
    # Append-only history: system must be byte-identical across turns of a session.
    assert p.system_blocks(True, "Saru") == p.system_blocks(True, "Saru")
    a = p.turn_system_text(p.SessionState(objective="RLS", ledger=[entry("rls-vs-grants", 1, 0)], first_turn=True))
    b = p.turn_system_text(p.SessionState(objective="locks", today=date(2027, 1, 1)))
    assert a != b


def test_persona_off_drops_persona_block_only() -> None:
    off = p.system_blocks(persona_on=False)
    assert "# PERSONA VOICE DETAIL" not in off[0]["text"]
    assert "# RUNTIME CONTRACT" in off[0]["text"]
    assert "Persona: off" in p.turn_system_text(p.SessionState(mode="neutral", persona_on=False))


def test_persona_is_retargeted_and_named() -> None:
    voice = p.persona_voice("Saru")
    assert "Machine Learning" not in voice and "Webentwicklung" not in voice
    assert "Supabase, SQL und PostgreSQL" in voice
    assert "{learner_name}" not in voice and "beim Saru" in voice
    assert voice.index("Subordinate to PRIORITY AND CONFLICT RESOLUTION") < voice.index("Du bist ein Känguru")


def test_persona_subject_change_is_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(p, "PERSONA_SUBJECT", p.re.compile("no such subject line"))
    with pytest.raises(ValueError, match="persona subject line"):
        p.persona_voice("x")


def test_all_curriculum_slugs_are_listed() -> None:
    phases = yaml.safe_load((ROOT / "docs" / "curriculum.yaml").read_text())["phases"]
    listing = p.topic_slugs()
    slugs = [s for spec in phases.values() for s in spec["topics"]]
    assert len(slugs) == 63
    assert all(s in listing for s in slugs)


@pytest.mark.parametrize("mode", get_args(p.Mode))
def test_every_mode_has_a_prompt_file(mode: p.Mode) -> None:
    assert p.mode_text(mode).startswith(f"# MODE: {mode}")


def test_session_block_ledger_summary_and_flags() -> None:
    ledger = [entry(f"t{i}", score=i % 6, days_ago=i) for i in range(14)]
    ledger.append(entry("long", 0, 30, evidence="x " * 200))
    text = p.session_block(p.SessionState(
        language="en", objective="trace a request", ledger=ledger, first_turn=True,
        active_lab=p.ActiveLab("01-rls-vs-grant", "RLS is broken", hints_used=2),
        still_wrong=["thought RLS runs before GRANT"], today=date(2026, 10, 21)))
    weakest = text.split("Mastery ledger, weakest 10")[1].split("Most recently reviewed:")[0]
    assert weakest.count("\n- ") == 10
    assert weakest.index("- long 0/5") < weakest.index("- t0 0/5")  # equal score: older review first
    assert "…" in weakest and len(max(weakest.splitlines(), key=len)) < 160
    recent = text.split("Most recently reviewed:")[1].split("Still wrong")[0]
    assert recent.strip().splitlines()[0].startswith("- t0 0/5 on 2026-10-21")
    assert "- Active lab: 01-rls-vs-grant — RLS is broken (hints used: 2)" in text
    assert "follow the FIRST TURN section" in text
    assert "Language: English" in text and "- Date: 2026-10-21" in text
    assert "- thought RLS runs before GRANT" in text


def test_empty_ledger_asks_for_scenario_assessment() -> None:
    assert "assess with a scenario" in p.session_block(p.SessionState())


@pytest.mark.parametrize(("step", "fragment"), [
    ("opening", "follow the FIRST TURN section exactly"),
    ("request_flow", "sequenceDiagram"),
    ("lab_handover", 'call lab_control with slug "01-rls-vs-grant" and action "install"'),
])
def test_onboarding_step_guidance(step: p.OnboardingStep, fragment: str) -> None:
    text = p.session_block(p.SessionState(onboarding=step, first_turn=True))
    assert "Onboarding step" in text and fragment in text
    assert text.count("FIRST TURN") <= 1  # the onboarding line replaces the generic first-turn line
