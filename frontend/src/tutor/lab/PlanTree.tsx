import type { PlanNode } from "../types";

const MISESTIMATE = 10;

function misestimated(node: PlanNode): boolean {
  const est = node["Plan Rows"];
  const actual = node["Actual Rows"];
  if (est === undefined || actual === undefined) return false;
  const ratio = (Math.max(actual, 1) / Math.max(est, 1));
  return ratio >= MISESTIMATE || ratio <= 1 / MISESTIMATE;
}

function Node({ node, depth }: { node: PlanNode; depth: number }) {
  const what = node["Index Name"] ? `${node["Relation Name"] ?? ""} using ${node["Index Name"]}` : node["Relation Name"];
  const loops = node["Actual Loops"] ?? 1;
  return (
    <details open={depth < 4} className="ml-3 border-l border-zinc-800 pl-2">
      <summary className="cursor-pointer font-mono text-xs">
        <span className="text-sky-300">{node["Node Type"]}</span>
        {what && <span className="text-zinc-400"> on {what}</span>}
        <span className="ml-2 text-zinc-500">
          est {node["Plan Rows"] ?? "?"} ·{" "}
          <span className={misestimated(node) ? "font-semibold text-amber-400" : ""}>
            actual {node["Actual Rows"] ?? "?"}{loops > 1 ? ` ×${loops}` : ""}
          </span>
          {node["Actual Total Time"] !== undefined && ` · ${node["Actual Total Time"]} ms`}
          {(node["Shared Hit Blocks"] !== undefined || node["Shared Read Blocks"] !== undefined) &&
            ` · buffers hit ${node["Shared Hit Blocks"] ?? 0} read ${node["Shared Read Blocks"] ?? 0}`}
        </span>
      </summary>
      {(node.Filter || node["Index Cond"]) && (
        <p className="ml-4 font-mono text-[11px] text-zinc-500">
          {node["Index Cond"] ? `Index Cond: ${node["Index Cond"]}` : `Filter: ${node.Filter}`}
          {node["Rows Removed by Filter"] ? ` (removed ${node["Rows Removed by Filter"]})` : ""}
        </p>
      )}
      {node.Plans?.map((child, i) => <Node key={i} node={child} depth={depth + 1} />)}
    </details>
  );
}

export function PlanTree({ plan }: { plan: { Plan: PlanNode; "Execution Time"?: number; "Planning Time"?: number } }) {
  return (
    <div className="rounded border border-zinc-800 bg-zinc-900/60 p-2">
      <p className="mb-1 text-xs text-zinc-400">
        EXPLAIN · execution {plan["Execution Time"] ?? "?"} ms · planning {plan["Planning Time"] ?? "?"} ms
      </p>
      <Node node={plan.Plan} depth={0} />
      <details className="mt-1">
        <summary className="cursor-pointer text-[11px] text-zinc-500">raw JSON</summary>
        <pre className="max-h-64 overflow-auto text-[11px]">{JSON.stringify(plan, null, 2)}</pre>
      </details>
    </div>
  );
}
