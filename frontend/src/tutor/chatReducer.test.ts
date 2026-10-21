import { chatReducer, initialChat } from "./chatReducer";
import type { TutorTurn } from "./types";

const turn = (text: string): TutorTurn => ({
  mode: "lesson", language: "de", persona_on: true, speech: "s", text, diagrams: [], citations: [],
  next_question: "Q?", path: null, ledger_delta: [], guard_flags: [],
});

test("stream: tokens, tools, rewrite clears text, final turn closes the stream", () => {
  let s = chatReducer(initialChat, { type: "send", id: "u1", text: "Hallo" });
  s = chatReducer(s, { type: "stream", event: { event: "token", data: { text: "Erst " } } });
  s = chatReducer(s, { type: "stream", event: { event: "tool_call", data: { name: "search_docs", input: { query: "rls" } } } });
  s = chatReducer(s, { type: "stream", event: { event: "tool_result_summary",
                                                 data: { name: "search_docs", is_error: false, summary: "ok" } } });
  expect(s.streaming?.tools).toEqual([{ name: "search_docs", input: { query: "rls" }, done: true, isError: false, summary: "ok" }]);
  s = chatReducer(s, { type: "stream", event: { event: "rewrite", data: { codes: ["UNCITED_CLAIM"] } } });
  expect(s.streaming?.text).toBe("");
  expect(s.streaming?.rewrites).toEqual([["UNCITED_CLAIM"]]);
  s = chatReducer(s, { type: "stream", event: { event: "turn",
    data: { turn_id: "t1", turn: turn("Final"), usage: {}, model: "m" } } });
  expect(s.streaming).toBeNull();
  expect(s.items.map((i) => i.kind)).toEqual(["user", "tutor"]);
});

test("error ends the stream and load rebuilds the transcript", () => {
  let s = chatReducer(initialChat, { type: "send", id: "u1", text: "Hallo" });
  s = chatReducer(s, { type: "stream", event: { event: "error", data: { status: 529, message: "overloaded" } } });
  expect(s).toMatchObject({ streaming: null, error: "overloaded" });
  s = chatReducer(s, { type: "load", rows: [
    { id: "1", role: "user", content: "Hallo", tutor_turn: null },
    { id: "2", role: "assistant", content: "x", tutor_turn: turn("Antwort") },
  ] });
  expect(s.items).toEqual([{ kind: "user", id: "1", text: "Hallo" }, { kind: "tutor", id: "2", turn: turn("Antwort") }]);
  expect(s.error).toBeNull();
});

test("lab event adds a notice after the turn", () => {
  const s = chatReducer(initialChat, { type: "stream", event: { event: "lab",
    data: { slug: "01-rls-vs-grant", action: "install", result: { ok: true } } } });
  expect(s.items).toEqual([{ kind: "notice", id: "lab-0", text: "lab install: 01-rls-vs-grant" }]);
});
