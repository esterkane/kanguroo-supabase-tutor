---
name: tutor-voice
description: Speech input and output for the tutor — browser Web Speech API STT/TTS in Phase 1, optional local server TTS (Piper/Kokoro) cached in Supabase Storage in Phase 2, and the `speech` track rules. Use for frontend/src/tutor/voice/* and backend/tutor/voice.py.
---

# Voice

## Phase 1 — browser only (no keys, no cost)
- STT: `window.SpeechRecognition || webkitSpeechRecognition`; `lang` from session
  (`de-DE` | `en-US`); `interimResults=true`; push-to-talk (hold space / mic button) and
  hands-free toggle with VAD-ish silence timeout (1.2 s). Final transcript is sent as a
  normal turn with `input_mode: 'voice'` so the model can keep the `speech` reply short.
- TTS: `speechSynthesis` with a voice picked by language; prefer a lower-pitch, slower rate
  (`rate 0.95, pitch 0.85`) for the dry kangaroo delivery. Speak only `TutorTurn.speech`.
  Cancel on new user input. Never speak `text`, code, URLs or Mermaid.
- Feature-detect; if unsupported (Firefox STT), hide the mic and keep TTS.
- Accessibility (AuDHD defaults): visible "speaking" indicator, replay button, text always
  shown alongside audio, global mute, and reduce-motion respected.

## `speech` track rules (enforced by the guard)
≤ 60 words; one idea + the one question; no identifiers longer than one word unless
spoken as a word (say "the authenticated role", not `authenticated`); persona voice when
persona is on, neutral otherwise; German/English per session.

## Phase 2 — server TTS (optional)
- `backend/tutor/voice.py`: `synthesize(text, voice, lang) -> bytes` with providers
  `piper` (local ONNX, de/en voices) or `kokoro`; API providers only behind an explicit
  flag because they cost money.
- Cache: Supabase Storage bucket `tutor-audio`, object key `sha256(voice|lang|text).mp3`;
  bucket is private; the frontend fetches via signed URL (teach signed URLs here).
- Built (R11): Piper is GPL-3.0 and runs as a separate process (`make tts`, HTTP :5002); never add
  `piper-tts` to pyproject. `POST /tutor/voice/speech` takes a `turn_id` and voices only that turn's
  stored `speech`. WAV -> MP3 via ffmpeg. Voices: de_DE-thorsten-high, en_US-ryan-high (one Piper server
  loads both on demand; the provider refuses a voice missing from Piper's /voices instead of letting Piper
  fall back to its default voice).
- The browser falls back to Web Speech if the server audio fails.

## Tests
- Unit: `speech` guard (length, no code/URL).
- Manual demo: `make tts-demo` (`scripts/tts.py demo`) synthesises three sample lines into
  `data/voice/` for listening.
