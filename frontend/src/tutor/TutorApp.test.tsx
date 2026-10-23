import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { SupabaseClient } from "@supabase/supabase-js";
import { TutorApp } from "./TutorApp";

function fakeSupabase(signedIn: boolean): SupabaseClient {
  const session = signedIn ? { access_token: "tok", user: { id: "user-1" } } : null;
  return {
    auth: {
      getSession: async () => ({ data: { session } }),
      onAuthStateChange: () => ({ data: { subscription: { unsubscribe() {} } } }),
      signInWithPassword: async () => ({ error: null }),
      signOut: async () => ({ error: null }),
    },
  } as unknown as SupabaseClient;
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

function sse(...events: [string, unknown][]) {
  const text = events.map(([e, d]) => `event: ${e}\r\ndata: ${JSON.stringify(d)}\r\n\r\n`).join("");
  return new Response(new ReadableStream({ start(c) { c.enqueue(new TextEncoder().encode(text)); c.close(); } }),
                      { headers: { "Content-Type": "text/event-stream" } });
}

afterEach(() => vi.restoreAllMocks());

test("signed out shows the login form", async () => {
  render(<TutorApp supabase={fakeSupabase(false)} apiBase="/tutor" />);
  expect(await screen.findByRole("button", { name: "Anmelden" })).toBeTruthy();
});

test("signed in: creates a session, streams a turn and renders it with sources", async () => {
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push(`${init?.method ?? "GET"} ${url}`);
    expect((init?.headers as Record<string, string>).Authorization).toBe("Bearer tok");
    if (url === "/tutor/session") return json({ id: "s1", objective: null, mode: "lesson", language: "de",
                                                persona_on: true, started_at: "now" }, 201);
    if (url === "/tutor/ledger") return json({ entries: [] });
    if (url === "/tutor/turn") return sse(
      ["token", { text: "Kleinkünstler, " }],
      ["tool_call", { name: "search_docs", input: { query: "42501" } }],
      ["turn", { turn_id: "t1", model: "m", usage: {}, turn: {
        mode: "lesson", language: "de", persona_on: true, speech: "s", diagrams: [], ledger_delta: [],
        guard_flags: [], next_question: "Welche Kontrolle?",
        text: "Kleinkünstler, GRANT zuerst [1].\n\nWelche Kontrolle?",
        citations: [{ n: 1, url: "https://supabase.com/docs/guides/x.md", title: "42501 errors", tier: 1 }] } }],
    );
    return json({ detail: "unexpected" }, 500);
  }));
  render(<TutorApp supabase={fakeSupabase(true)} apiBase="/tutor" />);
  const box = await screen.findByRole("textbox", { name: /Antwort oder Frage/ });
  fireEvent.change(box, { target: { value: "Hallo" } });
  fireEvent.click(screen.getByRole("button", { name: "Senden" }));
  await waitFor(() => expect(screen.getByText("42501 errors")).toBeTruthy());
  expect(screen.getByText("Hallo")).toBeTruthy();
  expect(screen.getByText(/GRANT zuerst/)).toBeTruthy();
  expect(calls).toContain("POST /tutor/turn");
});

test("voice: a spoken answer is sent as input_mode voice and only the speech track is read aloud", async () => {
  let rec: { onresult: ((e: unknown) => void) | null } | null = null;
  vi.stubGlobal("webkitSpeechRecognition", class {
    lang = ""; continuous = false; interimResults = false; onresult = null; onend = null; onerror = null;
    constructor() { rec = this; }
    start() {} stop() {} abort() {}
  });
  const spoken: string[] = [];
  vi.stubGlobal("speechSynthesis", { speak: (u: { text: string }) => spoken.push(u.text), cancel() {},
                                     getVoices: () => [], addEventListener() {}, removeEventListener() {} });
  vi.stubGlobal("SpeechSynthesisUtterance", class { constructor(public text: string) {} });
  const bodies: unknown[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/tutor/session") return json({ id: "s1", objective: null, mode: "lesson", language: "de",
                                                persona_on: true, started_at: "now" }, 201);
    if (url === "/tutor/ledger") return json({ entries: [] });
    if (url === "/tutor/turn") {
      bodies.push(JSON.parse(String(init?.body)));
      return sse(["turn", { turn_id: "t1", model: "m", usage: {}, turn: {
        mode: "lesson", language: "de", persona_on: true, speech: "Welche Rolle fragt hier an?", diagrams: [],
        ledger_delta: [], guard_flags: [], citations: [], text: "```sql\nselect 1;\n```\n\nWelche Rolle fragt hier an?" } }]);
    }
    return json({ detail: "unexpected" }, 500);
  }));
  try {
    localStorage.clear();
    render(<TutorApp supabase={fakeSupabase(true)} apiBase="/tutor" />);
    const mic = await screen.findByRole("button", { name: "Sprechen" });
    fireEvent.pointerDown(mic);
    rec!.onresult?.({ resultIndex: 0, results: [{ isFinal: true, 0: { transcript: "Die anon Rolle" } }] });
    fireEvent.pointerUp(mic);
    await waitFor(() => expect(spoken).toEqual(["Welche Rolle fragt hier an?"]));
    expect(bodies).toEqual([{ session_id: "s1", text: "Die anon Rolle", input_mode: "voice" }]);
    expect(screen.getByRole("button", { name: "Nochmal anhören" })).toBeTruthy();
  } finally {
    vi.unstubAllGlobals();
  }
});

test("incident: the first incident event opens the incident form with the merged model", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url === "/tutor/session") return json({ id: "s1", objective: null, mode: "lesson", language: "de",
                                                persona_on: true, started_at: "now" }, 201);
    if (url === "/tutor/ledger") return json({ entries: [] });
    if (url === "/tutor/voice") return json({ tts: "browser", voices: {} });
    if (url === "/tutor/turn") return sse(
      ["turn", { turn_id: "t1", model: "m", usage: {}, turn: {
        mode: "incident", language: "de", persona_on: true, speech: "Seit wann?", diagrams: [], ledger_delta: [],
        guard_flags: [], citations: [], next_question: "Seit wann?", text: "Erst die Fakten.\n\nSeit wann?",
        incident: { symptom: "API langsam", evidence: [], hypotheses: [] } } }],
      ["incident", { changed: ["symptom"], incident: {
        model: { symptom: "API langsam", evidence: [], hypotheses: [] }, sources: { symptom: "tutor" }, conflicts: [] } }],
    );
    return json({ detail: "unexpected" }, 500);
  }));
  try {
    localStorage.clear();
    render(<TutorApp supabase={fakeSupabase(true)} apiBase="/tutor" />);
    const box = await screen.findByRole("textbox", { name: /Antwort oder Frage/ });
    fireEvent.change(box, { target: { value: "Supabase ist langsam" } });
    fireEvent.click(screen.getByRole("button", { name: "Senden" }));
    await waitFor(() => expect(screen.getByRole("tab", { name: "Incident" }).getAttribute("aria-selected")).toBe("true"));
    expect(screen.getByText("API langsam")).toBeTruthy();
    expect(screen.getByText("1/12 erfasst")).toBeTruthy();
  } finally {
    vi.unstubAllGlobals();
  }
});

test("incident: a customer problem as first message switches the session to incident mode at once", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url === "/tutor/session") return json({ id: "s1", objective: null, mode: "lesson", language: "de",
                                                persona_on: true, started_at: "now" }, 201);
    if (url === "/tutor/ledger") return json({ entries: [] });
    if (url === "/tutor/voice") return json({ tts: "browser", voices: {} });
    if (url === "/tutor/turn") return sse(["mode", { mode: "incident", reason: "customer_problem" }]);
    return json({ detail: "unexpected" }, 500);
  }));
  try {
    localStorage.clear();
    render(<TutorApp supabase={fakeSupabase(true)} apiBase="/tutor" />);
    const box = await screen.findByRole("textbox", { name: /Antwort oder Frage/ });
    fireEvent.change(box, { target: { value: "Kunde meldet 42501 beim Insert" } });
    fireEvent.click(screen.getByRole("button", { name: "Senden" }));
    await waitFor(() => expect(screen.getByRole("tab", { name: "Incident" }).getAttribute("aria-selected")).toBe("true"));
    expect(screen.getByText(/Noch kein Incident/)).toBeTruthy();
  } finally {
    vi.unstubAllGlobals();
  }
});

test("host mode: no login, delivery choice first (explicit is the default), no token sent", async () => {
  const seen: { url: string; auth?: string; body?: unknown }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    seen.push({ url, auth: (init?.headers as Record<string, string>).Authorization,
                body: init?.body ? JSON.parse(String(init.body)) : undefined });
    if (url === "/api/kaenguru/session") return json({ id: "h1", objective: null, mode: "lesson", language: "de",
                                                       persona_on: true, delivery: "explicit", started_at: "now" }, 201);
    if (url === "/api/kaenguru/ledger") return json({ entries: [] });
    if (url === "/api/kaenguru/voice") return json({ tts: "browser", voices: {} });
    return json({ detail: "unexpected" }, 500);
  }));
  try {
    localStorage.clear();
    render(<TutorApp host={{ userId: "owner" }} apiBase="/api/kaenguru" />);
    const chooser = await screen.findByRole("region", { name: "Wie soll das Känguru in dieser Sitzung erklären?" });
    const options = within(chooser).getAllByRole("button");
    expect(options[0].textContent).toContain("Erklärend (Standard)");
    expect(screen.queryByRole("button", { name: "Anmelden" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Abmelden" })).toBeNull();
    fireEvent.click(options[0]);
    await screen.findByRole("textbox", { name: /Antwort oder Frage/ });
    expect(seen.find((r) => r.url === "/api/kaenguru/session")?.body).toEqual({ delivery: "explicit" });
    expect(seen.every((r) => r.auth === undefined)).toBe(true);
    expect(screen.getByText("Erklärend")).toBeTruthy();  // the lesson sidebar shows the session's delivery
  } finally {
    vi.unstubAllGlobals();
  }
});
