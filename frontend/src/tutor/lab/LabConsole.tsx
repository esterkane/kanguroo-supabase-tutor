import { useState } from "react";
import type { TutorApi } from "../api";
import type { Strings } from "../i18n";
import type { LabSqlResult } from "../types";
import { PlanTree } from "./PlanTree";

const ROLES = ["authenticated", "anon", "postgres"] as const;

export interface ConsolePreset {
  sql: string;
  role: (typeof ROLES)[number];
  sub: string;
}

/** The first ```sql block of a lab README (its evidence query) as console settings. READMEs are written for
 *  psql (begin; set local role ...; set_config claims; ...; rollback;) — the console sets role and claims
 *  itself and refuses transaction control, so those wrappers become fields. */
export function consolePreset(scenario: string): ConsolePreset | null {
  const block = /```sql\n([\s\S]*?)```/.exec(scenario)?.[1];
  if (!block) return null;
  const roleMatch = /set\s+local\s+role\s+(\w+)/i.exec(block)?.[1];
  const role = (ROLES as readonly string[]).includes(roleMatch ?? "") ? (roleMatch as ConsolePreset["role"]) : "postgres";
  const sub = /"sub"\s*:\s*"([^"]+)"/.exec(block)?.[1] ?? "";
  const sql = block
    .replace(/select\s+set_config\(\s*'request\.jwt\.claims'[\s\S]*?\)\s*;/gi, "")
    .replace(/^\s*(begin|commit|rollback|end)\s*;\s*$/gim, "")
    .replace(/^\s*set\s+local\s+role\s+\w+\s*;\s*$/gim, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
  return { sql, role, sub };
}

/** Markdown summary of a console result, for the learner to send to the tutor as evidence. */
export function resultSummary(sql: string, role: string, sub: string, r: LabSqlResult): string {
  const lines = [`Lab-Konsole (Rolle ${role}${sub ? `, sub ${sub}` : ""}):`, "```sql", sql.trim(), "```"];
  if (r.refused) lines.push(`Abgelehnt: ${r.reason}`);
  else if (!r.ok) lines.push(`Fehler ${r.sqlstate}: ${r.message}${r.hint ? ` (Hint: ${r.hint})` : ""}`);
  else {
    const rows = r.rows ?? [];
    lines.push(`${rows.length} Zeile(n)${r.truncated ? " (gekürzt)" : ""}, ${r.ms} ms`);
    if (rows.length) {
      const cols = Object.keys(rows[0]);
      lines.push(`| ${cols.join(" | ")} |`, `|${cols.map(() => "---").join("|")}|`);
      for (const row of rows.slice(0, 5)) lines.push(`| ${cols.map((c) => String(row[c])).join(" | ")} |`);
    }
  }
  const plan = r.plan?.[0];
  if (plan) lines.push(`Plan: ${plan.Plan["Node Type"]}, Execution Time ${plan["Execution Time"]} ms`);
  return lines.join("\n");
}

export function LabConsole({ api, sessionId, s, onSend, preset }: {
  api: TutorApi; sessionId: string; s: Strings; onSend: (text: string) => void; preset?: ConsolePreset | null;
}) {
  const [sql, setSql] = useState(preset?.sql ?? "select * from lab01.orders;");
  const [role, setRole] = useState<(typeof ROLES)[number]>(preset?.role ?? "authenticated");
  const [sub, setSub] = useState(preset ? preset.sub : "11111111-1111-1111-1111-111111111111");
  const [explain, setExplain] = useState(false);
  const [persist, setPersist] = useState(false);
  const [result, setResult] = useState<LabSqlResult | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true);
    try {
      const claims = role !== "postgres" && sub ? { sub, role } : null;
      setResult(await api.labSql({ session_id: sessionId, sql, role, claims, explain, persist }));
    } catch (e) {
      setResult({ ok: false, message: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="space-y-2" aria-label={s.console}>
      <textarea value={sql} onChange={(e) => setSql(e.target.value)} rows={6} spellCheck={false}
                aria-label="SQL"
                onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); run(); } }}
                className="w-full rounded border border-zinc-700 bg-zinc-900 p-2 font-mono text-xs focus:border-sky-600 focus:outline-none" />
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <label>{s.role}{" "}
          <select value={role} onChange={(e) => setRole(e.target.value as (typeof ROLES)[number])}
                  className="rounded border border-zinc-700 bg-zinc-900 px-1">
            {ROLES.map((r) => <option key={r}>{r}</option>)}
          </select>
        </label>
        {role !== "postgres" && (
          <input aria-label={s.claimsSub} placeholder={s.claimsSub} value={sub} onChange={(e) => setSub(e.target.value)}
                 className="w-64 rounded border border-zinc-700 bg-zinc-900 px-1 font-mono" />
        )}
        <label><input type="checkbox" aria-label={s.explain} checked={explain} onChange={(e) => setExplain(e.target.checked)} /> {s.explain}</label>
        <label><input type="checkbox" aria-label={s.persist} checked={persist} onChange={(e) => setPersist(e.target.checked)} /> {s.persist}</label>
        <button type="button" onClick={run} disabled={busy || !sql.trim()}
                className="ml-auto rounded bg-sky-700 px-2 py-1 disabled:opacity-40">{s.run} ⌘↵</button>
      </div>
      {result && (
        <div className="space-y-2 text-xs">
          {result.refused ? (
            <p className="text-amber-400">{result.reason}</p>
          ) : !result.ok ? (
            <p className="text-red-400">
              {result.sqlstate && <span className="font-mono">{result.sqlstate} </span>}{result.message}
              {result.hint && <span className="block text-zinc-400">hint: {result.hint}</span>}
            </p>
          ) : (
            <p className="text-zinc-400">
              {(result.rows ?? []).length} {s.rows}{result.truncated ? " (truncated)" : ""} · {result.ms} ms
              {result.persisted ? " · persisted" : ""}{result.persist_note ? ` · ${result.persist_note}` : ""}
            </p>
          )}
          {(result.rows ?? []).length > 0 && (
            <div className="max-h-64 overflow-auto">
              <table className="border-collapse font-mono">
                <thead><tr>{Object.keys(result.rows![0]).map((c) => (
                  <th key={c} className="border border-zinc-700 px-1 text-left">{c}</th>))}</tr></thead>
                <tbody>{result.rows!.map((row, i) => (
                  <tr key={i}>{Object.keys(result.rows![0]).map((c) => (
                    <td key={c} className="border border-zinc-800 px-1">{String(row[c])}</td>))}</tr>))}</tbody>
              </table>
            </div>
          )}
          {result.plan?.[0] && <PlanTree plan={result.plan[0]} />}
          <button type="button" onClick={() => onSend(resultSummary(sql, role, role !== "postgres" ? sub : "", result))}
                  className="rounded border border-zinc-700 px-2 py-1 hover:border-sky-600">{s.sendToTutor}</button>
        </div>
      )}
    </section>
  );
}
