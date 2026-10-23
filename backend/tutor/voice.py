"""Server TTS (T2.6 / R11, ADR-005): Piper voices for the `speech` track, cached in Supabase Storage.

Piper (GPL-3.0) runs as its own local process (`make tts`, Piper's HTTP server) and is called over HTTP, so it is
not a dependency of this app. Audio is cached in the private bucket `tutor-audio` under
sha256(voice|lang|text).mp3 and handed to the browser as a short-lived signed URL; the browser falls back to
Web Speech whenever this path fails. Enabled with TUTOR_TTS=server.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import re
import shutil

import httpx

BUCKET = "tutor-audio"
SIGNED_URL_TTL_S = 3600
MAX_CHARS = 800  # the guard keeps `speech` at <= 60 words; this only bounds abuse
DEFAULT_VOICES = {"de": "de_DE-thorsten-high", "en": "en_US-ryan-high"}  # PIPER_VOICE_<LANG>="" opts a language out


class TtsUnavailable(Exception):
    """The provider, ffmpeg or Storage failed; the browser should use Web Speech."""


def clean_for_speech(text: str) -> str:
    """Same rules as frontend speechText.cleanForSpeech: no code, URLs or Markdown marks are spoken."""
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[*_#>|]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def cache_key(voice: str, lang: str, text: str) -> str:
    return hashlib.sha256(f"{voice}|{lang}|{text}".encode()).hexdigest() + ".mp3"


async def to_mp3(wav: bytes) -> bytes:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise TtsUnavailable("ffmpeg not found (brew install ffmpeg)")
    proc = await asyncio.create_subprocess_exec(
        ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "wav", "-i", "pipe:0",
        "-codec:a", "libmp3lame", "-q:a", "5", "-f", "mp3", "pipe:1",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, err = await proc.communicate(wav)
    if proc.returncode != 0 or not out:
        raise TtsUnavailable(f"ffmpeg failed: {err.decode(errors='replace')[:200]}")
    return out


class PiperProvider:
    """Client for Piper's HTTP server (`python -m piper.http_server`): POST /synthesize -> WAV."""
    name = "piper"

    def __init__(self, url: str, voices: dict[str, str], client: httpx.AsyncClient) -> None:
        self.url = url.rstrip("/")
        self.voices = voices
        self.client = client
        self.downloaded: set[str] | None = None  # Piper's /voices, read once

    async def _check_voice(self, voice: str) -> None:
        """Piper answers an unknown voice with its default one (German text in an English session); refuse instead."""
        if self.downloaded is None or voice not in self.downloaded:
            try:
                res = await self.client.get(f"{self.url}/voices", timeout=10)
                self.downloaded = set(res.json()) if res.status_code == 200 else set()
            except (httpx.HTTPError, ValueError) as e:
                raise TtsUnavailable(f"piper not reachable at {self.url} ({type(e).__name__}); run `make tts`") from e
        if voice not in self.downloaded:
            raise TtsUnavailable(f"piper voice {voice} is not downloaded (make tts-voices)")

    def voice_for(self, lang: str) -> str | None:
        return self.voices.get(lang) or None

    async def synthesize(self, text: str, voice: str, lang: str) -> bytes:
        await self._check_voice(voice)
        try:
            res = await self.client.post(f"{self.url}/synthesize", json={"text": text, "voice": voice}, timeout=30)
        except httpx.HTTPError as e:
            raise TtsUnavailable(f"piper not reachable at {self.url} ({type(e).__name__}); run `make tts`") from e
        if res.status_code != 200 or not res.content.startswith(b"RIFF"):
            raise TtsUnavailable(f"piper answered {res.status_code} for voice {voice} ({lang})")
        return res.content


class StorageCache:
    """Private-bucket cache through the Storage REST API with the server-side secret key."""

    def __init__(self, api_url: str, key: str, client: httpx.AsyncClient) -> None:
        self.base = f"{api_url.rstrip('/')}/storage/v1"
        self.headers = {"Authorization": f"Bearer {key}", "apikey": key}
        self.client = client

    async def signed_url(self, key: str) -> str | None:
        """Signed URL for an existing object, None when it is not cached yet."""
        try:
            res = await self.client.post(f"{self.base}/object/sign/{BUCKET}/{key}", headers=self.headers,
                                         json={"expiresIn": SIGNED_URL_TTL_S}, timeout=10)
        except httpx.HTTPError as e:
            raise TtsUnavailable(f"storage not reachable ({type(e).__name__})") from e
        if res.status_code == 200:
            return f"{self.base}{res.json()['signedURL']}"
        if res.status_code in (400, 404):  # Storage reports a missing object as 400 "not_found"
            return None
        raise TtsUnavailable(f"storage sign failed: {res.status_code}")

    async def put(self, key: str, data: bytes, content_type: str = "audio/mpeg") -> None:
        res = await self.client.post(f"{self.base}/object/{BUCKET}/{key}", content=data, timeout=30,
                                     headers={**self.headers, "Content-Type": content_type, "x-upsert": "true"})
        if res.status_code not in (200, 201):
            raise TtsUnavailable(f"storage upload failed: {res.status_code} {res.text[:200]}")


class VoiceService:
    def __init__(self, provider: PiperProvider, cache: StorageCache, client: httpx.AsyncClient | None = None) -> None:
        self.provider = provider
        self.cache = cache
        self.client = client

    def voices(self) -> dict[str, str | None]:
        return {lang: self.provider.voice_for(lang) for lang in ("de", "en")}

    async def speech_url(self, text: str, lang: str) -> dict[str, object]:
        voice = self.provider.voice_for(lang)
        if not voice:
            raise TtsUnavailable(f"no server voice for {lang}")
        clean = clean_for_speech(text)[:MAX_CHARS]
        if not clean:
            raise TtsUnavailable("nothing to speak")
        key = cache_key(voice, lang, clean)
        if url := await self.cache.signed_url(key):
            return {"url": url, "voice": voice, "cached": True}
        audio = await to_mp3(await self.provider.synthesize(clean, voice, lang))
        await self.cache.put(key, audio)
        url = await self.cache.signed_url(key)
        if not url:
            raise TtsUnavailable("uploaded audio could not be signed")
        return {"url": url, "voice": voice, "cached": False}

    async def close(self) -> None:
        if self.client:
            await self.client.aclose()

    @classmethod
    def from_env(cls) -> VoiceService | None:
        """TUTOR_TTS=server plus PIPER_URL enables server voices; anything else keeps the browser voices."""
        if os.environ.get("TUTOR_TTS", "browser") != "server":
            return None
        key = os.environ.get("SECRET_KEY") or os.environ.get("SERVICE_ROLE_KEY")
        if not key:
            return None
        client = httpx.AsyncClient()
        voices = {lang: os.environ.get(f"PIPER_VOICE_{lang.upper()}", default) for lang, default in DEFAULT_VOICES.items()}
        provider = PiperProvider(os.environ.get("PIPER_URL", "http://127.0.0.1:5002"), voices, client)
        return cls(provider, StorageCache(os.environ["API_URL"], key, client), client)
