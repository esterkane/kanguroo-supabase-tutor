import type { Strings } from "../i18n";
import type { TutorTurn } from "../types";
import { Markdown } from "./Markdown";
import { MermaidBlock } from "./MermaidBlock";

export function TurnView({ turn, s }: { turn: TutorTurn; s: Strings }) {
  return (
    <article className="space-y-2">
      <Markdown text={turn.text} diagramFailed={s.diagramFailed} />
      {turn.diagrams.map((d) => (
        <MermaidBlock key={d.id} code={d.code} title={d.title} failedLabel={s.diagramFailed} />
      ))}
      {turn.citations.length > 0 && (
        <footer className="border-t border-zinc-800 pt-1 text-xs text-zinc-400">
          <span className="mr-2 uppercase tracking-wide text-zinc-500">{s.sources}</span>
          <ol className="mt-1 space-y-0.5">
            {turn.citations.map((c) => (
              <li key={c.n}>
                [{c.n}]{" "}
                <a href={c.url} target="_blank" rel="noopener noreferrer" className="text-sky-400 hover:underline">
                  {c.title}
                </a>{" "}
                <span className={c.tier >= 4 ? "text-amber-400" : "text-zinc-500"}>
                  tier {c.tier}{c.tier >= 4 ? ` · ${s.community}` : ""}
                </span>
              </li>
            ))}
          </ol>
        </footer>
      )}
      {turn.guard_flags.length > 0 && (
        <p className="text-[11px] text-zinc-500">guard: {turn.guard_flags.join(", ")}</p>
      )}
    </article>
  );
}
