#!/usr/bin/env python3
"""Local Piper server TTS for the tutor's `speech` track (T2.6 / R11), local only.

  download  fetch the configured Piper voices (PIPER_VOICE_DE, PIPER_VOICE_EN) into data/piper (skips existing)
  serve     run Piper's HTTP server on PIPER_URL's port (default 127.0.0.1:5002) with those voices
  demo      synthesise three sample lines through the backend's VoiceService path into data/voice/ for listening

Piper is GPL-3.0, so it runs as its own process via `uvx` and is not a dependency of the tutor. The backend
uses it when TUTOR_TTS=server (see .env.example); the browser falls back to Web Speech when it is not running.

Usage:
  uv run python scripts/tts.py download
  uv run python scripts/tts.py serve
  uv run python scripts/tts.py demo
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PIPER = ["uvx", "--python", "3.12", "--from", "piper-tts[http]==1.8.0", "python", "-m"]
DATA = ROOT / "data" / "piper"
DEMO_DIR = ROOT / "data" / "voice"
LENGTH_SCALE = "1.05"  # a little slower than Piper's default: the dry kangaroo delivery (rate 0.95 in the browser)
DEMO = [
    ("de", "Kleinkünstler, erst der Grant, dann die Policy. Welche Rolle fragt hier eigentlich an?"),
    ("de", "Schau dir den Plan an. Wo verliert die Abfrage ihre Zeit?"),
    ("en", "First the grant, then the policy. Which role is asking here?"),
]


def voices() -> dict[str, str]:
    from backend.tutor.voice import DEFAULT_VOICES
    found = {lang: os.environ.get(f"PIPER_VOICE_{lang.upper()}", default) for lang, default in DEFAULT_VOICES.items()}
    return {lang: v for lang, v in found.items() if v}


def download() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    missing = [v for v in voices().values() if not (DATA / f"{v}.onnx").exists()]
    if not missing:
        print(f"voices present in {DATA}: {', '.join(voices().values())}")
        return
    os.execvp(PIPER[0], [*PIPER, "piper.download_voices", "--data-dir", str(DATA), *missing])


def serve() -> None:
    url = urlparse(os.environ.get("PIPER_URL", "http://127.0.0.1:5002"))
    chosen = voices()
    default = chosen.get("de") or next(iter(chosen.values()), None)
    if not default or not (DATA / f"{default}.onnx").exists():
        sys.exit("no voice downloaded yet: make tts-voices")
    os.execvp(PIPER[0], [*PIPER, "piper.http_server", "--host", url.hostname or "127.0.0.1",
                         "--port", str(url.port or 5002), "--data-dir", str(DATA), "-m", default,
                         "--length-scale", LENGTH_SCALE])


async def demo() -> None:
    import httpx

    from backend.tutor.voice import PiperProvider, TtsUnavailable, clean_for_speech, to_mp3
    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient() as client:
        piper = PiperProvider(os.environ.get("PIPER_URL", "http://127.0.0.1:5002"), voices(), client)
        for i, (lang, line) in enumerate(DEMO, 1):
            voice = piper.voice_for(lang)
            if not voice:
                print(f"{i}: no server voice for {lang} (browser voice is used)")
                continue
            try:
                audio = await to_mp3(await piper.synthesize(clean_for_speech(line), voice, lang))
            except TtsUnavailable as e:
                sys.exit(str(e))
            out = DEMO_DIR / f"demo-{i}-{lang}.mp3"
            out.write_bytes(audio)
            print(f"{i}: {out.relative_to(ROOT)} ({len(audio) // 1024} KB, {voice})")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["download", "serve", "demo"])
    a = ap.parse_args()
    if a.command == "download":
        download()
    elif a.command == "serve":
        serve()
    else:
        asyncio.run(demo())


if __name__ == "__main__":
    main()
