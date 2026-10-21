import type { Strings } from "../i18n";
import type { LedgerEntry } from "../types";

export function Ledger({ entries, s, onReview }: { entries: LedgerEntry[]; s: Strings; onReview: (topic: string) => void }) {
  if (!entries.length) return <p className="text-xs text-zinc-500">{s.ledgerEmpty}</p>;
  const sorted = [...entries].sort((a, b) => a.score - b.score);  // weakest first
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
            <button type="button" onClick={() => onReview(e.topic)}
                    className="ml-auto text-zinc-500 hover:text-zinc-200">{s.reviewNow}</button>
          </div>
        </li>
      ))}
    </ul>
  );
}
