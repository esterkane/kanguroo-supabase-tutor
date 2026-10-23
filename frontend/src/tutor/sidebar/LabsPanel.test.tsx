import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { TutorApi } from "../api";
import { t } from "../i18n";
import { LabsPanel } from "./LabsPanel";

test("labs that declare a reproduce step get a reproduce button that calls the lab action", async () => {
  const labAction = vi.fn(async () => ({ ok: false, stage: "connect", sqlstate: "53300", reproduced_as: "lab07_app",
                                         application_name: "orders-api", ms: 4,
                                         message: 'FATAL:  too many connections for role "lab07_app"' }));
  const api = {
    labs: async () => ({ labs: [
      { slug: "02-wrong-jwt-identity", phase: "D", title: "x", requires: ["olist"], reproducible: false },
      { slug: "07-connection-exhaustion", phase: "J", title: "y", requires: ["olist"], reproducible: true },
    ] }),
    labAction,
  } as unknown as TutorApi;
  render(<LabsPanel api={api} sessionId="s1" s={t("de")} />);
  const buttons = await screen.findAllByRole("button", { name: "nachstellen" });
  expect(buttons).toHaveLength(1);
  fireEvent.click(buttons[0]);
  await waitFor(() => expect(labAction).toHaveBeenCalledWith("s1", "07-connection-exhaustion", "reproduce"));
  expect(await screen.findByText(/connect: 53300 FATAL: too many connections for role "lab07_app"/)).toBeTruthy();
});
