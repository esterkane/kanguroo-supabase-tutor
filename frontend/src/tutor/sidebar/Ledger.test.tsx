import { render, screen, within } from "@testing-library/react";
import { t } from "../i18n";
import type { LedgerEntry, TutorTurn } from "../types";
import { TurnView } from "../chat/TurnView";
import { Ledger } from "./Ledger";

const NOW = Date.parse("2026-10-23T12:00:00Z");
const e = (topic: string, score: number, next_review: string | null): LedgerEntry =>
  ({ topic, phase: "D", title: topic, score, evidence: null, last_reviewed: "2026-10-20T00:00:00Z", next_review });

test("due reviews come first, most overdue on top, with a due badge; others show their date", () => {
  render(<Ledger s={t("de")} onReview={vi.fn()} now={NOW} entries={[
    e("weak-not-due", 1, "2026-11-02T00:00:00Z"), e("due-recent", 4, "2026-10-22T00:00:00Z"),
    e("due-long-ago", 3, "2026-10-01T00:00:00Z"), e("never", 0, null)]} />);
  const rows = screen.getAllByRole("listitem").map((li) => li.textContent ?? "");
  expect(rows.map((r) => r.split(/fällig|2026|wiederholen/)[0])).toEqual(["due-long-ago", "due-recent", "never", "weak-not-due"]);
  expect(screen.getAllByText("fällig")).toHaveLength(2);
  expect(screen.getByText("2026-11-02")).toBeTruthy();
});

test("a turn with session_end shows the five headings", () => {
  const turn = { mode: "lesson", language: "de", persona_on: true, speech: "s", text: "Schluss.", diagrams: [],
    citations: [], ledger_delta: [], guard_flags: [], session_end: {
      understand: ["GRANT vor RLS"], proved: [], still_wrong: ["Reihenfolge"],
      retrieval_questions: ["F1?", "F2?", "F3?"], next_case: "Insert klappt für anon, nicht für authenticated." },
  } as TutorTurn;
  render(<TurnView turn={turn} s={t("de")} />);
  const card = screen.getByRole("region", { name: "Sitzungsende" });
  for (const heading of ["Was du jetzt verstehen solltest", "Was du im Lab bewiesen hast", "Was noch nicht stimmt",
                         "Drei Abruffragen", "Ein Support-Fall zum Nachdenken"]) {
    expect(within(card).getByText(heading)).toBeTruthy();
  }
  expect(within(card).getByText("nichts")).toBeTruthy();  // nothing proved in the lab
  expect(within(card).getAllByRole("listitem")).toHaveLength(5);
});
