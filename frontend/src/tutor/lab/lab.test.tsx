import { render, screen } from "@testing-library/react";
import { resultSummary } from "./LabConsole";
import { PlanTree } from "./PlanTree";

test("result summary is evidence the tutor can read", () => {
  const md = resultSummary("select 1", "authenticated", "1111", { ok: false, sqlstate: "42501",
    message: "permission denied for table orders", hint: "grant select" });
  expect(md).toContain("Rolle authenticated, sub 1111");
  expect(md).toContain("```sql\nselect 1\n```");
  expect(md).toContain("Fehler 42501: permission denied for table orders (Hint: grant select)");
  const rows = resultSummary("select n", "postgres", "", { ok: true, rows: [{ n: 20 }], ms: 1.2 });
  expect(rows).toContain("| n |\n|---|\n| 20 |");
});

test("plan tree highlights misestimates and shows buffers", () => {
  render(<PlanTree plan={{ "Execution Time": 37.6, Plan: {
    "Node Type": "Limit", "Plan Rows": 20, "Actual Rows": 20, Plans: [{
      "Node Type": "Seq Scan", "Relation Name": "orders", "Plan Rows": 5, "Actual Rows": 340,
      "Shared Hit Blocks": 120, "Shared Read Blocks": 30650, "Rows Removed by Filter": 1988480,
      Filter: "(customer_unique_id = 'x')",
    }] } }} />);
  expect(screen.getByText(/execution 37.6 ms/)).toBeTruthy();
  const actual = screen.getByText("actual 340");
  expect(actual.className).toContain("text-amber-400");  // 68x more rows than estimated
  expect(screen.getByText("actual 20").className).not.toContain("text-amber-400");
  expect(screen.getByText(/buffers hit 120 read 30650/)).toBeTruthy();
  expect(screen.getByText(/removed 1988480/)).toBeTruthy();
});
