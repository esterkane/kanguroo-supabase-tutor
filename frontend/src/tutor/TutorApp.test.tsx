import { render, screen } from "@testing-library/react";
import { TutorApp } from "./TutorApp";

test("renders the shell and starts a health check", () => {
  globalThis.fetch = vi.fn(() => new Promise<Response>(() => {}));
  render(<TutorApp apiBase="/tutor" />);
  expect(screen.getByText("Känguru Tutor")).toBeTruthy();
  expect(screen.getByTestId("health").textContent).toContain("checking");
  expect(globalThis.fetch).toHaveBeenCalledWith("/healthz");
});
