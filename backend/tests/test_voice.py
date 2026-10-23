"""Server TTS: Piper client, Storage cache and VoiceService against mocked HTTP (ffmpeg real when installed)."""
from __future__ import annotations

import io
import json
import shutil
import wave
from typing import Any

import httpx
import pytest

from backend.tutor.voice import (
    BUCKET,
    PiperProvider,
    StorageCache,
    TtsUnavailable,
    VoiceService,
    cache_key,
    clean_for_speech,
    to_mp3,
)


def silent_wav(seconds: float = 0.2) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(22050)
        w.writeframes(b"\0\0" * int(22050 * seconds))
    return buf.getvalue()


def test_clean_for_speech_matches_the_frontend_rules() -> None:
    assert clean_for_speech("Schau auf **GRANT**: `select 1` dann\n```sql\ndrop table x;\n```\nhttps://supabase.com ok") \
        == "Schau auf GRANT : select 1 dann ok"


def test_cache_key_depends_on_voice_language_and_text() -> None:
    k = cache_key("de_DE-thorsten-high", "de", "Hallo")
    assert k.endswith(".mp3") and len(k) == 68
    assert k != cache_key("de_DE-thorsten-medium", "de", "Hallo") != cache_key("de_DE-thorsten-high", "de", "Hallo.")


class FakeBackends:
    """Piper (/synthesize) and Storage (/storage/v1/object[/sign]) in one MockTransport."""

    def __init__(self, piper_status: int = 200, downloaded: tuple[str, ...] = ("de_DE-thorsten-high",)) -> None:
        self.downloaded = downloaded
        self.objects: dict[str, bytes] = {}
        self.synthesized: list[dict[str, Any]] = []
        self.piper_status = piper_status

    def __call__(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path == "/voices":
            return httpx.Response(200, json={v: {"language": {"code": v[:5]}} for v in self.downloaded})
        if path == "/synthesize":
            self.synthesized.append(json.loads(req.content))
            return httpx.Response(self.piper_status, content=silent_wav() if self.piper_status == 200 else b"no")
        assert req.headers["authorization"] == "Bearer secret"
        if path.startswith(f"/storage/v1/object/sign/{BUCKET}/"):
            key = path.rsplit("/", 1)[1]
            if key not in self.objects:
                return httpx.Response(400, json={"error": "not_found"})
            return httpx.Response(200, json={"signedURL": f"/object/sign/{BUCKET}/{key}?token=t"})
        if path.startswith(f"/storage/v1/object/{BUCKET}/"):
            assert req.headers["content-type"] == "audio/mpeg"
            self.objects[path.rsplit("/", 1)[1]] = req.content
            return httpx.Response(200, json={"Key": path})
        return httpx.Response(404)


def service(backends: FakeBackends, voices: dict[str, str] | None = None) -> VoiceService:
    client = httpx.AsyncClient(transport=httpx.MockTransport(backends))
    provider = PiperProvider("http://piper:5002", voices or {"de": "de_DE-thorsten-high", "en": ""}, client)
    return VoiceService(provider, StorageCache("http://supabase:54321", "secret", client), client)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
async def test_synthesizes_once_then_serves_the_cached_object_by_signed_url() -> None:
    backends = FakeBackends()
    voice = service(backends)
    first = await voice.speech_url("Welche `Rolle` fragt an?", "de")
    second = await voice.speech_url("Welche `Rolle` fragt an?", "de")
    await voice.close()
    assert backends.synthesized == [{"text": "Welche Rolle fragt an?", "voice": "de_DE-thorsten-high"}]
    assert (first["cached"], second["cached"]) == (False, True)
    assert str(first["url"]).startswith(f"http://supabase:54321/storage/v1/object/sign/{BUCKET}/")
    (stored,) = backends.objects.values()
    assert stored[:3] == b"ID3" or stored[:2] == b"\xff\xfb"  # MP3, not the WAV


async def test_failures_raise_tts_unavailable_so_the_browser_falls_back() -> None:
    voice = service(FakeBackends(piper_status=500))
    with pytest.raises(TtsUnavailable, match="piper answered 500"):
        await voice.speech_url("Hallo", "de")
    with pytest.raises(TtsUnavailable, match="no server voice for en"):
        await voice.speech_url("Hello", "en")
    with pytest.raises(TtsUnavailable, match="nothing to speak"):
        await voice.speech_url("```sql\nselect 1;\n```", "de")
    await voice.close()


async def test_a_voice_piper_has_not_downloaded_is_refused_not_replaced() -> None:
    backends = FakeBackends()
    voice = service(backends, {"de": "de_DE-thorsten-high", "en": "en_US-ryan-high"})
    with pytest.raises(TtsUnavailable, match="en_US-ryan-high is not downloaded"):
        await voice.speech_url("Which role is asking?", "en")
    await voice.close()
    assert backends.synthesized == []  # Piper would have read English with the German voice


def test_english_has_a_server_voice_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TUTOR_TTS", "server")
    monkeypatch.setenv("SECRET_KEY", "secret")
    monkeypatch.setenv("API_URL", "http://supabase:54321")
    monkeypatch.delenv("PIPER_VOICE_EN", raising=False)
    voice = VoiceService.from_env()
    assert voice is not None and voice.voices() == {"de": "de_DE-thorsten-high", "en": "en_US-ryan-high"}
    monkeypatch.setenv("PIPER_VOICE_EN", "")  # opt English out: browser voice
    opted = VoiceService.from_env()
    assert opted is not None and opted.voices()["en"] is None


async def test_to_mp3_without_ffmpeg_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    with pytest.raises(TtsUnavailable, match="ffmpeg"):
        await to_mp3(silent_wav())


def test_from_env_is_off_unless_tts_server(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TUTOR_TTS", "browser")
    assert VoiceService.from_env() is None
