// Chat state as a pure reducer: easy to test, independent of React.
import type { StreamEvent, TranscriptRow, TutorTurn } from "./types";

export type ChatItem =
  | { kind: "user"; id: string; text: string }
  | { kind: "tutor"; id: string; turn: TutorTurn }
  | { kind: "notice"; id: string; text: string };

export interface ToolActivity {
  name: string;
  input: Record<string, unknown>;
  done?: boolean;
  isError?: boolean;
  summary?: string;
}

export interface ChatState {
  items: ChatItem[];
  streaming: { text: string; tools: ToolActivity[]; rewrites: string[][] } | null;
  error: string | null;
}

export type ChatAction =
  | { type: "load"; rows: TranscriptRow[] }
  | { type: "send"; id: string; text: string }
  | { type: "stream"; event: StreamEvent }
  | { type: "fail"; message: string }
  | { type: "reset" };

export const initialChat: ChatState = { items: [], streaming: null, error: null };

export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case "reset":
      return initialChat;
    case "load":
      return {
        ...initialChat,
        items: action.rows.map((r): ChatItem =>
          r.role === "assistant" && r.tutor_turn
            ? { kind: "tutor", id: r.id, turn: r.tutor_turn }
            : { kind: "user", id: r.id, text: r.content }),
      };
    case "send":
      return { items: [...state.items, { kind: "user", id: action.id, text: action.text }],
               streaming: { text: "", tools: [], rewrites: [] }, error: null };
    case "fail":
      return { ...state, streaming: null, error: action.message };
    case "stream": {
      const s = state.streaming ?? { text: "", tools: [], rewrites: [] };
      const e = action.event;
      switch (e.event) {
        case "token":
          return { ...state, streaming: { ...s, text: s.text + e.data.text } };
        case "tool_call":
          return { ...state, streaming: { ...s, tools: [...s.tools, { name: e.data.name, input: e.data.input }] } };
        case "tool_result_summary": {
          const tools = [...s.tools];
          const i = tools.map((x) => x.name).lastIndexOf(e.data.name);
          if (i >= 0) tools[i] = { ...tools[i], done: true, isError: e.data.is_error, summary: e.data.summary };
          return { ...state, streaming: { ...s, tools } };
        }
        case "rewrite":  // the guard rejected what streamed so far; the rewrite streams next
          return { ...state, streaming: { ...s, text: "", rewrites: [...s.rewrites, e.data.codes] } };
        case "turn":
          return { items: [...state.items, { kind: "tutor", id: e.data.turn_id, turn: e.data.turn }],
                   streaming: null, error: null };
        case "lab": {  // the app ran the turn's lab_action (e.g. onboarding handover of lab 01)
          const ok = e.data.result.ok !== false;
          const text = ok ? `lab ${e.data.action}: ${e.data.slug}` : `lab ${e.data.action} failed: ${e.data.slug}`;
          return { ...state, items: [...state.items, { kind: "notice", id: `lab-${state.items.length}`, text }] };
        }
        case "error":
          return { ...state, streaming: null, error: e.data.message };
      }
    }
  }
  return state;
}
