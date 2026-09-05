"""
Simli service - realtime avatar sessions and text-to-video generation.
"""
import base64
from typing import Any, Optional

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

SIMLI_API_BASE = "https://api.simli.ai"
SIMLI_STATIC_AUDIO_URL = f"{SIMLI_API_BASE}/static/audio"
ELEVENLABS_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech"
DEFAULT_FACE_ID = "cace3ef7-a4c4-425d-a8cf-a5358eb0c427"
DEFAULT_ELEVENLABS_VOICE = "pMsXgVXv3BLzUgSXRplE"


class SimliService:
    def __init__(self):
        self.api_key = settings.simli_api_key or settings.avatar_api_key
        self.elevenlabs_api_key = settings.elevenlabs_api_key or settings.tts_api_key
        self.default_face_id = settings.simli_face_id or DEFAULT_FACE_ID

    async def create_session(self, face_id: Optional[str] = None) -> dict:
        """Create a WebRTC audio-to-video session with Simli."""
        if not self.api_key:
            raise RuntimeError(
                "SIMLI_API_KEY is not configured. Add it to .env before starting an avatar session."
            )

        face = face_id or self.default_face_id
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                f"{SIMLI_API_BASE}/startAudioToVideoSession",
                json={
                    "apiKey": self.api_key,
                    "faceId": face,
                    "isJPG": False,
                    "syncAudio": True,
                },
            )
            if resp.status_code != 200:
                logger.error(f"Failed to create Simli session: {resp.status_code} {resp.text}")
                raise RuntimeError(f"Simli session creation failed: {resp.text}")

            data = resp.json()
            session_token = data.get("session_token")
            logger.info("Created Simli avatar session successfully")
            return {
                "session_token": session_token,
                "face_id": face,
                "api_key": self.api_key,
            }

    async def create_text_to_video_stream(
        self,
        text: str,
        face_id: Optional[str] = None,
        voice_name: Optional[str] = None,
        language: Optional[str] = None,
    ) -> dict:
        """Create a Simli talking-avatar video from text via configured TTS audio."""
        if not self.api_key:
            raise RuntimeError("SIMLI_API_KEY is not configured.")
        if not text.strip():
            raise RuntimeError("Video script is empty.")

        selected_face_id = face_id or self.default_face_id
        tts_provider = (settings.tts_provider or "edge-tts").strip().lower()
        if tts_provider == "elevenlabs":
            if not self.elevenlabs_api_key:
                raise RuntimeError("ELEVENLABS_API_KEY is not configured. Use TTS_PROVIDER=edge-tts or add a valid ElevenLabs key.")
            selected_voice = voice_name or settings.elevenlabs_voice_id or DEFAULT_ELEVENLABS_VOICE
            audio_bytes = await self._generate_elevenlabs_audio(text.strip(), selected_voice)
        else:
            selected_voice = voice_name or self._default_edge_voice(language)
            audio_bytes = await self._generate_edge_tts_audio(text.strip(), selected_voice)

        payload = {
            "faceId": selected_face_id,
            "audioBase64": base64.b64encode(audio_bytes).decode("ascii"),
            "audioFormat": "mp3",
            "audioSampleRate": 24000 if tts_provider != "elevenlabs" else 44100,
            "audioChannelCount": 1,
            "videoStartingFrame": 0,
        }

        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(
                SIMLI_STATIC_AUDIO_URL,
                json=payload,
                headers={
                    "x-simli-api-key": self.api_key,
                    "Content-Type": "application/json",
                },
            )
            if resp.status_code not in (200, 201, 202):
                logger.error(f"Simli static video failed: {resp.status_code} {resp.text}")
                raise RuntimeError(f"Simli static video failed: {resp.text}")

            data = resp.json()
            hls_url, mp4_url = self._extract_static_video_urls(data)
            if not hls_url and not mp4_url:
                raise RuntimeError(f"Simli response did not include a playable video URL: {data}")

            return {
                "provider": "simli_static_audio",
                "status": "complete",
                "hls_url": hls_url,
                "mp4_url": mp4_url,
                "face_id": selected_face_id,
                "voice_name": selected_voice,
                "tts_provider": tts_provider,
                "raw_response": data,
            }

    async def _generate_elevenlabs_audio(self, text: str, voice_id: str) -> bytes:
        """Generate MP3 speech bytes for the lesson script."""
        output_format = "mp3_44100_128"
        model_id = settings.elevenlabs_model_id or "eleven_turbo_v2"
        url = f"{ELEVENLABS_TTS_URL}/{voice_id}?output_format={output_format}"
        payload = {
            "text": text,
            "model_id": model_id,
            "voice_settings": {
                "stability": 0.35,
                "similarity_boost": 0.65,
                "style": 0.25,
            },
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                url,
                json=payload,
                headers={
                    "xi-api-key": self.elevenlabs_api_key,
                    "Content-Type": "application/json",
                    "Accept": "audio/mpeg",
                },
            )
            if resp.status_code != 200:
                logger.error(f"ElevenLabs TTS failed: {resp.status_code} {resp.text}")
                raise RuntimeError(f"ElevenLabs TTS failed: {resp.text}")
            return resp.content

    async def _generate_edge_tts_audio(self, text: str, voice_id: str) -> bytes:
        """Generate free local MP3 speech bytes using Microsoft Edge TTS."""
        try:
            import edge_tts
        except ImportError as exc:
            raise RuntimeError("edge-tts is not installed. Run: pip install edge-tts") from exc

        communicate = edge_tts.Communicate(text, voice_id)
        chunks: list[bytes] = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                chunks.append(chunk["data"])
        if not chunks:
            raise RuntimeError("edge-tts did not return audio.")
        return b"".join(chunks)

    def _default_edge_voice(self, language: Optional[str]) -> str:
        configured = settings.edge_tts_voice
        if configured and configured != "en-IN-NeerjaNeural":
            return configured
        normalized = (language or "").strip().lower()
        if normalized == "hindi":
            return "hi-IN-SwaraNeural"
        return "en-IN-NeerjaNeural"

    def _extract_static_video_urls(self, data: dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
        """Accept likely Simli response shapes and normalize them for the frontend."""
        candidates = self._flatten_response_dicts(data)
        hls_url = None
        mp4_url = None
        destination = None
        file_name = None

        for item in candidates:
            hls_url = hls_url or (
                item.get("hls_url")
                or item.get("hlsUrl")
                or item.get("hls")
                or item.get("hls_url_path")
            )
            mp4_url = mp4_url or (
                item.get("mp4_url")
                or item.get("mp4Url")
                or item.get("mp4")
                or item.get("video_url")
                or item.get("videoUrl")
            )
            destination = destination or item.get("destination") or item.get("videoDestination")
            file_name = file_name or item.get("file") or item.get("filename") or item.get("fileName")
            generic_url = item.get("url")
            if isinstance(generic_url, str):
                if generic_url.endswith(".m3u8"):
                    hls_url = hls_url or generic_url
                elif generic_url.endswith(".mp4"):
                    mp4_url = mp4_url or generic_url

        generic_url = data.get("url")
        if isinstance(generic_url, str):
            if generic_url.endswith(".m3u8"):
                hls_url = hls_url or generic_url
            elif generic_url.endswith(".mp4"):
                mp4_url = mp4_url or generic_url

        if destination and file_name:
            hls_url = hls_url or f"{SIMLI_API_BASE}/static/hls/{destination}/{file_name}"
            mp4_url = mp4_url or f"{SIMLI_API_BASE}/static/mp4/{destination}/{file_name}"
        if hls_url and not mp4_url and "/static/hls/" in hls_url:
            mp4_url = hls_url.replace("/static/hls/", "/static/mp4/", 1)

        return hls_url, mp4_url

    def _flatten_response_dicts(self, value: Any) -> list[dict[str, Any]]:
        if isinstance(value, dict):
            items = [value]
            for nested in value.values():
                items.extend(self._flatten_response_dicts(nested))
            return items
        if isinstance(value, list):
            items: list[dict[str, Any]] = []
            for nested in value:
                items.extend(self._flatten_response_dicts(nested))
            return items
        return []


simli_service = SimliService()
