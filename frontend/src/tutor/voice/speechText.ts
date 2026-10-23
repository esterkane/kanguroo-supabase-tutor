// Pure helpers for the voice track (tutor-voice skill): which voice, and what may be spoken.
import type { Language } from "../types";

export const SPEECH_LANG: Record<Language, string> = { de: "de-DE", en: "en-US" };
// Dry, unhurried kangaroo delivery (tutor-voice skill; persona tts_hint).
export const RATE = 0.95;
export const PITCH = 0.85;
export const SILENCE_MS = 1200;

export interface VoiceLike {
  name: string;
  lang: string;
  localService: boolean;
  default: boolean;
}

// Downloaded high-quality voices (macOS "Premium"/"Erweitert", Windows "Natural", Chrome's Google voices).
const QUALITY = /premium|enhanced|erweitert|verbessert|natural|neural|google/i;
// macOS Eloquence and effect voices: robotic, never picked automatically (still selectable).
const NOVELTY = /^(eddy|flo|grandma|grandpa|reed|rocko|sandy|shelley|albert|bahh|boing|bells|bubbles|cellos|fred|good news|bad news|jester|junior|organ|ralph|superstar|trinoids|whisper|wobble|zarvox|glocken|seifenblasen|orgel|flüstern|monster|gute neuigkeiten|schlechte neuigkeiten|spaßvogel)\b/i;

function score(v: VoiceLike, lang: Language): number {
  const locale = SPEECH_LANG[lang].toLowerCase();
  const l = v.lang.toLowerCase().replace("_", "-");
  const match = l === locale ? 4 : l.startsWith(locale.slice(0, 2)) ? 2 : 0;
  if (!match) return 0;
  return match + (QUALITY.test(v.name) ? 8 : 0) + (v.localService ? 1 : 0) - (NOVELTY.test(v.name) ? 20 : 0);
}

/** Voices for the language, best first (the picker's list); novelty voices last. */
export function voicesFor<V extends VoiceLike>(voices: readonly V[], lang: Language): V[] {
  return voices.filter((v) => score(v, lang) !== 0).sort((a, b) => score(b, lang) - score(a, lang));
}

/** The learner's chosen voice if installed, else the best non-novelty voice for the language. */
export function pickVoice<V extends VoiceLike>(voices: readonly V[], lang: Language, preferred?: string | null): V | null {
  const ranked = voicesFor(voices, lang);
  return ranked.find((v) => v.name === preferred) ?? ranked.find((v) => score(v, lang) > 0) ?? null;
}

/** Defense in depth: `speech` must not contain code, URLs or diagrams (the guard checks too). */
export function cleanForSpeech(text: string): string {
  return text
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/`([^`]*)`/g, "$1")
    .replace(/https?:\/\/\S+/g, " ")
    .replace(/[*_#>|]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}
