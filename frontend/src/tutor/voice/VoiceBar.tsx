// Voice controls (tutor-voice skill): push-to-talk (hold button or Space), hands-free, mute, speaking indicator.
import { useEffect } from "react";
import type { Strings } from "../i18n";
import type { useSpeech } from "./useSpeech";

type Voice = ReturnType<typeof useSpeech>;

function isEditable(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  return !!el && (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName));
}

const chip = "rounded border px-2 py-0.5 text-xs disabled:opacity-40";

export function VoiceBar({ voice, s }: { voice: Voice; s: Strings }) {
  const { support, mode, interim, micError, speaking, muted, startListening, stopListening, cancelSpeech, setMuted,
          voiceOptions, voiceName, setVoiceName } = voice;

  useEffect(() => {  // hold Space to talk, unless the learner is typing somewhere
    if (!support.stt) return;
    const down = (e: KeyboardEvent) => {
      if (e.code !== "Space" || e.repeat || isEditable(e.target) || mode === "handsfree") return;
      e.preventDefault();
      startListening("push");
    };
    const up = (e: KeyboardEvent) => {
      if (e.code === "Space" && mode === "push") stopListening();
    };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
    };
  }, [support.stt, mode, startListening, stopListening]);

  if (!support.stt && !support.tts) return null;

  return (
    <div className="flex flex-wrap items-center gap-2 border-t border-zinc-800 px-2 py-1">
      {support.stt ? (
        <>
          <button type="button" title={s.mic} aria-pressed={mode === "push"} disabled={mode === "handsfree"}
                  onPointerDown={() => startListening("push")} onPointerUp={() => stopListening()}
                  onPointerLeave={() => mode === "push" && stopListening()}
                  className={`${chip} ${mode === "push" ? "border-red-600 text-red-300" : "border-zinc-700 hover:border-sky-600"}`}>
            {s.micShort}
          </button>
          <button type="button" aria-pressed={mode === "handsfree"}
                  onClick={() => (mode === "handsfree" ? stopListening() : startListening("handsfree"))}
                  className={`${chip} ${mode === "handsfree" ? "border-red-600 text-red-300" : "border-zinc-700 hover:border-sky-600"}`}>
            {s.handsFree}
          </button>
        </>
      ) : (
        <span className="text-[11px] text-zinc-500">{s.noStt}</span>
      )}
      {micError && mode === "off" && (
        <span role="alert" className="text-[11px] text-amber-400">
          {micError === "not-allowed" || micError === "service-not-allowed" ? s.micDenied : `${s.micFailed}: ${micError}`}
        </span>
      )}
      {mode !== "off" && (
        <span className="min-w-0 flex-1 truncate text-xs text-zinc-400" aria-live="polite">
          <span className="mr-1 inline-block h-2 w-2 rounded-full bg-red-500 motion-safe:animate-pulse" aria-hidden />
          {s.listening}{interim ? `: ${interim}` : " …"}
        </span>
      )}
      <span className="ml-auto flex items-center gap-2">
        {speaking && (
          <>
            <span className="text-xs text-emerald-400" role="status">
              <span className="mr-1 inline-block h-2 w-2 rounded-full bg-emerald-500 motion-safe:animate-pulse" aria-hidden />
              {s.speaking}
            </span>
            <button type="button" onClick={cancelSpeech} className={`${chip} border-zinc-700 hover:border-sky-600`}>
              {s.stopSpeaking}
            </button>
          </>
        )}
        {support.tts && voiceOptions.length > 1 && (
          <select aria-label={s.voice} value={voiceName} onChange={(e) => setVoiceName(e.target.value)}
                  className="max-w-40 rounded border border-zinc-700 bg-zinc-900 px-1 py-0.5 text-xs">
            {voiceOptions.map((o) => (
              <option key={o.value} value={o.value}>{o.server ? `${o.label} (${s.serverVoice})` : o.label}</option>
            ))}
          </select>
        )}
        {support.tts && (
          <button type="button" aria-pressed={muted} onClick={() => setMuted(!muted)}
                  className={`${chip} border-zinc-700 hover:border-sky-600`}>
            {muted ? s.unmute : s.mute}
          </button>
        )}
      </span>
    </div>
  );
}
