import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { t } from "../i18n";
import type { IncidentState } from "../types";
import { IncidentPanel } from "./IncidentPanel";
import { incidentMarkdown, missingFields, progress } from "./incidentModel";

const state: IncidentState = {
  model: {
    symptom: "API langsam", scope: "nur Org A", evidence: ["CPU 91%"],
    hypotheses: [{ h: "fehlender Index", rank: 1, test: "EXPLAIN ANALYZE", status: "supported" },
                 { h: "Lock", rank: 2, status: "falsified" }],
  },
  sources: { symptom: "tutor", scope: "learner", "evidence:0": "tutor" },
  conflicts: [{ field: "scope", learner: "nur Org A", tutor: "alle Orgs" }],
};

test("progress, next missing field and the Markdown write-up", () => {
  expect(missingFields(state)[0]).toBe("expected");
  expect(progress(state)).toEqual({ filled: 4, total: 12 });
  const md = incidentMarkdown(state, "de");
  expect(md).toContain("**Symptom:** API langsam");
  expect(md).toContain("1. fehlender Index (supported) — test: EXPLAIN ANALYZE");
  expect(md).toContain("**Ursache:** —");
});

test("shows who filled what, the conflict and the next field; the learner can edit and add evidence", async () => {
  const onEdit = vi.fn(async () => undefined);
  render(<IncidentPanel state={state} lang="de" s={t("de")} onEdit={onEdit} />);
  expect(screen.getByText("4/12 erfasst")).toBeTruthy();
  expect(screen.getByText("du")).toBeTruthy();  // scope came from the learner
  expect(screen.getByText(/Das Känguru schlägt etwas anderes vor: alle Orgs/)).toBeTruthy();
  expect(screen.getAllByText("als Nächstes")).toHaveLength(1);
  expect(screen.getByText("(widerlegt)")).toBeTruthy();

  fireEvent.click(screen.getAllByRole("button", { name: "bearbeiten" })[1]);  // expected behaviour
  fireEvent.change(screen.getByRole("textbox", { name: "Erwartetes Verhalten" }), { target: { value: "< 200 ms" } });
  fireEvent.click(screen.getByRole("button", { name: "speichern" }));
  await waitFor(() => expect(onEdit).toHaveBeenCalledWith({ field: "expected", value: "< 200 ms" }));

  fireEvent.change(screen.getByRole("textbox", { name: "Evidenz hinzufügen" }), { target: { value: "p95 2.3 s" } });
  fireEvent.click(screen.getByRole("button", { name: "+" }));
  await waitFor(() => expect(onEdit).toHaveBeenCalledWith({ field: "evidence", value: "p95 2.3 s" }));
  fireEvent.click(screen.getByRole("button", { name: "entfernen 1" }));
  expect(onEdit).toHaveBeenCalledWith({ field: "evidence", index: 0 });
});

test("without an incident it explains how to start one", () => {
  render(<IncidentPanel state={null} lang="en" s={t("en")} onEdit={vi.fn()} />);
  expect(screen.getByText(/No incident yet/)).toBeTruthy();
});
