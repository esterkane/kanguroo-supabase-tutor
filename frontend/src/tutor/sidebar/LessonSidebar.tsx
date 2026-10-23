import { MODE_COMMANDS, type Strings } from "../i18n";
import type { Session, TutorTurn } from "../types";

export function LessonSidebar({ session, lastTurn, s, onCommand, busy }: {
  session: Session; lastTurn: TutorTurn | null; s: Strings; onCommand: (cmd: string) => void; busy: boolean;
}) {
  const path = lastTurn?.path;
  const mode = lastTurn?.mode ?? session.mode;
  return (
    <div className="space-y-4 text-xs">
      <dl className="space-y-1">
        <dt className="uppercase tracking-wide text-zinc-500">{s.objective}</dt>
        <dd>{session.objective ?? s.noObjective}</dd>
        <dt className="pt-1 uppercase tracking-wide text-zinc-500">{s.modes}</dt>
        <dd className="font-mono">{mode}{lastTurn && !lastTurn.persona_on ? " · neutral voice" : ""}</dd>
        {session.delivery && (
          <>
            <dt className="pt-1 uppercase tracking-wide text-zinc-500">{s.delivery}</dt>
            <dd>{session.delivery === "explicit" ? s.deliveryExplicit.replace(/ \(.*\)$/, "") : s.deliverySocratic}</dd>
          </>
        )}
        <dt className="pt-1 uppercase tracking-wide text-zinc-500">{s.path}</dt>
        <dd>
          {path?.state === "rabbit_hole" ? (
            <span className="text-amber-300">{s.rabbitHole} · depth {path.depth}</span>
          ) : (
            <span className="text-sky-300">{s.mainPath}</span>
          )}
          {path?.return_point && <span className="block text-zinc-400">{s.returnPoint}: {path.return_point}</span>}
        </dd>
      </dl>
      <div className="flex flex-wrap gap-1" role="group" aria-label={s.modes}>
        {MODE_COMMANDS.map((cmd) => (
          <button key={cmd} type="button" disabled={busy} onClick={() => onCommand(cmd)}
                  className="rounded border border-zinc-700 px-1.5 py-0.5 font-mono hover:border-sky-600 disabled:opacity-40">
            {cmd}
          </button>
        ))}
      </div>
    </div>
  );
}
