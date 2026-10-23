// Typed client for the FastAPI router (backend/tutor/router.py), mounted at apiBase.
import { SseParser } from "./sse";
import type {
  IncidentScalar, IncidentState, LabInfo, LabSqlResult, LedgerEntry, Session, StreamEvent, TranscriptRow, VoiceInfo,
} from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export class TutorApi {
  constructor(private apiBase: string, private token: () => Promise<string | null>) {}

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const token = await this.token();
    const res = await fetch(`${this.apiBase}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new ApiError(res.status, typeof body.detail === "string" ? body.detail : res.statusText);
    }
    return res.json() as Promise<T>;
  }

  createSession(body: Partial<Pick<Session, "objective" | "mode" | "language" | "persona_on" | "delivery">> = {}) {
    return this.request<Session>("/session", { method: "POST", body: JSON.stringify(body) });
  }
  getSession(id: string) {
    return this.request<Session & { transcript: TranscriptRow[] }>(`/session/${id}`);
  }
  /** The learner edits the incident model: set/clear a field, add evidence (value) or remove evidence (index). */
  editIncident(sessionId: string, body: { field: IncidentScalar | "evidence"; value?: string | null; index?: number }) {
    return this.request<{ incident: IncidentState }>(`/session/${sessionId}/incident`,
      { method: "PATCH", body: JSON.stringify(body) });
  }
  ledger() {
    return this.request<{ entries: LedgerEntry[] }>("/ledger");
  }
  voiceInfo() {
    return this.request<VoiceInfo>("/voice");
  }
  /** Signed URL to the cached server audio of a tutor turn's `speech` track (503: use the browser voice). */
  voiceSpeech(turnId: string) {
    return this.request<{ url: string; voice: string; cached: boolean }>("/voice/speech",
      { method: "POST", body: JSON.stringify({ turn_id: turnId }) });
  }
  labs() {
    return this.request<{ labs: LabInfo[] }>("/labs");
  }
  labAction(sessionId: string, slug: string,
            action: "install" | "reset" | "status" | "hint" | "check" | "reproduce") {
    return this.request<Record<string, unknown>>(`/lab/${slug}/${action}?session_id=${sessionId}`, { method: "POST" });
  }
  labSql(body: { session_id: string; sql: string; role: string; claims?: Record<string, unknown> | null;
                 explain?: boolean; persist?: boolean }) {
    return this.request<LabSqlResult>("/lab/sql", { method: "POST", body: JSON.stringify(body) });
  }

  /** Stream one tutor turn; calls onEvent for every SSE event in order. */
  async turn(sessionId: string, text: string, onEvent: (e: StreamEvent) => void,
             inputMode: "text" | "voice" = "text", signal?: AbortSignal) {
    const token = await this.token();
    const res = await fetch(`${this.apiBase}/turn`, {
      method: "POST",
      signal,
      headers: { "Content-Type": "application/json", Accept: "text/event-stream",
                 ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: JSON.stringify({ session_id: sessionId, text, input_mode: inputMode }),
    });
    if (!res.ok || !res.body) {
      const body = await res.json().catch(() => ({}));
      throw new ApiError(res.status, typeof body.detail === "string" ? body.detail : res.statusText);
    }
    const parser = new SseParser();
    const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      for (const event of parser.feed(value)) onEvent(event);
    }
  }
}
