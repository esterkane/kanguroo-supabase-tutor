import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { MermaidBlock } from "./MermaidBlock";

export function Markdown({ text, diagramFailed }: { text: string; diagramFailed: string }) {
  return (
    <div className="prose-tutor space-y-2 text-sm leading-relaxed">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noopener noreferrer" className="text-sky-400 underline">{children}</a>
          ),
          table: ({ children }) => (
            <div className="overflow-x-auto"><table className="my-2 border-collapse text-xs">{children}</table></div>
          ),
          th: ({ children }) => <th className="border border-zinc-700 px-2 py-1 text-left">{children}</th>,
          td: ({ children }) => <td className="border border-zinc-800 px-2 py-1 align-top">{children}</td>,
          blockquote: ({ children }) => (
            <blockquote className="border-l-2 border-amber-500 pl-3 text-amber-200">{children}</blockquote>
          ),
          code: ({ className, children }) => {
            const lang = /language-(\w+)/.exec(className ?? "")?.[1];
            const code = String(children).replace(/\n$/, "");
            if (lang === "mermaid") return <MermaidBlock code={code} failedLabel={diagramFailed} />;
            if (!lang && !code.includes("\n")) {
              return <code className="rounded bg-zinc-800 px-1 font-mono text-[0.85em]">{code}</code>;
            }
            return (
              <pre className="my-2 overflow-x-auto rounded bg-zinc-900 p-2 text-xs">
                <code className="font-mono">{code}</code>
              </pre>
            );
          },
          ul: ({ children }) => <ul className="ml-5 list-disc space-y-1">{children}</ul>,
          ol: ({ children }) => <ol className="ml-5 list-decimal space-y-1">{children}</ol>,
          h1: ({ children }) => <h3 className="font-semibold">{children}</h3>,
          h2: ({ children }) => <h3 className="font-semibold">{children}</h3>,
          h3: ({ children }) => <h4 className="font-semibold">{children}</h4>,
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
