// Web Speech input and output for the tutor (T2.1), feature-detected. Browser only: no keys, no cost.
import { useCallback, useEffect, useRef, useState } from "react";
import type { Language } from "../types";
import { cleanForSpeech, pickVoice, PITCH, RATE, SILENCE_MS, SPEECH_LANG, voicesFor } from "./speechText";

interface RecognitionResult {
  isFinal: boolean;
  0: { transcript: string };
}
interface RecognitionEvent {
  resultIndex: number;
  results: ArrayLike<RecognitionResult>;
}
export interface Recognition {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((e: RecognitionEvent) => void) | null;
  onend: (() => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}
type RecognitionCtor = new () => Recognition;

export type ListenMode = "off" | "push" | "handsfree";

const MUTE_KEY = "kaenguru.voice.muted";
const voiceKey = (lang: Language) => `kaenguru.voice.name.${lang}`;

function recognitionCtor(): RecognitionCtor | null {
  const w = window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

function readStored(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStored(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    // private mode: the setting just isn't remembered
  }
}

/** Server TTS (GET /tutor/voice): the voice per language and how to get a turn's audio URL. */
export interface ServerTts {
  voices: Partial<Record<Language, string | null>>;
  speechUrl: (turnId: string) => Promise<string>;
}

export interface VoiceOption {
  value: string;
  label: string;
  server: boolean;
}

const SERVER_PREFIX = "server:";

/** "de_DE-thorsten-high" -> "Thorsten" */
function serverLabel(voice: string): string {
  const name = voice.split("-")[1] ?? voice;
  return `${name.charAt(0).toUpperCase()}${name.slice(1)}`;
}

export function useSpeech(lang: Language, onFinal: (transcript: string) => void, server: ServerTts | null = null) {
  const Ctor = typeof window === "undefined" ? null : recognitionCtor();
  const synth = typeof window !== "undefined" && "speechSynthesis" in window ? window.speechSynthesis : null;
  const support = { stt: Ctor !== null, tts: synth !== null };

  const [mode, setMode] = useState<ListenMode>("off");
  const [interim, setInterim] = useState("");
  const [micError, setMicError] = useState<string | null>(null);
  const [speaking, setSpeaking] = useState(false);
  const [muted, setMutedState] = useState(() => readStored(MUTE_KEY) === "1");
  const [preferred, setPreferred] = useState(() => readStored(voiceKey(lang)));
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>(() => synth?.getVoices() ?? []);

  const rec = useRef<Recognition | null>(null);
  const finalText = useRef("");
  const silence = useRef<ReturnType<typeof setTimeout> | null>(null);
  const audio = useRef<HTMLAudioElement | null>(null);
  const speakSeq = useRef(0);
  const serverVoice = server?.voices[lang] ?? null;
  const modeRef = useRef<ListenMode>("off");
  const onFinalRef = useRef(onFinal);
  onFinalRef.current = onFinal;
  modeRef.current = mode;

  useEffect(() => setPreferred(readStored(voiceKey(lang))), [lang]);

  useEffect(() => {  // voices load asynchronously in Chrome
    if (!synth) return;
    const update = () => setVoices(synth.getVoices());
    update();  // they may have arrived between the first render and this effect
    synth.addEventListener?.("voiceschanged", update);
    return () => synth.removeEventListener?.("voiceschanged", update);
  }, [synth]);

  const cancelSpeech = useCallback(() => {
    speakSeq.current++;
    synth?.cancel();
    audio.current?.pause();
    audio.current = null;
    setSpeaking(false);
  }, [synth]);

  const flush = useCallback(() => {
    if (silence.current) clearTimeout(silence.current);
    silence.current = null;
    const text = finalText.current.trim();
    finalText.current = "";
    setInterim("");
    if (text) onFinalRef.current(text);
  }, []);

  const stopListening = useCallback((send = true) => {
    const current = rec.current;
    rec.current = null;
    setMode("off");
    current?.stop();
    if (send) flush();
    else {
      finalText.current = "";
      setInterim("");
    }
  }, [flush]);

  const startListening = useCallback((next: Exclude<ListenMode, "off">) => {
    if (!Ctor || rec.current) return;
    cancelSpeech();  // the learner is about to talk: the tutor stops (barge-in)
    setMicError(null);
    const r = new Ctor();
    r.lang = SPEECH_LANG[lang];
    r.continuous = true;
    r.interimResults = true;
    r.onresult = (e) => {
      cancelSpeech();
      let partial = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const res = e.results[i];
        if (res.isFinal) finalText.current += `${res[0].transcript} `;
        else partial += res[0].transcript;
      }
      setInterim((finalText.current + partial).replace(/\s+/g, " ").trim());
      if (modeRef.current === "handsfree") {  // send after a pause in speech
        if (silence.current) clearTimeout(silence.current);
        silence.current = setTimeout(flush, SILENCE_MS);
      }
    };
    r.onerror = (e) => {
      if (e.error === "no-speech" || e.error === "aborted") return;
      setMicError(e.error);  // not-allowed, audio-capture, network, ...
      stopListening(false);
    };
    r.onend = () => {  // browsers end recognition on their own; hands-free keeps listening
      if (rec.current === r && modeRef.current === "handsfree") r.start();
    };
    rec.current = r;
    setMode(next);
    r.start();
  }, [Ctor, cancelSpeech, flush, lang, stopListening]);

  const webSpeak = useCallback((clean: string) => {
    if (!synth) return;
    synth.cancel();
    const u = new SpeechSynthesisUtterance(clean);
    u.lang = SPEECH_LANG[lang];
    const voice = pickVoice(voices, lang, preferred);
    if (voice) u.voice = voice;
    u.rate = RATE;
    u.pitch = PITCH;
    u.onstart = () => setSpeaking(true);
    u.onend = () => setSpeaking(false);
    u.onerror = () => setSpeaking(false);
    synth.speak(u);
  }, [synth, lang, voices, preferred]);

  /** Speak a turn's `speech` track: the server voice when chosen and available, else (or on failure) Web Speech. */
  const speak = useCallback(async (text: string, turnId?: string) => {
    const clean = cleanForSpeech(text);
    if (muted || !clean) return;
    cancelSpeech();  // also invalidates any server audio still being prepared
    const attempt = ++speakSeq.current;
    if (serverVoice && turnId && server && (preferred === null || preferred === SERVER_PREFIX + serverVoice)) {
      try {
        const url = await server.speechUrl(turnId);
        if (attempt !== speakSeq.current) return;  // cancelled or superseded while the audio was prepared
        const el = new Audio(url);
        audio.current = el;
        el.onplay = () => setSpeaking(true);
        el.onended = () => setSpeaking(false);
        el.onerror = () => setSpeaking(false);
        await el.play();
        return;
      } catch {
        if (attempt !== speakSeq.current) return;
        // server TTS down or autoplay refused: fall through to the browser voice
      }
    }
    webSpeak(clean);
  }, [muted, cancelSpeech, server, serverVoice, preferred, webSpeak]);

  const setMuted = useCallback((next: boolean) => {
    setMutedState(next);
    if (next) cancelSpeech();
    writeStored(MUTE_KEY, next ? "1" : "0");
  }, [cancelSpeech]);

  const setVoiceName = useCallback((name: string) => {
    setPreferred(name);
    writeStored(voiceKey(lang), name);
  }, [lang]);

  useEffect(() => () => {
    rec.current?.abort();
    synth?.cancel();
    audio.current?.pause();
  }, [synth]);

  const browserVoice = pickVoice(voices, lang, preferred);
  const voiceOptions: VoiceOption[] = [
    ...(serverVoice ? [{ value: SERVER_PREFIX + serverVoice, label: serverLabel(serverVoice), server: true }] : []),
    ...voicesFor(voices, lang).map((v) => ({ value: v.name, label: v.name, server: false })),
  ];
  const voiceName = serverVoice && (preferred === null || preferred === SERVER_PREFIX + serverVoice)
    ? SERVER_PREFIX + serverVoice : browserVoice?.name ?? "";

  return { support: { ...support, tts: support.tts || serverVoice !== null }, mode, interim, micError, speaking,
           muted, startListening, stopListening, speak, cancelSpeech, setMuted, voiceOptions, voiceName, setVoiceName };
}
