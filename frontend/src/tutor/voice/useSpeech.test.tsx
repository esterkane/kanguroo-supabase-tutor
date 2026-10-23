import { act, renderHook } from "@testing-library/react";
import { useSpeech } from "./useSpeech";

class FakeRecognition {
  static last: FakeRecognition | null = null;
  lang = "";
  continuous = false;
  interimResults = false;
  onresult: ((e: unknown) => void) | null = null;
  onend: (() => void) | null = null;
  onerror: ((e: { error: string }) => void) | null = null;
  started = 0;
  stopped = 0;
  constructor() { FakeRecognition.last = this; }
  start() { this.started++; }
  stop() { this.stopped++; }
  abort() {}
  emit(results: [string, boolean][]) {
    this.onresult?.({ resultIndex: 0, results: results.map(([t, isFinal]) => ({ isFinal, 0: { transcript: t } })) });
  }
}

const spoken: SpeechSynthesisUtterance[] = [];
const synth = {
  speak: vi.fn((u: SpeechSynthesisUtterance) => spoken.push(u)),
  cancel: vi.fn(),
  getVoices: () => [{ name: "Petra", lang: "de-DE", localService: true, default: false }],
  addEventListener: vi.fn(),
  removeEventListener: vi.fn(),
};

class FakeUtterance {
  lang = ""; rate = 1; pitch = 1; voice: unknown = null;
  onstart: (() => void) | null = null; onend: (() => void) | null = null; onerror: (() => void) | null = null;
  constructor(public text: string) {}
}

beforeEach(() => {
  spoken.length = 0;
  vi.useFakeTimers();
  vi.stubGlobal("webkitSpeechRecognition", FakeRecognition);
  vi.stubGlobal("speechSynthesis", synth);
  vi.stubGlobal("SpeechSynthesisUtterance", FakeUtterance);
  localStorage.clear();
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

test("push-to-talk sends the final transcript when released, in the session language", () => {
  const onFinal = vi.fn();
  const { result } = renderHook(() => useSpeech("de", onFinal));
  expect(result.current.support).toEqual({ stt: true, tts: true });
  act(() => result.current.startListening("push"));
  const rec = FakeRecognition.last!;
  expect([rec.lang, rec.interimResults]).toEqual(["de-DE", true]);
  act(() => rec.emit([["Die Policy", true], [" fehlt", false]]));
  expect(result.current.interim).toBe("Die Policy fehlt");
  act(() => result.current.stopListening());
  expect(onFinal).toHaveBeenCalledWith("Die Policy");
  expect(result.current.mode).toBe("off");
});

test("hands-free sends after 1.2 s of silence and keeps listening when the browser ends recognition", () => {
  const onFinal = vi.fn();
  const { result } = renderHook(() => useSpeech("en", onFinal));
  act(() => result.current.startListening("handsfree"));
  const rec = FakeRecognition.last!;
  act(() => rec.emit([["the grant is missing", true]]));
  act(() => vi.advanceTimersByTime(1100));
  expect(onFinal).not.toHaveBeenCalled();
  act(() => vi.advanceTimersByTime(200));
  expect(onFinal).toHaveBeenCalledWith("the grant is missing");
  act(() => rec.onend?.());
  expect(rec.started).toBe(2);
});

test("speaks only cleaned speech with the kangaroo voice settings; mute and barge-in cancel", async () => {
  const { result } = renderHook(() => useSpeech("de", vi.fn()));
  await act(() => result.current.speak("Schau auf `GRANT` https://x.y"));
  expect(spoken).toHaveLength(1);
  const u = spoken[0] as unknown as FakeUtterance;
  expect([u.text, u.lang, u.rate, u.pitch]).toEqual(["Schau auf GRANT", "de-DE", 0.95, 0.85]);
  expect((u.voice as { name: string }).name).toBe("Petra");

  synth.cancel.mockClear();
  act(() => result.current.startListening("push"));  // the learner starts talking
  expect(synth.cancel).toHaveBeenCalled();
  act(() => result.current.stopListening(false));

  act(() => result.current.setMuted(true));
  await act(() => result.current.speak("Noch was"));
  expect(spoken).toHaveLength(1);
  expect(localStorage.getItem("kaenguru.voice.muted")).toBe("1");
});

test("a denied microphone stops listening and reports why", () => {
  const { result } = renderHook(() => useSpeech("de", vi.fn()));
  act(() => result.current.startListening("handsfree"));
  act(() => FakeRecognition.last!.onerror?.({ error: "not-allowed" }));
  expect([result.current.mode, result.current.micError]).toEqual(["off", "not-allowed"]);
});

test("without SpeechRecognition the mic is unsupported but speech output still works", () => {
  vi.stubGlobal("webkitSpeechRecognition", undefined);
  const { result } = renderHook(() => useSpeech("de", vi.fn()));
  expect(result.current.support).toEqual({ stt: false, tts: true });
  act(() => result.current.startListening("push"));
  expect(result.current.mode).toBe("off");
});

class FakeAudio {
  static played: string[] = [];
  onplay: (() => void) | null = null; onended: (() => void) | null = null; onerror: (() => void) | null = null;
  paused = false;
  constructor(public src: string) {}
  async play() { FakeAudio.played.push(this.src); this.onplay?.(); }
  pause() { this.paused = true; }
}

describe("server voice (Piper)", () => {
  beforeEach(() => {
    FakeAudio.played = [];
    vi.stubGlobal("Audio", FakeAudio);
  });

  test("is the default choice for its language and plays the turn's signed URL", async () => {
    const speechUrl = vi.fn(async (id: string) => `http://storage/sign/${id}.mp3?token=t`);
    const { result } = renderHook(() => useSpeech("de", vi.fn(), { voices: { de: "de_DE-thorsten-high" }, speechUrl }));
    expect(result.current.voiceOptions[0]).toEqual({ value: "server:de_DE-thorsten-high", label: "Thorsten", server: true });
    expect(result.current.voiceName).toBe("server:de_DE-thorsten-high");
    await act(() => result.current.speak("Welche Rolle?", "turn-1"));
    expect(speechUrl).toHaveBeenCalledWith("turn-1");
    expect(FakeAudio.played).toEqual(["http://storage/sign/turn-1.mp3?token=t"]);
    expect(spoken).toHaveLength(0);
    expect(result.current.speaking).toBe(true);
  });

  test("falls back to the browser voice when the server fails, and for languages without a server voice", async () => {
    const speechUrl = vi.fn(async () => { throw new Error("503"); });
    const { result } = renderHook(() => useSpeech("de", vi.fn(), { voices: { de: "de_DE-thorsten-high" }, speechUrl }));
    await act(() => result.current.speak("Welche Rolle?", "turn-1"));
    expect(spoken.map((u) => (u as unknown as FakeUtterance).text)).toEqual(["Welche Rolle?"]);

    const en = renderHook(() => useSpeech("en", vi.fn(), { voices: { de: "de_DE-thorsten-high" }, speechUrl }));
    expect(en.result.current.voiceOptions.some((o) => o.server)).toBe(false);
  });

  test("barge-in while the audio is being prepared means it never plays", async () => {
    let resolve: (url: string) => void = () => {};
    const speechUrl = () => new Promise<string>((r) => { resolve = r; });
    const { result } = renderHook(() => useSpeech("de", vi.fn(), { voices: { de: "de_DE-thorsten-high" }, speechUrl }));
    let pending: Promise<void> = Promise.resolve();
    act(() => { pending = result.current.speak("Welche Rolle?", "turn-1"); });
    act(() => result.current.startListening("push"));
    await act(async () => { resolve("http://late"); await pending; });
    expect(FakeAudio.played).toEqual([]);
  });

  test("a browser voice the learner picked wins over the server voice", async () => {
    const speechUrl = vi.fn(async () => "http://x");
    const { result } = renderHook(() => useSpeech("de", vi.fn(), { voices: { de: "de_DE-thorsten-high" }, speechUrl }));
    act(() => result.current.setVoiceName("Petra"));
    await act(() => result.current.speak("Hallo", "turn-1"));
    expect(speechUrl).not.toHaveBeenCalled();
    expect(spoken).toHaveLength(1);
  });
});
