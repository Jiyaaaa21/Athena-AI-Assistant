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
from backend.core.rate_limit import voice_rate_limiter_minute, voice_rate_limiter_daily, require_budget
from backend.voice.stt import transcribe_audio
from backend.voice.tts import (
    VOICE_CATALOGUE, synthesize, synthesize_stream_async,
    split_into_speakable_chunks, prepare_voice_params,
)

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

    # Phase 29: protects Groq Whisper / the Hugging Face Whisper fallback
    # -- a distinct shared resource from chat completions, so it has its
    # own budget rather than eating into the chat one.
    uid = get_current_user_id()
    require_budget(
        voice_rate_limiter_minute, voice_rate_limiter_daily,
        str(uid) if uid is not None else "unknown",
        minute_detail="Too many voice messages in a short time — please wait a moment.",
        daily_detail="You've hit today's voice transcription limit for this shared deployment. It resets in 24 hours.",
    )

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
        import time

        voice, rate_str, vol_str = prepare_voice_params(voice_id, speed, volume)
        chunks_synthesized = 0
        chunks_failed = 0

        for i, chunk_text in enumerate(chunks):
            try:
                # ── Phase 24 fix (real cause of "voice trails text") ────────
                # This used to call synthesize_chunk(), which buffers the
                # ENTIRE chunk's audio in memory before returning anything —
                # so even a single sentence had to finish synthesizing
                # completely, server-side, before the browser received one
                # byte. synthesize_stream_async() is the true-streaming path
                # that was already written (Phase 17) but never actually
                # wired into this endpoint. edge-tts's underlying protocol
                # genuinely streams audio as Microsoft's service produces
                # it, so switching to this gets real, not cosmetic,
                # time-to-first-audio improvement — the first sound reaches
                # the browser as soon as the first fraction of a second of
                # speech exists, not after the whole sentence does.
                #
                # Raw chunks straight off the websocket can be very small
                # (sometimes well under one MP3 frame), and the frontend's
                # StreamingPlaybackQueue treats each frame it receives as an
                # independent, separately-decodable <audio> source — too
                # fine-grained a raw chunk risks a frame that won't decode
                # on its own, producing an audible gap. So this buffers just
                # long enough to get a safely-decodable amount of audio,
                # flushing on a short timer rather than waiting for the
                # whole chunk: the FIRST flush goes out almost immediately
                # (50ms window) so time-to-first-audio stays low, and
                # subsequent flushes use a slightly wider window (150ms) to
                # keep the number of separate <audio> elements reasonable
                # for smooth back-to-back playback.
                first_flush_done = False
                audio_buffer = bytearray()
                window_start = time.monotonic()
                any_audio_this_chunk = False

                async for audio_bytes in synthesize_stream_async(chunk_text, voice, rate_str, vol_str):
                    audio_buffer.extend(audio_bytes)
                    any_audio_this_chunk = True
                    window_s = 0.05 if not first_flush_done else 0.15
                    if audio_buffer and (time.monotonic() - window_start) >= window_s:
                        length_prefix = len(audio_buffer).to_bytes(4, byteorder="big")
                        yield length_prefix
                        yield bytes(audio_buffer)
                        audio_buffer.clear()
                        window_start = time.monotonic()
                        first_flush_done = True

                if audio_buffer:
                    length_prefix = len(audio_buffer).to_bytes(4, byteorder="big")
                    yield length_prefix
                    yield bytes(audio_buffer)

                if not any_audio_this_chunk:
                    raise RuntimeError("edge-tts returned empty audio for this chunk")

                chunks_synthesized += 1
                logger.info(
                    "[voice/speak/stream] chunk %d/%d streamed for %r",
                    i + 1, len(chunks), chunk_text[:60],
                )
            except Exception as exc:
                chunks_failed += 1
                logger.warning("[voice/speak/stream] chunk %d/%d FAILED, skipping: %s", i + 1, len(chunks), exc)
                continue

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