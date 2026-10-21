import { useEffect, useState } from "react";

export interface TutorAppProps {
  /** Base path of the mounted FastAPI router, e.g. "/tutor". */
  apiBase: string;
}

type Health = "checking" | "ok" | "down";

/** Shell layout: chat (left), lesson sidebar (right). Panels are filled in T1.9. */
export function TutorApp({ apiBase }: TutorAppProps) {
  const [health, setHealth] = useState<Health>("checking");

  useEffect(() => {
    fetch("/healthz")
      .then((r) => setHealth(r.ok ? "ok" : "down"))
      .catch(() => setHealth("down"));
  }, []);

  return (
    <div className="grid h-screen grid-cols-[1fr_320px] text-sm">
      <main className="flex flex-col border-r border-zinc-800">
        <header className="flex items-center justify-between border-b border-zinc-800 px-3 py-2">
          <h1 className="font-semibold">Känguru Tutor</h1>
          <span data-testid="health" className="text-xs text-zinc-400">
            backend: {health}
          </span>
        </header>
        <section className="flex-1 overflow-y-auto p-3 text-zinc-400">
          Chat folgt in T1.9 ({apiBase}/turn).
        </section>
      </main>
      <aside className="p-3">
        <h2 className="mb-2 text-xs uppercase tracking-wide text-zinc-500">Lektion</h2>
        <p className="text-zinc-400">Noch keine Sitzung.</p>
      </aside>
    </div>
  );
}
