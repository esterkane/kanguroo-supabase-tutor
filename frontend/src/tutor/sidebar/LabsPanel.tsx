import { useEffect, useState } from "react";
import type { TutorApi } from "../api";
import type { Strings } from "../i18n";
import type { LabInfo } from "../types";

type Action = "install" | "status" | "check" | "reproduce";

export interface LabOutput {
  slug: string;
  action: string;
  body: Record<string, unknown>;
}

export function LabsPanel({ api, sessionId, s, handover }: {
  api: TutorApi; sessionId: string; s: Strings; handover?: LabOutput | null;
}) {
  const [labs, setLabs] = useState<LabInfo[]>([]);
  const [out, setOut] = useState<LabOutput | null>(handover ?? null);

  useEffect(() => {
    if (handover) setOut(handover);  // the tutor installed a lab: show its customer report here
  }, [handover]);

  useEffect(() => {
    api.labs().then((r) => setLabs(r.labs)).catch(() => setLabs([]));
  }, [api]);

  const act = async (slug: string, action: Action) => {
    setOut({ slug, action, body: await api.labAction(sessionId, slug, action).catch((e) => ({ error: String(e) })) });
  };

  return (
    <div className="space-y-2 text-xs">
      <ul className="space-y-1">
        {labs.map((lab) => (
          <li key={lab.slug} className="flex items-center gap-1">
            <span className="w-6 text-zinc-500">{lab.phase}</span>
            <span className="flex-1 truncate" title={lab.title}>{lab.slug}</span>
            {(["install", "status", "check", ...(lab.reproducible ? ["reproduce"] : [])] as Action[]).map((a) => (
              <button key={a} type="button" onClick={() => act(lab.slug, a)}
                      className="rounded border border-zinc-700 px-1 hover:border-sky-600">{s[a]}</button>
            ))}
          </li>
        ))}
      </ul>
      {out && (
        <div className="rounded border border-zinc-800 p-2">
          <p className="mb-1 font-mono text-zinc-400">{out.slug} · {out.action}</p>
          {typeof out.body.passed === "boolean" && (
            <p className={out.body.passed ? "text-emerald-400" : "text-amber-400"}>
              {out.body.passed ? "PASS" : "FAIL"}
            </p>
          )}
          {typeof out.body.error === "string" && <p className="text-red-400">{out.body.error}</p>}
          {typeof out.body.learner_action === "string" && <p className="text-amber-300">{out.body.learner_action}</p>}
          {out.action === "reproduce" && typeof out.body.stage === "string" && (
            <div className="space-y-1 font-mono text-[11px]">
              <p className="text-zinc-400">{String(out.body.reproduced_as)} · {String(out.body.application_name ?? "")} · {String(out.body.ms)} ms</p>
              {out.body.ok === false ? (
                <p className="text-red-400">{String(out.body.stage)}: {String(out.body.sqlstate ?? "")} {String(out.body.message ?? "")}</p>
              ) : (
                <pre className="whitespace-pre-wrap text-emerald-300">{JSON.stringify({ rows: out.body.rows, session_settings: out.body.session_settings }, null, 1)}</pre>
              )}
            </div>
          )}
          {typeof out.body.scenario === "string" && (
            <pre className="max-h-72 overflow-auto whitespace-pre-wrap text-[11px] text-zinc-300">{out.body.scenario}</pre>
          )}
        </div>
      )}
    </div>
  );
}
