import type { Strings } from "../i18n";
import type { TutorTurn } from "../types";
import { Markdown } from "./Markdown";
import { MermaidBlock } from "./MermaidBlock";

function SessionEndCard({ end, s }: { end: NonNullable<TutorTurn["session_end"]>; s: Strings }) {
  const sections: [string, string[]][] = [
    [s.endUnderstand, end.understand], [s.endProved, end.proved], [s.endStillWrong, end.still_wrong],
  ];
  return (
    <section aria-label={s.sessionEnd} className="space-y-2 rounded border border-emerald-900 bg-emerald-950/30 p-2 text-xs">
      <h3 className="text-[11px] uppercase tracking-wide text-emerald-400">{s.sessionEnd}</h3>
      {sections.map(([title, items]) => (
        <div key={title}>
          <h4 className="text-zinc-400">{title}</h4>
          {items.length ? <ul className="ml-4 list-disc">{items.map((x) => <li key={x}>{x}</li>)}</ul>
            : <p className="ml-4 text-zinc-600">{s.nothingYet}</p>}
        </div>
      ))}
      <div>
        <h4 className="text-zinc-400">{s.endRetrieval}</h4>
        <ol className="ml-4 list-decimal">{end.retrieval_questions.map((q) => <li key={q}>{q}</li>)}</ol>
      </div>
      <div>
        <h4 className="text-zinc-400">{s.endNextCase}</h4>
        <p className="ml-4">{end.next_case}</p>
      </div>
    </section>
  );
}

export function TurnView({ turn, s, onReplay }: { turn: TutorTurn; s: Strings; onReplay?: (speech: string) => void }) {
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
      {turn.session_end && <SessionEndCard end={turn.session_end} s={s} />}
      {onReplay && turn.speech && (
        <button type="button" onClick={() => onReplay(turn.speech)} title={turn.speech}
                className="rounded border border-zinc-800 px-1.5 py-0.5 text-[11px] text-zinc-400 hover:border-sky-600">
          {s.replay}
        </button>
      )}
      {turn.guard_flags.length > 0 && (
        <p className="text-[11px] text-zinc-500">guard: {turn.guard_flags.join(", ")}</p>
      )}
    </article>
  );
}
