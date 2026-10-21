import { useEffect, useRef, useState } from "react";
import type { ChatState } from "../chatReducer";
import type { Strings } from "../i18n";
import { Markdown } from "./Markdown";
import { TurnView } from "./TurnView";

export function ChatPanel({ chat, s, onSend }: { chat: ChatState; s: Strings; onSend: (text: string) => void }) {
  const [draft, setDraft] = useState("");
  const end = useRef<HTMLDivElement>(null);
  const busy = chat.streaming !== null;

  useEffect(() => {
    // Braces matter: newer Chromium returns a Promise from scrollIntoView, and an effect must not return one.
    end.current?.scrollIntoView?.({ block: "end" });
  }, [chat.items.length, chat.streaming?.text]);

  const submit = () => {
    const text = draft.trim();
    if (!text || busy) return;
    onSend(text);
    setDraft("");
  };

  return (
    <section className="flex min-h-0 flex-1 flex-col" aria-label="chat">
      <div className="flex-1 space-y-3 overflow-y-auto p-3">
        {chat.items.map((item) =>
          item.kind === "user" ? (
            <div key={item.id} className="ml-auto max-w-[85%] rounded bg-zinc-800 px-3 py-2 text-sm whitespace-pre-wrap">
              {item.text}
            </div>
          ) : (
            <div key={item.id} className="max-w-[95%]"><TurnView turn={item.turn} s={s} /></div>
          ),
        )}
        {chat.streaming && (
          <div className="max-w-[95%]" aria-live="polite">
            {chat.streaming.rewrites.length > 0 && (
              <p className="mb-1 text-[11px] text-amber-400">
                {s.rewritten}: {chat.streaming.rewrites.at(-1)?.join(", ")}
              </p>
            )}
            {chat.streaming.tools.length > 0 && (
              <ul className="mb-2 flex flex-wrap gap-1 text-[11px]">
                {chat.streaming.tools.map((tool, i) => (
                  <li key={i} title={tool.summary}
                      className={`rounded border px-1.5 py-0.5 font-mono ${tool.isError ? "border-red-700 text-red-300"
                        : tool.done ? "border-zinc-700 text-zinc-400" : "border-sky-700 text-sky-300"}`}>
                    {tool.name}{typeof tool.input.query === "string" ? `: ${tool.input.query}` : ""}
                  </li>
                ))}
              </ul>
            )}
            {chat.streaming.text ? (
              <Markdown text={chat.streaming.text} diagramFailed={s.diagramFailed} />
            ) : (
              <p className="text-sm text-zinc-500">{s.thinking} …</p>
            )}
          </div>
        )}
        {chat.error && <p role="alert" className="text-sm text-red-400">{s.error}: {chat.error}</p>}
        <div ref={end} />
      </div>
      <form className="flex gap-2 border-t border-zinc-800 p-2"
            onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <textarea
          aria-label={s.placeholder} value={draft} rows={2} placeholder={s.placeholder}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); } }}
          className="flex-1 resize-none rounded border border-zinc-700 bg-zinc-900 p-2 text-sm focus:border-sky-600 focus:outline-none"
        />
        <button type="submit" disabled={busy || !draft.trim()}
                className="self-end rounded bg-sky-700 px-3 py-1.5 text-sm disabled:opacity-40">{s.send}</button>
      </form>
    </section>
  );
}
