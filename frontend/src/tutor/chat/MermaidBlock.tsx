import { useEffect, useId, useState } from "react";

let mermaidReady: Promise<typeof import("mermaid").default> | null = null;

function loadMermaid() {
  // Lazy: mermaid is large and most turns have no diagram.
  mermaidReady ??= import("mermaid").then(({ default: mermaid }) => {
    mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: "dark", fontFamily: "inherit" });
    return mermaid;
  });
  return mermaidReady;
}

export function MermaidBlock({ code, title, failedLabel }: { code: string; title?: string; failedLabel: string }) {
  const id = "m" + useId().replace(/[^a-zA-Z0-9]/g, "");
  const [svg, setSvg] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    loadMermaid()
      .then((mermaid) => mermaid.render(id, code))
      .then(({ svg }) => !cancelled && setSvg(svg))
      .catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
    };
  }, [id, code]);

  return (
    <figure className="my-2 rounded border border-zinc-800 bg-zinc-900/60 p-2">
      {title && <figcaption className="mb-1 text-xs text-zinc-400">{title}</figcaption>}
      {failed || svg === null ? (
        <>
          {failed && <p className="mb-1 text-xs text-amber-400">{failedLabel}</p>}
          <pre className="overflow-x-auto text-xs text-zinc-300"><code>{code}</code></pre>
        </>
      ) : (
        // securityLevel "strict": mermaid sanitises labels and disables click handlers.
        <div className="overflow-x-auto [&_svg]:max-w-full" dangerouslySetInnerHTML={{ __html: svg }} />
      )}
      <button type="button" className="mt-1 text-[11px] text-zinc-500 hover:text-zinc-300"
              onClick={() => navigator.clipboard?.writeText(code)}>copy Mermaid</button>
    </figure>
  );
}
