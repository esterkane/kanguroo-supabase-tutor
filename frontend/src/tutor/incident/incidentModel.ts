// Pure helpers for the incident panel: progress, the next missing field, and the Markdown write-up.
import { INCIDENT_LABELS } from "../i18n";
import { INCIDENT_SCALARS, type IncidentState, type Language } from "../types";

export const GATHER = ["symptom", "expected", "scope", "timeline", "environment"] as const;
export type IncidentField = (typeof INCIDENT_SCALARS)[number] | "evidence" | "hypotheses";

/** Same order as backend incident.missing(): evidence gathering first, then cause and fix. */
export function missingFields(state: IncidentState): IncidentField[] {
  const m = state.model;
  const gaps: IncidentField[] = GATHER.filter((f) => !m[f]);
  if (!m.evidence.length) gaps.push("evidence");
  if (!m.hypotheses.length) gaps.push("hypotheses");
  return [...gaps, ...INCIDENT_SCALARS.filter((f) => !(GATHER as readonly string[]).includes(f) && !m[f])];
}

export function progress(state: IncidentState): { filled: number; total: number } {
  const total = INCIDENT_SCALARS.length + 2;
  return { filled: total - missingFields(state).length, total };
}

/** Ticket-ready write-up of the incident model (for a support ticket, a postmortem, or the learner's notes). */
export function incidentMarkdown(state: IncidentState, lang: Language): string {
  const label = INCIDENT_LABELS[lang];
  const m = state.model;
  const out = [`# ${lang === "de" ? "Incident-Modell" : "Incident model"}`, ""];
  for (const f of ["symptom", "expected", "scope", "timeline", "environment"] as const) {
    out.push(`**${label[f]}:** ${m[f] ?? "—"}`);
  }
  out.push("", `## ${label.evidence}`, ...(m.evidence.length ? m.evidence.map((e) => `- ${e}`) : ["- —"]));
  out.push("", `## ${label.hypotheses}`);
  out.push(...(m.hypotheses.length
    ? m.hypotheses.map((h) => `${h.rank}. ${h.h} (${h.status})${h.test ? ` — test: ${h.test}` : ""}`)
    : ["- —"]));
  out.push("");
  for (const f of ["root_cause", "mitigation", "permanent_fix", "prevention", "confidence"] as const) {
    out.push(`**${label[f]}:** ${m[f] ?? "—"}`);
  }
  return out.join("\n");
}
