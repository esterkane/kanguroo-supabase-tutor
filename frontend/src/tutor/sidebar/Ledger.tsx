import type { Strings } from "../i18n";
import type { LedgerEntry } from "../types";

const isDue = (e: LedgerEntry, now: number) => !!e.next_review && Date.parse(e.next_review) <= now;

export function Ledger({ entries, s, onReview, now = Date.now() }: {
  entries: LedgerEntry[]; s: Strings; onReview: (topic: string) => void; now?: number;
}) {
  if (!entries.length) return <p className="text-xs text-zinc-500">{s.ledgerEmpty}</p>;
  // Due reviews first (most overdue on top), then the weakest topics.
  const sorted = [...entries].sort((a, b) => {
    const da = isDue(a, now), db = isDue(b, now);
    if (da !== db) return da ? -1 : 1;
    if (da && db) return Date.parse(a.next_review!) - Date.parse(b.next_review!);
    return a.score - b.score;
  });
  return (
    <ul className="space-y-1.5" aria-label={s.ledger}>
      {sorted.map((e) => (
        <li key={e.topic} className="text-xs">
          <div className="flex items-center gap-2">
            <span className="w-40 truncate font-mono" title={e.evidence ?? ""}>{e.topic}</span>
            <span className="flex gap-0.5" aria-label={`${e.score}/5`}>
              {[1, 2, 3, 4, 5].map((i) => (
                <span key={i} className={`h-2 w-3 rounded-sm ${i <= e.score ? "bg-sky-500" : "bg-zinc-800"}`} />
              ))}
            </span>
            {isDue(e, now) ? (
              <span className="rounded bg-amber-900/60 px-1 text-[10px] text-amber-300">{s.due}</span>
            ) : e.next_review ? (
              <span className="text-[10px] text-zinc-500" title={s.nextReview}>{e.next_review.slice(0, 10)}</span>
            ) : null}
            <button type="button" onClick={() => onReview(e.topic)}
                    className="ml-auto text-zinc-500 hover:text-zinc-200">{s.reviewNow}</button>
          </div>
        </li>
      ))}
    </ul>
  );
}
