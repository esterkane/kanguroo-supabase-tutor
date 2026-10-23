// Incident model form (T2.2): the tutor fills it turn by turn, the learner can correct any field.
import { useState } from "react";
import { INCIDENT_LABELS, type Strings } from "../i18n";
import { type IncidentScalar, type IncidentState, type Language } from "../types";
import { incidentMarkdown, missingFields, progress } from "./incidentModel";

export type IncidentEditFn = (body: { field: IncidentScalar | "evidence"; value?: string | null; index?: number }) =>
  Promise<void>;

const HYP_STYLE = { open: "text-zinc-400", supported: "text-emerald-400", falsified: "text-zinc-600 line-through" };

function SourceBadge({ source, s }: { source?: "tutor" | "learner"; s: Strings }) {
  if (!source) return null;
  return (
    <span className={`rounded px-1 text-[10px] ${source === "learner" ? "bg-sky-950 text-sky-300" : "bg-zinc-800 text-zinc-400"}`}>
      {source === "learner" ? s.byLearner : s.byTutor}
    </span>
  );
}

function ScalarRow({ field, state, lang, s, next, onEdit, changed }: {
  field: IncidentScalar; state: IncidentState; lang: Language; s: Strings; next: boolean; changed: boolean;
  onEdit: IncidentEditFn;
}) {
  const value = state.model[field] ?? "";
  const [draft, setDraft] = useState<string | null>(null);
  const conflict = state.conflicts.find((c) => c.field === field);
  const save = async (v: string | null) => {
    await onEdit({ field, value: v });
    setDraft(null);
  };
  return (
    <div className={`rounded border px-2 py-1 ${next ? "border-amber-700" : changed ? "border-sky-800" : "border-zinc-800"}`}>
      <div className="flex items-center gap-2">
        <span className="text-[11px] uppercase tracking-wide text-zinc-500">{INCIDENT_LABELS[lang][field]}</span>
        <SourceBadge source={state.sources[field]} s={s} />
        {next && <span className="text-[10px] text-amber-400">{s.next}</span>}
        {draft === null && (
          <button type="button" onClick={() => setDraft(value)} className="ml-auto text-[11px] text-zinc-500 hover:text-zinc-200">
            {s.edit}
          </button>
        )}
      </div>
      {draft === null ? (
        <p className={`whitespace-pre-wrap ${value ? "" : "text-zinc-600"}`}>{value || s.open}</p>
      ) : (
        <div className="mt-1 space-y-1">
          <textarea aria-label={INCIDENT_LABELS[lang][field]} value={draft} rows={3} onChange={(e) => setDraft(e.target.value)}
                    className="w-full rounded border border-zinc-700 bg-zinc-900 p-1 text-xs focus:border-sky-600 focus:outline-none" />
          <div className="flex gap-2 text-[11px]">
            <button type="button" onClick={() => save(draft)} className="rounded bg-sky-700 px-2 py-0.5">{s.save}</button>
            {value && <button type="button" onClick={() => save(null)} className="text-zinc-400 hover:text-zinc-200">{s.clear}</button>}
            <button type="button" onClick={() => setDraft(null)} className="text-zinc-400 hover:text-zinc-200">{s.cancel}</button>
          </div>
        </div>
      )}
      {conflict && <p className="mt-1 text-[11px] text-amber-300">{s.conflict}: {conflict.tutor}</p>}
    </div>
  );
}

export function IncidentPanel({ state, lang, s, onEdit, changed = [] }: {
  state: IncidentState | null; lang: Language; s: Strings; onEdit: IncidentEditFn; changed?: string[];
}) {
  const [evidence, setEvidence] = useState("");
  const [copied, setCopied] = useState(false);
  if (!state) return <p className="text-xs text-zinc-500">{s.incidentEmpty}</p>;
  const m = state.model;
  const gaps = missingFields(state);
  const { filled, total } = progress(state);
  const label = INCIDENT_LABELS[lang];
  const row = (f: IncidentScalar) => (
    <ScalarRow key={f} field={f} state={state} lang={lang} s={s} next={gaps[0] === f} changed={changed.includes(f)}
               onEdit={onEdit} />
  );
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(incidentMarkdown(state, lang));
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard blocked: nothing to do, the panel still shows everything
    }
  };

  return (
    <section className="space-y-2 text-xs" aria-label={s.incident}>
      <div className="flex items-center gap-2">
        <div className="h-1.5 flex-1 rounded bg-zinc-800" role="progressbar" aria-valuenow={filled} aria-valuemax={total}>
          <div className="h-1.5 rounded bg-sky-600" style={{ width: `${(filled / total) * 100}%` }} />
        </div>
        <span className="text-[11px] text-zinc-400">{filled}/{total} {s.filled}</span>
        <button type="button" onClick={copy} className="rounded border border-zinc-700 px-1.5 py-0.5 text-[11px] hover:border-sky-600">
          {copied ? s.copied : s.copyMarkdown}
        </button>
      </div>
      {(["symptom", "expected", "scope", "timeline", "environment"] as const).map(row)}

      <div className={`rounded border px-2 py-1 ${gaps[0] === "evidence" ? "border-amber-700" : changed.includes("evidence") ? "border-sky-800" : "border-zinc-800"}`}>
        <span className="text-[11px] uppercase tracking-wide text-zinc-500">{label.evidence}</span>
        {gaps[0] === "evidence" && <span className="ml-2 text-[10px] text-amber-400">{s.next}</span>}
        <ul className="mt-1 space-y-1">
          {m.evidence.map((e, i) => (
            <li key={`${i}-${e}`} className="flex items-start gap-2">
              <span className="flex-1 whitespace-pre-wrap font-mono text-[11px]">{e}</span>
              <SourceBadge source={state.sources[`evidence:${i}`]} s={s} />
              <button type="button" aria-label={`${s.remove} ${i + 1}`} onClick={() => onEdit({ field: "evidence", index: i })}
                      className="text-zinc-600 hover:text-red-400">×</button>
            </li>
          ))}
        </ul>
        <form className="mt-1 flex gap-1" onSubmit={async (e) => {
          e.preventDefault();
          if (!evidence.trim()) return;
          await onEdit({ field: "evidence", value: evidence });
          setEvidence("");
        }}>
          <input aria-label={s.addEvidence} value={evidence} placeholder={s.addEvidence} onChange={(e) => setEvidence(e.target.value)}
                 className="flex-1 rounded border border-zinc-700 bg-zinc-900 px-1 py-0.5 font-mono text-[11px] focus:border-sky-600 focus:outline-none" />
          <button type="submit" disabled={!evidence.trim()} className="rounded border border-zinc-700 px-1.5 disabled:opacity-40">+</button>
        </form>
      </div>

      <div className={`rounded border px-2 py-1 ${gaps[0] === "hypotheses" ? "border-amber-700" : changed.includes("hypotheses") ? "border-sky-800" : "border-zinc-800"}`}>
        <span className="text-[11px] uppercase tracking-wide text-zinc-500">{label.hypotheses}</span>
        {m.hypotheses.length ? (
          <ol className="mt-1 space-y-1">
            {m.hypotheses.map((h) => (
              <li key={h.rank}>
                <span className={HYP_STYLE[h.status]}>{h.rank}. {h.h}</span>
                <span className="ml-1 text-[10px] text-zinc-500">({s[`hypStatus_${h.status}`]})</span>
                {h.test && <span className="block pl-3 text-[11px] text-zinc-500">{s.test}: {h.test}</span>}
              </li>
            ))}
          </ol>
        ) : <p className="text-zinc-600">{s.open}</p>}
      </div>

      {(["root_cause", "mitigation", "permanent_fix", "prevention", "confidence"] as const).map(row)}
    </section>
  );
}
