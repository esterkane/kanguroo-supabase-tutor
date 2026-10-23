"""Output guard: TutorTurn invariants from prompts/tutor_runtime.md and the master instructions.

`check()` is pure: it looks at one TutorTurn plus what the tools actually returned (`GuardContext`)
and returns GuardFinding[]. `block` findings get one rewrite request from the orchestrator; `warn`
findings only end up in `guard_flags`. `redact_secrets()` runs on every final turn regardless.

The claim and SQL checks are deliberately narrow regex heuristics: they catch the cheap, common
violations (an uncited price, an unflagged DROP) and leave judgement calls to evals (T1.11).
"""
from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urldefrag

from backend.tutor.schemas import GuardFinding, TutorTurn

QUESTION_MODES = {"lesson", "exam", "rabbit_hole"}
SPEECH_MAX_WORDS = 60
DIAGRAM_MAX_LINES = 45  # ~40 nodes plus header and styling lines
LEDGER_MAX = 3

# ----------------------------------------------------------------------------- patterns
SECRET_PATTERNS = [
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),  # JWT
    re.compile(r"\bsb_secret_[A-Za-z0-9_-]{8,}"),  # Supabase secret API key
    re.compile(r"\bsk-ant-[A-Za-z0-9_-]{10,}"),  # Anthropic key
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9]{20,}"),  # OpenAI-style key
]
# Connection string with a real-looking password; placeholders and the local default are fine.
CONN_PASSWORD = re.compile(r"postgres(?:ql)?://[^:/\s@]+:([^@\s]+)@")
PASSWORD_PLACEHOLDER = re.compile(r"^(?:\[.*\]|<.*>|\{.*\}|\*+|x+|postgres|password|your[-_].*|\$\{?\w+\}?)$", re.IGNORECASE)

DESTRUCTIVE_SQL = re.compile(
    r"\bdrop\s+(?:table|schema|database|index|policy|function|role|view|trigger|extension|type)\b"
    r"|\btruncate\b"
    r"|\bdelete\s+from\s+[\w.\"]+\s*(?:;|$)"  # DELETE without WHERE
    r"|\bupdate\s+[\w.\"]+\s+set\s+(?:(?!\bwhere\b)[^;])*(?:;|$)"  # UPDATE without WHERE
    r"|\balter\s+system\b|\bvacuum\s+full\b|\breindex\b|\bcluster\s+\w"
    r"|\bdisable\s+row\s+level\s+security\b",
    re.IGNORECASE | re.DOTALL,
)
RISK_MARKER = re.compile(r"^\s*>?\s*⚠\s*Risk:", re.IGNORECASE)

# Sentences that state prices, plans, quotas or versions need a citation or an explicit label.
CLAIM = re.compile(
    r"[$€]\s?\d|\d\s?(?:USD|EUR)\b|\b(?:Free|Pro|Team|Enterprise)[- ](?:plan|Plan|tier|Tarif)\b"
    r"|\b(?:pricing|priced|billed|Preis|kostet|costs?\s+\$)"
    r"|\b(?:Postgres(?:QL)?|PG)\s?1\d\b|\bv\d+\.\d+(?:\.\d+)?\b|\bversion\s+\d+(?:\.\d+)*"
    r"|\b(?:limit(?:ed)?\s+(?:of|to)|maximum\s+of|up\s+to|bis\s+zu|höchstens)\s+\d",
    re.IGNORECASE,
)
LABELLED = re.compile(r"unverified|unverifiziert|nicht verifiziert|community|tier\s*4|fiktiv|fictional|"
                      r"illustrative|illustrativ", re.IGNORECASE)
# Any wording that tells the learner this is someone's experience, not current product behaviour.
COMMUNITY_LABEL = re.compile(r"community|tier\s*4|erfahrung|experience|forum|github[- ]?(?:issue|discussion)|reddit|"
                             r"stack ?overflow|blog|user report|nutzerbericht|anecdot|inoffiziell|unofficial|"
                             r"keine offizielle|not (?:an )?official", re.IGNORECASE)
MARKER = re.compile(r"\[(\d{1,2})\]")
EXECUTION_CLAIM = re.compile(
    r"\b(?:I|I've|I have)\s+(?:just\s+)?(?:ran|run|executed|tested|checked it in the lab)\b"
    r"|\bich\s+habe\s+(?:das\s+|es\s+|die\s+\w+\s+)?(?:gerade\s+)?(?:ausgeführt|laufen lassen|getestet)\b",
    re.IGNORECASE,
)
PERSONA_WORDS = re.compile(r"Kleinkünstler|Känguru|Schnapspraline|Kühlschrank|Vermieter|Weltrevolution", re.IGNORECASE)
SPEECH_MARKUP = re.compile(r"```|https?://|\bselect\s+.+\bfrom\b|sequenceDiagram|flowchart\s", re.IGNORECASE)


# ----------------------------------------------------------------------------- context
@dataclass(frozen=True)
class GuardContext:
    """What the tools actually returned in this conversation: cited URL (no fragment) → tier."""

    sources: dict[str, int] = field(default_factory=dict)
    ran_lab_sql: bool = False
    learner_text: str = ""  # secrets the learner pasted must not be repeated back, not even in a warning
    known_evidence: int = 0  # evidence items already in the session's incident model


def _norm(url: str) -> str:
    return urldefrag(url.strip())[0].rstrip("/")


def collect_sources(messages: Iterable[dict[str, Any]]) -> dict[str, int]:
    """URL → tier from every search_docs / web_search tool_result in the messages."""
    sources: dict[str, int] = {}
    for msg in messages:
        content = msg.get("content")
        if msg.get("role") != "user" or not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result" or block.get("is_error"):
                continue
            body = block.get("content")
            if not isinstance(body, str):
                continue
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                payload = None
            if isinstance(payload, dict) and isinstance(payload.get("results"), list):
                for hit in payload["results"]:
                    if isinstance(hit, dict) and isinstance(hit.get("url"), str):
                        sources[_norm(hit["url"])] = int(hit.get("tier", 4))
            for url, tier in re.findall(r'<untrusted_source url="([^"]+)" tier="(\d)"', body):
                sources[_norm(html.unescape(url))] = int(tier)
    return sources


def ran_tool(messages: Iterable[dict[str, Any]], name: str) -> bool:
    return any(
        isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == name
        for m in messages if m.get("role") == "assistant" and isinstance(m.get("content"), list)
        for b in m["content"]
    )


# ----------------------------------------------------------------------------- markdown helpers
@dataclass(frozen=True)
class CodeBlock:
    lang: str
    code: str
    preceding: list[str]  # up to 3 non-empty lines before the fence


def split_markdown(md: str) -> tuple[str, list[CodeBlock]]:
    """(prose without code blocks and tables, code blocks)."""
    prose: list[str] = []
    blocks: list[CodeBlock] = []
    lines = md.splitlines()
    i = 0
    while i < len(lines):
        stripped = lines[i].lstrip("> ").strip()
        if stripped.startswith("```"):
            lang = stripped[3:].strip().lower()
            before = [ln for ln in lines[:i] if ln.strip()][-3:]
            j = i + 1
            while j < len(lines) and not lines[j].lstrip("> ").strip().startswith("```"):
                j += 1
            blocks.append(CodeBlock(lang, "\n".join(lines[i + 1:j]), before))
            i = j + 1
            continue
        if not stripped.startswith("|"):
            prose.append(lines[i])
        i += 1
    return "\n".join(prose), blocks


def sentences(prose: str) -> list[str]:
    out: list[str] = []
    for para in re.split(r"\n\s*\n|\n(?=\s*[-*\d]+[.)]?\s)", prose):
        out += [s.strip() for s in re.split(r"(?<=[.!?])\s+", " ".join(para.split())) if s.strip()]
    return out


def _secrets_in(text: str) -> list[str]:
    found = [m.group(0) for p in SECRET_PATTERNS for m in p.finditer(text)]
    found += [m.group(1) for m in CONN_PASSWORD.finditer(text) if not PASSWORD_PLACEHOLDER.match(m.group(1))]
    return found


def learner_secrets(learner_text: str) -> list[str]:
    """Secrets in the learner's message (a pasted key or connection-string password), longest first."""
    return sorted(set(_secrets_in(learner_text)), key=len, reverse=True)


def redact_secrets(turn: TutorTurn, learner_text: str = "") -> TutorTurn:
    """Last line of defense: replace secrets in learner-visible fields, incl. ones the learner pasted."""
    known = learner_secrets(learner_text)

    def scrub(text: str) -> str:
        for secret in [*known, *_secrets_in(text)]:
            text = text.replace(secret, "[REDACTED]")
        return text

    diagrams = [d.model_copy(update={"code": scrub(d.code)}) for d in turn.diagrams]
    return turn.model_copy(update={"text": scrub(turn.text), "speech": scrub(turn.speech), "diagrams": diagrams})


# ----------------------------------------------------------------------------- checks
def _f(code: str, severity: str, hint: str) -> GuardFinding:
    return GuardFinding(code=code, severity=severity, fix_hint=hint)  # type: ignore[arg-type]


def check_questions(turn: TutorTurn) -> list[GuardFinding]:
    q = (turn.next_question or "").strip()
    if turn.mode in QUESTION_MODES and turn.session_end is None and not q:
        return [_f("NO_QUESTION", "block", f"Mode {turn.mode} needs exactly one next_question; end the answer with it.")]
    findings = []
    if q.count("?") > 1:
        findings.append(_f("MULTI_QUESTION", "block", "next_question must be one question (one '?'). Keep the "
                                                      "most discriminating one."))
    prose, _ = split_markdown(turn.text)
    asked = [s for s in sentences(prose) if s.endswith("?") and not s.startswith(">")]
    if len(asked) > 1 and turn.mode in QUESTION_MODES and turn.session_end is None:
        findings.append(_f("MULTI_QUESTION", "block", f"{len(asked)} questions in the text; end with exactly one, "
                                                      "rhetorical ones count for the learner too."))
    if q and not _question_in_text(q, turn.text):
        findings.append(_f("QUESTION_NOT_IN_TEXT", "warn", "Put next_question at the end of the Markdown too."))
    return findings


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"\w+", text.lower()) if len(w) > 3}


def _question_in_text(question: str, text: str) -> bool:
    """The model may word next_question differently from the Markdown: reworded, or as a self-contained
    version that repeats the scenario. Accept the text when one of its last questions shares at least half of
    the content words of the shorter of the two."""
    asked = [s for s in sentences(split_markdown(text)[0]) if s.endswith("?")]
    want = _words(question)
    if not asked or not want:
        return False
    return max(len(want & _words(s)) / max(1, min(len(want), len(_words(s)))) for s in asked[-2:]) >= 0.5


def check_citations(turn: TutorTurn, ctx: GuardContext) -> list[GuardFinding]:
    findings = []
    used = {int(n) for n in MARKER.findall(split_markdown(turn.text)[0])}
    listed = {c.n: c for c in turn.citations}
    if missing := sorted(used - listed.keys()):
        findings.append(_f("CITATION_MARKER_MISSING", "block",
                           f"Markers {missing} have no entry in citations[]; add them or remove the markers."))
    if unused := sorted(listed.keys() - used):
        findings.append(_f("CITATION_UNUSED", "warn", f"citations {unused} are never marked in the text."))
    for c in turn.citations:
        tool_tier = ctx.sources.get(_norm(c.url))
        if tool_tier is None:
            findings.append(_f("CITATION_NOT_FROM_TOOL", "block",
                               f"[{c.n}] {c.url} was not returned by search_docs/web_search in this conversation. "
                               "Cite only URLs a tool returned, or mark the claim 'unverified — verify live'."))
        elif c.tier < tool_tier:
            findings.append(_f("CITATION_TIER_INFLATED", "block",
                               f"[{c.n}] is tier {tool_tier} according to the tool, not tier {c.tier}."))
    community = {c.n for c in turn.citations if max(c.tier, ctx.sources.get(_norm(c.url), 0)) >= 4}
    if unlabelled := unlabelled_community(turn.text, community):
        findings.append(_f("COMMUNITY_UNLABELLED", "block",
                           f"Label tier-4 evidence as community evidence in: \"{unlabelled[:80]}\""))
    return findings


def unlabelled_community(text: str, community: set[int]) -> str | None:
    """First paragraph that cites tier-4 evidence without saying it is community evidence, else None.

    The paragraph is the unit: "The search found a GitHub issue [1]. A comment suggests pinning 2.79 [1]." is
    labelled; so is "… one person's experience. [5] Don't do that."."""
    if not community:
        return None
    for para in re.split(r"\n\s*\n", split_markdown(text)[0]):
        if {int(n) for n in MARKER.findall(para)} & community and not COMMUNITY_LABEL.search(para):
            return para.strip()
    return None


def check_uncited_claims(turn: TutorTurn) -> list[GuardFinding]:
    prose, _ = split_markdown(turn.text)
    bad = [s for s in sentences(prose) if CLAIM.search(s) and not MARKER.search(s) and not LABELLED.search(s)]
    if not bad:
        return []
    return [_f("UNCITED_CLAIM", "block",
               "These sentences state prices, plans, limits or versions without [n] or an 'unverified' label: "
               + " | ".join(f'"{s[:90]}"' for s in bad[:3]))]


def check_secrets(turn: TutorTurn, ctx: GuardContext | None = None) -> list[GuardFinding]:
    fields = [turn.text, turn.speech, *(d.code for d in turn.diagrams)]
    pasted = learner_secrets(ctx.learner_text) if ctx else []
    if any(_secrets_in(f) for f in fields) or any(secret in f for secret in pasted for f in fields):
        return [_f("SECRET_LEAK", "block", "Remove keys, JWTs and real passwords; use placeholders like "
                                          "<SERVICE_ROLE_KEY> or [YOUR-PASSWORD] and say they stay server-side.")]
    return []


def check_sql(turn: TutorTurn) -> list[GuardFinding]:
    _, blocks = split_markdown(turn.text)
    findings = []
    for block in blocks:
        if block.lang not in {"", "sql", "psql", "postgresql", "pgsql", "plpgsql"}:
            continue
        flagged = any(RISK_MARKER.search(ln) for ln in block.preceding)
        hit = DESTRUCTIVE_SQL.search(block.code)
        if hit and not flagged:
            what = " ".join(hit.group(0).split())[:40]
            hint = ("Disabling RLS is never a fix; only a labelled diagnostic in the lab." if "disable" in what.lower()
                    else "Put destructive SQL right after a line starting with '> ⚠ Risk:' naming lock level / "
                         "data loss and rollback, and prefer the lab database.")
            findings.append(_f("DESTRUCTIVE_SQL_UNFLAGGED", "block", f"`{what}`: {hint}"))
        if PERSONA_WORDS.search(block.code):
            findings.append(_f("PERSONA_IN_CODE", "warn", "No persona or jokes inside code blocks."))
    return findings


RESTART = re.compile(r"(?i)\b(re-?start\w*|reboot\w*|neu\s?(?:ge)?start\w*)")


def check_incident(turn: TutorTurn, ctx: GuardContext) -> list[GuardFinding]:
    if turn.mode == "incident" and turn.incident is None:
        return [_f("INCIDENT_MODEL_MISSING", "block", "Incident mode: send `incident` with the new or changed "
                                                      "fields (null for unknowns).")]
    inc = turn.incident
    if inc is None:
        return []
    findings = []
    if inc.root_cause and RESTART.search(inc.root_cause):
        findings.append(_f("INCIDENT_RESTART_ROOT_CAUSE", "block", "A restart is never a root cause: it is a "
                           "mitigation at best. Name what the restart cleared (connections, locks, memory) or keep "
                           "root_cause null."))
    if inc.root_cause and not inc.evidence and ctx.known_evidence == 0:
        findings.append(_f("INCIDENT_ROOT_CAUSE_WITHOUT_EVIDENCE", "block", "root_cause needs evidence first: keep it "
                           "null and ask for the most discriminating evidence."))
    if inc.root_cause and not inc.confidence:
        findings.append(_f("INCIDENT_CONFIDENCE_MISSING", "warn", "Give `confidence` with a root cause."))
    ranks = [h.rank for h in inc.hypotheses]
    if len(ranks) != len(set(ranks)):
        findings.append(_f("INCIDENT_HYPOTHESIS_RANKS", "warn", "Hypothesis ranks must be unique (1 = most likely)."))
    return findings


def check_session_end(turn: TutorTurn) -> list[GuardFinding]:
    """The master instructions' end block: understand, proved in the lab, still wrong, THREE retrieval questions,
    ONE next support case."""
    end = turn.session_end
    if end is None:
        return []
    findings = []
    if len(end.retrieval_questions) != 3:
        findings.append(_f("SESSION_END_RETRIEVAL", "block", f"session_end needs exactly three retrieval questions, "
                                                             f"not {len(end.retrieval_questions)}."))
    if not end.next_case.strip():
        findings.append(_f("SESSION_END_NEXT_CASE", "block", "session_end needs one support case to think about next."))
    if not end.understand:
        findings.append(_f("SESSION_END_EMPTY", "warn", "session_end.understand is empty: what should the learner "
                                                        "now understand?"))
    return findings


def check_speech(turn: TutorTurn) -> list[GuardFinding]:
    findings = []
    if (n := len(turn.speech.split())) > SPEECH_MAX_WORDS:
        findings.append(_f("SPEECH_TOO_LONG", "block", f"speech has {n} words; at most {SPEECH_MAX_WORDS}."))
    if SPEECH_MARKUP.search(turn.speech) or _secrets_in(turn.speech):
        findings.append(_f("SPEECH_HAS_MARKUP", "block", "speech is read aloud: no code, SQL, URLs or diagrams."))
    return findings


def check_execution_claims(turn: TutorTurn, ctx: GuardContext) -> list[GuardFinding]:
    if not ctx.ran_lab_sql and EXECUTION_CLAIM.search(split_markdown(turn.text)[0]):
        return [_f("CLAIMED_EXECUTION", "block", "You did not run anything this turn (no run_lab_sql). Say what "
                                                 "the learner should run, or label output as illustrative.")]
    return []


def check_shape(turn: TutorTurn) -> list[GuardFinding]:
    findings = []
    if len(turn.ledger_delta) > LEDGER_MAX:
        findings.append(_f("LEDGER_TOO_MANY", "warn", f"At most {LEDGER_MAX} ledger_delta entries per turn."))
    for d in turn.diagrams:
        if len(d.code.splitlines()) > DIAGRAM_MAX_LINES:
            findings.append(_f("DIAGRAM_TOO_BIG", "warn", f"Diagram {d.id} is too large; keep it under 40 nodes."))
    return findings


def check(turn: TutorTurn, ctx: GuardContext) -> list[GuardFinding]:
    return [
        *check_questions(turn),
        *check_citations(turn, ctx),
        *check_uncited_claims(turn),
        *check_secrets(turn, ctx),
        *check_sql(turn),
        *check_incident(turn, ctx),
        *check_session_end(turn),
        *check_speech(turn),
        *check_execution_claims(turn, ctx),
        *check_shape(turn),
    ]


def repair_message(findings: list[GuardFinding]) -> str:
    lines = "\n".join(f"- {f.code}: {f.fix_hint}" for f in findings if f.severity == "block")
    return ("[app message, not from the learner] The output guard rejected your answer:\n" + lines +
            "\nWrite the whole answer again (Markdown, then the ```json tutor_turn block without `text`), "
            "fixing only these points. The learner will see the new version instead of the old one.")
