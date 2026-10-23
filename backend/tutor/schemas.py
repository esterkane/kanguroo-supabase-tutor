"""Data shapes shared across the tutor package (pydantic, extra='forbid')."""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class Chunk(BaseModel):
    """One search_docs hit: a cited passage of the official corpus."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_id: UUID
    url: str
    anchor: str | None
    heading_path: str
    content: str
    tier: int
    fetched_at: datetime | None
    score: float

    @property
    def cite_url(self) -> str:
        """URL with the heading anchor, the form the tutor puts in citations."""
        return f"{self.url}#{self.anchor}" if self.anchor else self.url


# ----------------------------------------------------------------------------- TutorTurn
# Mirrors prompts/tutor_output_schema.md. `text` is filled by the app from the streamed Markdown;
# `guard_flags` is set by the app (orchestrator/guard), never expected from the model.
class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Diagram(_Strict):
    id: str
    kind: Literal["sequenceDiagram", "flowchart", "erDiagram", "xychart-beta"]
    title: str
    code: str


class Citation(_Strict):
    n: int = Field(ge=1)
    url: str
    title: str
    tier: int = Field(ge=1, le=4)
    fetched_at: str | None = None


class PathState(_Strict):
    state: Literal["main", "rabbit_hole"] = "main"
    depth: int = Field(default=0, ge=0)
    return_point: str | None = None


class TurnLedgerDelta(_Strict):
    topic: str
    score: int = Field(ge=0, le=5)
    evidence: str = Field(min_length=10)


class LabAction(_Strict):
    slug: str
    action: Literal["install", "reset", "check", "hint"]


class Hypothesis(_Strict):
    h: str
    rank: int = Field(ge=1)
    test: str | None = None  # the discriminating test that would confirm or falsify it
    status: Literal["open", "supported", "falsified"] = "open"


class Incident(_Strict):
    symptom: str | None = None
    expected: str | None = None
    scope: str | None = None
    timeline: str | None = None
    environment: str | None = None
    evidence: list[str] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    root_cause: str | None = None
    mitigation: str | None = None
    permanent_fix: str | None = None
    prevention: str | None = None
    confidence: str | None = None


class SessionEnd(_Strict):
    understand: list[str]
    proved: list[str]
    still_wrong: list[str]
    retrieval_questions: list[str]
    next_case: str


class TutorTurn(_Strict):
    mode: Literal["lesson", "incident", "exam", "neutral", "rabbit_hole"]
    language: Literal["de", "en"]
    persona_on: bool
    speech: str
    text: str
    diagrams: list[Diagram] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    next_question: str | None = None
    path: PathState | None = None
    ledger_delta: list[TurnLedgerDelta] = Field(default_factory=list)
    lab_action: LabAction | None = None
    incident: Incident | None = None
    session_end: SessionEnd | None = None
    guard_flags: list[str] = Field(default_factory=list)


class GuardFinding(_Strict):
    """One violated TutorTurn invariant. `block` triggers one rewrite request; `warn` is only recorded."""

    code: str
    severity: Literal["block", "warn"]
    fix_hint: str
