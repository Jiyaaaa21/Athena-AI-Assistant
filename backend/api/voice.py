"""
Phase 9 — Voice OS API

Endpoints:
  POST /voice/transcribe    — STT: audio bytes → text
  POST /voice/speak         — TTS: text → MP3 audio stream
  GET  /voice/voices        — list available TTS voices
  GET  /voice/settings      — fetch persisted voice preferences
  PUT  /voice/settings      — upsert voice preferences
"""

from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from backend.core.logger import agent_logger as logger
from backend.database.db import SessionLocal
from backend.core.request_context import get_current_user_id
from backend.voice.stt import transcribe_audio
from backend.voice.tts import VOICE_CATALOGUE, synthesize, synthesize_chunk, split_into_speakable_chunks

router = APIRouter(prefix="/voice", tags=["voice"])

# ── Voice settings defaults ───────────────────────────────────────────────────

_DEFAULT_VOICE_SETTINGS: dict = {
    "voice_id": "en-US-AriaNeural",
    "speed": 1.0,
    "volume": 1.0,
    "wake_word_enabled": False,
    "wake_word": "Hey Athena",
    "continuous_mode": False,
    "auto_play": True,
    "vad_enabled": True,
}

_SETTINGS_KEY = "default"


def _get_voice_settings(db) -> dict:
    from backend.database.models import VoiceSettings
    row = db.query(VoiceSettings).filter(
        VoiceSettings.key == _SETTINGS_KEY, VoiceSettings.user_id == get_current_user_id()
    ).first()
    if not row:
        return dict(_DEFAULT_VOICE_SETTINGS)
    try:
        stored = json.loads(row.value)
        return {**_DEFAULT_VOICE_SETTINGS, **stored}
    except Exception:
        return dict(_DEFAULT_VOICE_SETTINGS)


def _set_voice_settings(db, settings: dict) -> None:
    from backend.database.models import VoiceSettings
    row = db.query(VoiceSettings).filter(
        VoiceSettings.key == _SETTINGS_KEY, VoiceSettings.user_id == get_current_user_id()
    ).first()
    blob = json.dumps(settings)
    if row:
        row.value = blob
    else:
        row = VoiceSettings(key=_SETTINGS_KEY, value=blob, user_id=get_current_user_id())
        db.add(row)
    db.commit()


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class VoiceSettingsIn(BaseModel):
    voice_id: Optional[str] = None
    speed: Optional[float] = None
    volume: Optional[float] = None
    wake_word_enabled: Optional[bool] = None
    wake_word: Optional[str] = None
    continuous_mode: Optional[bool] = None
    auto_play: Optional[bool] = None
    vad_enabled: Optional[bool] = None


class SpeakRequest(BaseModel):
    text: str
    voice_id: Optional[str] = None
    speed: Optional[float] = None
    volume: Optional[float] = None


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/transcribe")
async def transcribe(
    audio: UploadFile = File(...),
    mime_type: str = Form(default="audio/webm"),
):
    """
    Receive raw audio bytes from the browser's MediaRecorder,
    run Whisper (via Groq) or fallback STT, return the transcript.
    """
    import time
    start = time.monotonic()

    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio payload")

    effective_mime = mime_type or audio.content_type or "audio/webm"

    try:
        text = transcribe_audio(audio_bytes, effective_mime)
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    duration_ms = int((time.monotonic() - start) * 1000)
    logger.info("[voice/transcribe] %d bytes -> %d chars in %d ms", len(audio_bytes), len(text), duration_ms)

    return {"text": text, "duration_ms": duration_ms}


@router.post("/speak")
def speak(body: SpeakRequest):
    """
    Convert text to speech using Edge TTS.
    Returns raw MP3 bytes as audio/mpeg.

    Kept for callers that want one complete audio file (e.g. "replay last
    message" from the conversation history, where chunked playback isn't
    needed). New voice-mode conversations should use /voice/speak/stream
    instead — see below.
    """
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="text is required")

    db = SessionLocal()
    try:
        settings = _get_voice_settings(db)
    finally:
        db.close()

    voice_id = body.voice_id or settings.get("voice_id")
    speed = body.speed if body.speed is not None else settings.get("speed", 1.0)
    volume = body.volume if body.volume is not None else settings.get("volume", 1.0)

    speed = max(0.5, min(2.0, float(speed)))
    volume = max(0.1, min(1.0, float(volume)))

    try:
        mp3_bytes = synthesize(body.text, voice_id=voice_id, speed=speed, volume=volume)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return Response(
        content=mp3_bytes,
        media_type="audio/mpeg",
        headers={
            "Content-Disposition": "inline; filename=\"athena_speech.mp3\"",
            "Cache-Control": "no-cache",
        },
    )


@router.post("/speak/stream")
async def speak_stream(body: SpeakRequest):
    """
    Phase 17 — sentence-chunked streaming TTS.

    The old /speak endpoint waits for the ENTIRE text to synthesize before
    sending a single audio file back. For a 200-word answer that's 3-4
    seconds of dead silence before any sound plays, then one long blob —
    nothing like a real conversation.

    This endpoint splits the input into speakable sentence-sized chunks,
    synthesizes each one in turn, and streams them to the client as a
    sequence of length-prefixed MP3 frames:

        [4-byte big-endian length][mp3 bytes][4-byte length][mp3 bytes]...

    The frontend reads frames as they arrive and queues each one for
    playback independently — so chunk 1 (the first sentence) can start
    playing while chunk 2 is still being synthesized server-side. This
    cuts time-to-first-audio from "however long the whole response takes"
    down to "however long ONE sentence takes" (typically under a second).

    Used together with sentence-level chunking on the LLM token stream
    itself (see api/chat.py), Athena can start speaking the first
    sentence of her answer while she's still generating the rest of it —
    matching how a person actually talks.
    """
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="text is required")

    db = SessionLocal()
    try:
        settings = _get_voice_settings(db)
    finally:
        db.close()

    voice_id = body.voice_id or settings.get("voice_id")
    speed = body.speed if body.speed is not None else settings.get("speed", 1.0)
    volume = body.volume if body.volume is not None else settings.get("volume", 1.0)
    speed = max(0.5, min(2.0, float(speed)))
    volume = max(0.1, min(1.0, float(volume)))

    chunks = split_into_speakable_chunks(body.text)
    logger.info("[voice/speak/stream] request: %d chars -> %d chunk(s), voice=%s", len(body.text), len(chunks), voice_id)
    if not chunks:
        raise HTTPException(status_code=400, detail="No speakable content after cleaning text")

    async def _frame_generator():
        import asyncio
        chunks_synthesized = 0
        chunks_failed = 0
        for i, chunk_text in enumerate(chunks):
            try:
                # synthesize_chunk is sync (thread-pooled internally); run
                # it off the event loop so other requests aren't blocked
                # while this chunk renders.
                audio_bytes = await asyncio.to_thread(
                    synthesize_chunk, chunk_text, voice_id, speed, volume
                )
                chunks_synthesized += 1
                logger.info(
                    "[voice/speak/stream] chunk %d/%d synthesized: %d bytes for %r",
                    i + 1, len(chunks), len(audio_bytes), chunk_text[:60],
                )
            except RuntimeError as exc:
                chunks_failed += 1
                logger.warning("[voice/speak/stream] chunk %d/%d FAILED, skipping: %s", i + 1, len(chunks), exc)
                continue
            except Exception as exc:
                # Catch anything beyond the expected RuntimeError too —
                # previously an unexpected exception type here would
                # propagate up and silently kill the whole generator,
                # ending the stream with zero frames sent and no log line
                # explaining why every chunk after the first failure
                # vanished.
                chunks_failed += 1
                logger.error("[voice/speak/stream] chunk %d/%d UNEXPECTED error, skipping: %s: %s", i + 1, len(chunks), type(exc).__name__, exc)
                continue

            length_prefix = len(audio_bytes).to_bytes(4, byteorder="big")
            yield length_prefix
            yield audio_bytes

        logger.info(
            "[voice/speak/stream] DONE: %d/%d chunks synthesized, %d failed",
            chunks_synthesized, len(chunks), chunks_failed,
        )
        if chunks_synthesized == 0:
            logger.error(
                "[voice/speak/stream] ALL %d chunk(s) failed — client will receive a "
                "zero-byte stream and no audio will play. Check edge-tts connectivity "
                "(network access to speech.platform.bing.com) and SSL certificates.",
                len(chunks),
            )

    return StreamingResponse(
        _frame_generator(),
        media_type="application/octet-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/voices")
def list_voices():
    """Return the curated list of available TTS voices."""
    return {"voices": VOICE_CATALOGUE}


@router.get("/settings")
def get_voice_settings():
    """Fetch the user's persisted voice preferences."""
    db = SessionLocal()
    try:
        return _get_voice_settings(db)
    finally:
        db.close()


@router.put("/settings")
def update_voice_settings(body: VoiceSettingsIn):
    """Upsert voice preferences."""
    db = SessionLocal()
    try:
        current = _get_voice_settings(db)
        updates = body.model_dump(exclude_none=True)

        if "speed" in updates:
            updates["speed"] = max(0.5, min(2.0, float(updates["speed"])))
        if "volume" in updates:
            updates["volume"] = max(0.1, min(1.0, float(updates["volume"])))

        current.update(updates)
        _set_voice_settings(db, current)
        return current
    finally:
        db.close()