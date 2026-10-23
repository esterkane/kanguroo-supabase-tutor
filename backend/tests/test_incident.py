"""Incident model merging (T2.2): partial model updates, learner edits win, ordered gaps, prompt block."""
from __future__ import annotations

import pytest

from backend.tutor.incident import (
    IncidentState,
    learner_edit,
    looks_like_customer_problem,
    merge,
    missing,
    prompt_block,
)
from backend.tutor.prompt import SessionState, session_block
from backend.tutor.schemas import Hypothesis, Incident


def test_partial_updates_accumulate_and_evidence_is_deduplicated() -> None:
    state, changed = merge(IncidentState(), Incident(symptom="API slow since yesterday", evidence=["CPU 91%"]))
    assert changed == ["symptom", "evidence"]
    state, changed = merge(state, Incident(scope="all projects of one org", evidence=["cpu 91% ", "85/200 conns"]))
    assert changed == ["scope", "evidence"]
    assert state.model.symptom == "API slow since yesterday"  # null kept the field
    assert state.model.evidence == ["CPU 91%", "85/200 conns"]
    assert state.sources["symptom"] == state.sources["evidence:1"] == "tutor"


def test_placeholders_are_not_knowledge() -> None:
    state, changed = merge(IncidentState(), Incident(scope="Unknown: which endpoints", environment="unbekannt",
                                                     expected="Sessions persist", evidence=["n/a", "CPU 91%"]))
    assert changed == ["expected", "evidence"] and state.model.scope is None and state.model.evidence == ["CPU 91%"]
    assert missing(state)[:2] == ["symptom", "scope"]


def test_hypotheses_are_replaced_as_a_ranked_list_and_renumbered() -> None:
    state, _ = merge(IncidentState(), Incident(hypotheses=[Hypothesis(h="seq scan", rank=1)]))
    state, changed = merge(state, Incident(hypotheses=[
        Hypothesis(h="missing index", rank=3, test="EXPLAIN ANALYZE", status="supported"),
        Hypothesis(h="seq scan", rank=2, status="falsified")]))
    assert changed == ["hypotheses"]
    assert [(h.rank, h.h, h.status) for h in state.model.hypotheses] == [
        (1, "seq scan", "falsified"), (2, "missing index", "supported")]


def test_the_tutor_never_overwrites_a_learner_value_but_records_the_conflict() -> None:
    state = learner_edit(IncidentState(), "root_cause", "RLS policy slow")
    state, changed = merge(state, Incident(root_cause="missing index on orders.customer_id"))
    assert changed == []
    assert state.model.root_cause == "RLS policy slow" and state.sources["root_cause"] == "learner"
    assert [(c.field, c.tutor) for c in state.conflicts] == [("root_cause", "missing index on orders.customer_id")]
    state, _ = merge(state, Incident(root_cause="missing index on orders.customer_id"))
    assert len(state.conflicts) == 1  # the same proposal is not recorded twice
    state = learner_edit(state, "root_cause", None)  # clearing hands the field back to the tutor
    assert "root_cause" not in state.sources and state.conflicts == []
    state, changed = merge(state, Incident(root_cause="missing index on orders.customer_id"))
    assert changed == ["root_cause"]


def test_learner_evidence_edits_keep_sources_aligned() -> None:
    state, _ = merge(IncidentState(), Incident(evidence=["a", "b"]))
    state = learner_edit(state, "evidence", "c from the learner")
    state = learner_edit(state, "evidence", None, index=0)
    assert state.model.evidence == ["b", "c from the learner"]
    assert (state.sources["evidence:0"], state.sources["evidence:1"]) == ("tutor", "learner")
    assert "evidence:2" not in state.sources


def test_missing_orders_evidence_gathering_before_cause_and_fix() -> None:
    assert missing(IncidentState())[:7] == ["symptom", "expected", "scope", "timeline", "environment", "evidence",
                                            "hypotheses"]
    state, _ = merge(IncidentState(), Incident(symptom="x", expected="y", scope="z", timeline="t", environment="e"))
    assert missing(state)[0] == "evidence"


def test_prompt_block_marks_learner_fields_conflicts_and_gaps() -> None:
    state = learner_edit(IncidentState(), "symptom", "42501 on insert")
    state, _ = merge(state, Incident(symptom="permission denied", evidence=["SQLSTATE 42501"]))
    block = prompt_block(state)
    assert "- SYMPTOM [learner]: 42501 on insert" in block
    assert "- EVIDENCE 1: SQLSTATE 42501" in block
    assert 'CONFLICT on symptom' in block
    assert "- Missing: expected, scope, timeline, environment, hypotheses" in block


def test_session_block_carries_the_incident_model_in_incident_mode() -> None:
    assert "Incident model so far" not in session_block(SessionState())
    empty = session_block(SessionState(mode="incident"))
    assert "Incident model so far" in empty and "- Missing: symptom, expected" in empty
    state, _ = merge(IncidentState(), Incident(symptom="slow"))
    assert "- SYMPTOM: slow" in session_block(SessionState(mode="lesson", incident=state))


REPORTS = [
    "Supabase ist seit gestern langsam.",
    "Unsere Nutzer werden zufällig ausgeloggt.",
    "Die Migration läuft lokal, aber nicht auf dem gehosteten Projekt.",
    "Realtime updates stopped arriving in our dashboard this morning.",
    "Edge Function returns 500 for every request since this morning.",
    "Kunde meldet: Inserts in orders schlagen mit 42501 permission denied fehl.",
    "Warum bekomme ich 42501 beim Insert in meine Tabelle?",
]
NOT_REPORTS = [
    "Hallo", "GRANT", "Klar", "Hallo, ich möchte Supabase Support lernen",
    "Was ist der Unterschied zwischen GRANT und RLS?", "Was bedeutet SQLSTATE 42501?",
    "How does the connection pooler work?", "Ich habe OrbStack und Node 22", "Zeig mir einen Index auf orders",
]


@pytest.mark.parametrize("text", REPORTS)
def test_first_messages_that_report_a_problem_start_an_incident(text: str) -> None:
    assert looks_like_customer_problem(text)


@pytest.mark.parametrize("text", NOT_REPORTS)
def test_greetings_answers_and_concept_questions_do_not(text: str) -> None:
    assert not looks_like_customer_problem(text)
