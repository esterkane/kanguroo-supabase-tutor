// Mirrors backend/tutor/schemas.py (TutorTurn) and the router's response shapes.
export type Mode = "lesson" | "incident" | "exam" | "neutral" | "rabbit_hole";
export type Language = "de" | "en";

export interface Diagram {
  id: string;
  kind: "sequenceDiagram" | "flowchart" | "erDiagram" | "xychart-beta";
  title: string;
  code: string;
}

export interface Citation {
  n: number;
  url: string;
  title: string;
  tier: number;
  fetched_at?: string | null;
}

export interface PathState {
  state: "main" | "rabbit_hole";
  depth: number;
  return_point?: string | null;
}

export interface TutorTurn {
  mode: Mode;
  language: Language;
  persona_on: boolean;
  speech: string;
  text: string;
  diagrams: Diagram[];
  citations: Citation[];
  next_question?: string | null;
  path?: PathState | null;
  ledger_delta: { topic: string; score: number; evidence: string }[];
  lab_action?: { slug: string; action: string } | null;
  incident?: Incident | null;
  session_end?: {
    understand: string[];
    proved: string[];
    still_wrong: string[];
    retrieval_questions: string[];
    next_case: string;
  } | null;
  guard_flags: string[];
}

export interface Hypothesis {
  h: string;
  rank: number;
  test?: string | null;
  status: "open" | "supported" | "falsified";
}

export const INCIDENT_SCALARS = ["symptom", "expected", "scope", "timeline", "environment", "root_cause",
  "mitigation", "permanent_fix", "prevention", "confidence"] as const;
export type IncidentScalar = (typeof INCIDENT_SCALARS)[number];

export type Incident = { [K in IncidentScalar]?: string | null } & { evidence: string[]; hypotheses: Hypothesis[] };

/** Mirrors backend/tutor/incident.py IncidentState: the session's merged incident model. */
export interface IncidentState {
  model: Incident;
  sources: Record<string, "tutor" | "learner">;
  conflicts: { field: string; learner: string; tutor: string }[];
}

export interface Session {
  id: string;
  objective: string | null;
  mode: Mode;
  language: Language;
  persona_on: boolean;
  started_at: string;
  delivery?: "socratic" | "explicit";
  incident?: IncidentState | null;
}

export interface TranscriptRow {
  id: string;
  role: "user" | "assistant";
  content: string;
  tutor_turn: TutorTurn | null;
}

export interface LedgerEntry {
  topic: string;
  phase: string;
  title: string;
  score: number;
  evidence: string | null;
  last_reviewed: string;
  next_review?: string | null;  // FSRS due date (backend/tutor/review.py)
}

export interface LabInfo {
  slug: string;
  phase: string;
  title: string;
  requires: string[];
  reproducible?: boolean;
}

export interface PlanNode {
  "Node Type": string;
  "Relation Name"?: string;
  "Index Name"?: string;
  "Plan Rows"?: number;
  "Actual Rows"?: number;
  "Actual Loops"?: number;
  "Actual Total Time"?: number;
  "Shared Hit Blocks"?: number;
  "Shared Read Blocks"?: number;
  Filter?: string;
  "Index Cond"?: string;
  "Rows Removed by Filter"?: number;
  Plans?: PlanNode[];
  [key: string]: unknown;
}

export interface LabSqlResult {
  ok: boolean;
  refused?: boolean;
  reason?: string;
  role?: string;
  statement?: string;
  rows?: Record<string, unknown>[];
  truncated?: boolean;
  row_count?: number | null;
  sqlstate?: string | null;
  message?: string | null;
  detail?: string | null;
  hint?: string | null;
  plan?: { Plan: PlanNode; "Execution Time"?: number; "Planning Time"?: number }[] | null;
  explain_note?: string;
  persisted?: boolean;
  persist_note?: string;
  ms?: number;
}

export interface VoiceInfo {
  tts: "browser" | "server";
  voices: Partial<Record<Language, string | null>>;
}

export type StreamEvent =
  | { event: "token"; data: { text: string } }
  | { event: "tool_call"; data: { name: string; input: Record<string, unknown> } }
  | { event: "tool_result_summary"; data: { name: string; is_error: boolean; summary: string } }
  | { event: "rewrite"; data: { codes: string[] } }
  | { event: "turn"; data: { turn_id: string; turn: TutorTurn; usage: Record<string, number>; model: string } }
  | { event: "mode"; data: { mode: Mode; reason: string } }
  | { event: "incident"; data: { incident: IncidentState; changed: string[] } }
  | { event: "lab"; data: { slug: string; action: string; result: Record<string, unknown> } }
  | { event: "error"; data: { status: number; message: string } };
