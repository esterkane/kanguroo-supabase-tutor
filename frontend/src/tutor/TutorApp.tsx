import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { ApiError, TutorApi } from "./api";
import type { AuthClient, AuthSession } from "./auth/authClient";
import { LoginForm } from "./auth/LoginForm";
import { ChatPanel, type InputMode } from "./chat/ChatPanel";
import { chatReducer, initialChat } from "./chatReducer";
import { t } from "./i18n";
import { type IncidentEditFn, IncidentPanel } from "./incident/IncidentPanel";
import { consolePreset, LabConsole } from "./lab/LabConsole";
import { type LabOutput, LabsPanel } from "./sidebar/LabsPanel";
import { Ledger } from "./sidebar/Ledger";
import { LessonSidebar } from "./sidebar/LessonSidebar";
import type { IncidentState, LedgerEntry, Session, TutorTurn } from "./types";
import type { ServerTts } from "./voice/useSpeech";

export interface TutorAppProps {
  /** Standalone: the Supabase client (created in main.tsx); the learner signs in with it. */
  supabase?: AuthClient;
  /** Mounted in a host app (AuDHS ADR 0021): the host's backend vouches for this learner; no login, no token. */
  host?: { userId: string };
  /** Base path of the mounted FastAPI router, e.g. "/tutor" standalone or "/api/kaenguru" in AuDHS. */
  apiBase: string;
  /** Ask "explicit or Socratic?" at the start of each session (default: on in host mode, explicit first). */
  deliveryChoice?: boolean;
}

export type Delivery = "socratic" | "explicit";

type Tab = "lesson" | "incident" | "lab" | "ledger";
const lastSessionKey = (userId: string) => `kaenguru.session.${userId}`;

function readLastSession(userId: string): string | null {
  try {
    return localStorage.getItem(lastSessionKey(userId));
  } catch {
    return null;
  }
}

function writeLastSession(userId: string, sessionId: string) {
  try {
    localStorage.setItem(lastSessionKey(userId), sessionId);
  } catch {
    // private mode etc.: the session just won't be resumed
  }
}

/** "How should the kangaroo explain today?" Explicit first: it is the default where a host asks (AuDHS rule). */
function DeliveryChooser({ s, onChoose, onCancel }: {
  s: ReturnType<typeof t>; onChoose: (d: Delivery) => void; onCancel?: () => void;
}) {
  const options: [Delivery, string, string][] = [
    ["explicit", s.deliveryExplicit, s.deliveryExplicitHint], ["socratic", s.deliverySocratic, s.deliverySocraticHint],
  ];
  return (
    <section aria-label={s.deliveryTitle} className="col-span-full mx-auto mt-16 w-full max-w-md space-y-3 px-4">
      <h2 className="text-sm font-semibold">{s.deliveryTitle}</h2>
      {options.map(([value, label, hint]) => (
        <button key={value} type="button" onClick={() => onChoose(value)}
                className="block w-full rounded border border-zinc-700 p-3 text-left hover:border-sky-600">
          <span className="block text-sm">{label}</span>
          <span className="block text-xs text-zinc-400">{hint}</span>
        </button>
      ))}
      {onCancel && <button type="button" onClick={onCancel} className="text-xs text-zinc-500 hover:text-zinc-200">{s.cancel}</button>}
    </section>
  );
}

export function TutorApp({ supabase, host, apiBase, deliveryChoice = !!host }: TutorAppProps) {
  const hostSession = useMemo<AuthSession | null>(() => (host ? { access_token: "", user: { id: host.userId } } : null),
                                                   [host]);
  const [auth, setAuth] = useState<AuthSession | null>(hostSession);
  const [authReady, setAuthReady] = useState(!!host);
  const [choosing, setChoosing] = useState(false);  // delivery choice shown before a new session starts
  const [session, setSession] = useState<Session | null>(null);
  const [chat, dispatch] = useReducer(chatReducer, initialChat);
  const [ledger, setLedger] = useState<LedgerEntry[]>([]);
  const [tab, setTab] = useState<Tab>("lesson");
  const [fatal, setFatal] = useState<string | null>(null);
  const [handover, setHandover] = useState<LabOutput | null>(null);
  const [serverTts, setServerTts] = useState<ServerTts | null>(null);
  const [incident, setIncident] = useState<IncidentState | null>(null);
  const [incidentChanged, setIncidentChanged] = useState<string[]>([]);
  const authRef = useRef<AuthSession | null>(null);

  useEffect(() => {
    if (!supabase) return;  // host mode: the identity comes from the host
    supabase.auth.getSession().then(({ data }) => {
      setAuth(data.session);
      setAuthReady(true);
    });
    const { data } = supabase.auth.onAuthStateChange((_event, next) => setAuth(next));
    return () => data.subscription.unsubscribe();
  }, [supabase]);
  authRef.current = auth;

  const api = useMemo(() => new TutorApi(apiBase, async () => {
    if (!supabase) return null;  // host mode: the host backend authenticates the request
    const { data } = await supabase.auth.getSession();  // refreshes an expired access token
    return data.session?.access_token ?? authRef.current?.access_token ?? null;
  }), [apiBase, supabase]);

  const userId = auth?.user.id;
  const s = t(session?.language ?? "de");

  const startSession = useCallback(async (delivery: Delivery = "socratic") => {
    if (!userId) return;
    setChoosing(false);
    const created = await api.createSession({ delivery });
    writeLastSession(userId, created.id);
    setSession(created);
    setIncident(null);
    dispatch({ type: "reset" });
  }, [api, userId]);

  useEffect(() => {
    if (!userId) {
      setSession(null);
      return;
    }
    const resume = readLastSession(userId);
    (resume
      ? api.getSession(resume).then((full) => {
          setSession(full);
          setIncident(full.incident ?? null);
          dispatch({ type: "load", rows: full.transcript });
        })
      : Promise.reject(new ApiError(404, "no session"))
    ).catch((e) => (e instanceof ApiError && e.status === 404
      ? (deliveryChoice ? setChoosing(true) : startSession())
      : setFatal(String(e))));
    api.ledger().then((r) => setLedger(r.entries)).catch(() => undefined);
    api.voiceInfo().then((info) => setServerTts(info.tts === "server" ? {
      voices: info.voices, speechUrl: (turnId) => api.voiceSpeech(turnId).then((r) => r.url),
    } : null)).catch(() => setServerTts(null));  // browser voices only
  }, [api, userId, startSession, deliveryChoice]);

  const send = useCallback(async (text: string, inputMode: InputMode = "text") => {
    if (!session) return;
    dispatch({ type: "send", id: crypto.randomUUID(), text });
    try {
      await api.turn(session.id, text, (event) => {
        dispatch({ type: "stream", event });
        if (event.event === "lab" && event.data.result.ok !== false) {
          setHandover({ slug: event.data.slug, action: event.data.action, body: event.data.result });
          setTab("lab");
        }
        if (event.event === "mode") {  // the first message was a customer problem: incident mode, no onboarding
          setSession((prev) => (prev ? { ...prev, mode: event.data.mode } : prev));
          if (event.data.mode === "incident") setTab("incident");
        }
        if (event.event === "incident") {
          setIncident((prev) => {
            if (!prev) setTab("incident");  // the first incident turn opens the form
            return event.data.incident;
          });
          setIncidentChanged(event.data.changed);
        }
      }, inputMode);
      api.ledger().then((r) => setLedger(r.entries)).catch(() => undefined);
    } catch (e) {
      dispatch({ type: "fail", message: e instanceof ApiError && e.status === 503 ? s.noKey : String(e) });
    }
  }, [api, session, s.noKey]);

  const editIncident: IncidentEditFn = useCallback(async (body) => {
    if (!session) return;
    try {
      setIncident((await api.editIncident(session.id, body)).incident);
      setIncidentChanged([]);
    } catch (e) {
      dispatch({ type: "fail", message: String(e) });
    }
  }, [api, session]);

  if (!authReady) return null;
  if (!auth) return supabase ? <LoginForm supabase={supabase} s={s} /> : null;

  const lastTurn: TutorTurn | null =
    [...chat.items].reverse().find((i) => i.kind === "tutor")?.turn ?? null;
  const busy = chat.streaming !== null;
  const showIncident = incident !== null || session?.mode === "incident" || lastTurn?.mode === "incident";

  return (
    <div className="grid h-screen grid-cols-1 grid-rows-[auto_1fr] text-sm md:grid-cols-[1fr_380px]">
      <header className="col-span-full flex items-center gap-3 border-b border-zinc-800 px-3 py-2">
        <h1 className="font-semibold">{s.title}</h1>
        {session && <span className="truncate text-xs text-zinc-500">{session.objective ?? session.id.slice(0, 8)}</span>}
        <button type="button" onClick={() => (deliveryChoice ? setChoosing(true) : startSession())} disabled={busy}
                className="ml-auto rounded border border-zinc-700 px-2 py-0.5 text-xs hover:border-sky-600">{s.newSession}</button>
        {supabase && (
          <button type="button" onClick={() => supabase.auth.signOut()}
                  className="rounded border border-zinc-700 px-2 py-0.5 text-xs hover:border-sky-600">{s.signOut}</button>
        )}
      </header>
      {fatal && <p role="alert" className="col-span-full p-3 text-red-400">{fatal}</p>}
      {choosing && (
        <DeliveryChooser s={s} onChoose={startSession} onCancel={session ? () => setChoosing(false) : undefined} />
      )}
      {session && !choosing && (
        <>
          <main className="flex min-h-0 flex-col border-r border-zinc-800">
            <ChatPanel chat={chat} s={s} language={session.language} onSend={send} serverTts={serverTts} />
          </main>
          <aside className="flex min-h-0 flex-col">
            <nav className="flex border-b border-zinc-800 text-xs" role="tablist">
              {(["lesson", ...(showIncident ? ["incident"] : []), "lab", "ledger"] as Tab[]).map((key) => (
                <button key={key} type="button" role="tab" aria-selected={tab === key} onClick={() => setTab(key)}
                        className={`flex-1 px-2 py-1.5 ${tab === key ? "border-b-2 border-sky-500 text-zinc-100" : "text-zinc-500"}`}>
                  {key === "lesson" ? s.lesson : key === "incident" ? s.incident : key === "lab" ? s.labs : s.ledger}
                </button>
              ))}
            </nav>
            <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-3">
              {tab === "lesson" && (
                <LessonSidebar session={session} lastTurn={lastTurn} s={s} onCommand={send} busy={busy} />
              )}
              {tab === "incident" && (
                <IncidentPanel state={incident} lang={session.language} s={s} onEdit={editIncident}
                               changed={incidentChanged} />
              )}
              {tab === "lab" && (
                <>
                  <LabsPanel api={api} sessionId={session.id} s={s} handover={handover} />
                  <h2 className="text-xs uppercase tracking-wide text-zinc-500">{s.console}</h2>
                  <LabConsole key={handover ? `${handover.slug}-${handover.action}` : "console"} api={api}
                              sessionId={session.id} s={s} onSend={send}
                              preset={typeof handover?.body.scenario === "string" ? consolePreset(handover.body.scenario) : null} />
                </>
              )}
              {tab === "ledger" && <Ledger entries={ledger} s={s} onReview={(topic) => send(`recap ${topic}`)} />}
            </div>
          </aside>
        </>
      )}
    </div>
  );
}
