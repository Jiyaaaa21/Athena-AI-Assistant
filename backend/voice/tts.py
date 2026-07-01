"""
Phase 9 — Text-to-Speech service.

ISSUE 4: Voice reliability improvements.
- Fixed asyncio.run() conflict when running inside an existing event loop (FastAPI)
- Uses concurrent.futures to run synthesis in a clean thread with its own event loop
- Added retry logic for transient edge-tts failures
- Improved error messages

Uses Microsoft Edge TTS (edge-tts) for natural, zero-cost synthesis.
Returns audio as MP3 bytes that can be streamed directly to the browser.
"""

from __future__ import annotations

import asyncio
import io
import concurrent.futures
from backend.core.logger import agent_logger as logger, error_logger

# ── Voice catalogue ───────────────────────────────────────────────────────────

VOICE_CATALOGUE: list[dict] = [
    {"id": "en-US-AriaNeural",     "label": "Aria (US, Female)",      "gender": "female", "locale": "en-US"},
    {"id": "en-US-JennyNeural",    "label": "Jenny (US, Female)",     "gender": "female", "locale": "en-US"},
    {"id": "en-GB-SoniaNeural",    "label": "Sonia (UK, Female)",     "gender": "female", "locale": "en-GB"},
    {"id": "en-AU-NatashaNeural",  "label": "Natasha (AU, Female)",   "gender": "female", "locale": "en-AU"},
    {"id": "en-IN-NeerjaNeural",   "label": "Neerja (IN, Female)",    "gender": "female", "locale": "en-IN"},
    {"id": "en-US-GuyNeural",      "label": "Guy (US, Male)",         "gender": "male",   "locale": "en-US"},
    {"id": "en-US-DavisNeural",    "label": "Davis (US, Male)",       "gender": "male",   "locale": "en-US"},
    {"id": "en-GB-RyanNeural",     "label": "Ryan (UK, Male)",        "gender": "male",   "locale": "en-GB"},
    {"id": "en-AU-WilliamNeural",  "label": "William (AU, Male)",     "gender": "male",   "locale": "en-AU"},
]

DEFAULT_VOICE = "en-US-AriaNeural"
_VALID_VOICE_IDS = {v["id"] for v in VOICE_CATALOGUE}


def _resolve_voice(voice_id: str | None) -> str:
    if voice_id and voice_id in _VALID_VOICE_IDS:
        return voice_id
    return DEFAULT_VOICE


def prepare_voice_params(voice_id: str | None, speed: float, volume: float) -> tuple[str, str, str]:
    """
    Resolves a voice_id + speed/volume floats into the (voice, rate_str,
    vol_str) triple edge-tts's Communicate() expects. Factored out so the
    true-streaming path (synthesize_stream_async, used by the
    /voice/speak/stream endpoint) computes this identically to the
    buffering path (synthesize(), below) without duplicating the
    percentage-formatting logic in two places.
    """
    voice = _resolve_voice(voice_id)
    rate_pct = int((speed - 1.0) * 100)
    rate_str = f"+{rate_pct}%" if rate_pct >= 0 else f"{rate_pct}%"
    vol_pct = int((volume - 1.0) * 100)
    vol_str = f"+{vol_pct}%" if vol_pct >= 0 else f"{vol_pct}%"
    return voice, rate_str, vol_str


async def _synthesize_async(text: str, voice: str, rate: str, volume: str) -> bytes:
    """Core async synthesis — returns full MP3 bytes."""
    import edge_tts

    communicate = edge_tts.Communicate(text, voice, rate=rate, volume=volume)
    buf = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            buf.write(chunk["data"])
    audio = buf.getvalue()
    if not audio:
        raise RuntimeError("edge-tts returned empty audio — the service may be temporarily unavailable.")
    return audio


async def synthesize_stream_async(text: str, voice: str, rate: str, volume: str):
    """
    Phase 17 — true streaming synthesis.

    edge_tts.Communicate.stream() already yields audio chunks as Microsoft's
    TTS service produces them (it's a websocket under the hood) — the old
    `_synthesize_async` was buffering all of that into one BytesIO and
    returning only once finished. This version yields each chunk through,
    so the very first audio bytes can reach the browser and start playing
    while the rest of the sentence is still being synthesized.
    """
    import edge_tts

    communicate = edge_tts.Communicate(text, voice, rate=rate, volume=volume)
    any_audio = False
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            any_audio = True
            yield chunk["data"]
    if not any_audio:
        raise RuntimeError("edge-tts returned empty audio — the service may be temporarily unavailable.")


def split_into_speakable_chunks(text: str) -> list[str]:
    """
    Phase 17 — split LLM output into TTS-ready chunks at natural speech
    boundaries (sentence end, or a hard length cap for run-on text/lists),
    so each chunk can be sent to TTS and start playing independently
    while later chunks are still being synthesized.

    This is also used to feed TTS incrementally as the LLM streams tokens:
    the caller accumulates text and calls this each time a new sentence
    boundary is crossed, rather than waiting for the full response.
    """
    import re

    # Strip markdown that shouldn't be spoken literally
    cleaned = re.sub(r"[*_`#]+", "", text)
    cleaned = re.sub(r"\n{2,}", ". ", cleaned)
    cleaned = cleaned.replace("\n", " ")

    # Split on sentence-ending punctuation, keeping the punctuation
    raw_sentences = re.split(r"(?<=[.!?])\s+", cleaned.strip())

    chunks: list[str] = []
    buffer = ""
    MAX_CHUNK_CHARS = 220  # keeps latency-to-first-audio low per chunk

    for sentence in raw_sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(buffer) + len(sentence) + 1 <= MAX_CHUNK_CHARS:
            buffer = f"{buffer} {sentence}".strip()
        else:
            if buffer:
                chunks.append(buffer)
            if len(sentence) > MAX_CHUNK_CHARS:
                # Single run-on sentence longer than the cap — split on commas
                parts = sentence.split(", ")
                sub = ""
                for p in parts:
                    if len(sub) + len(p) + 2 <= MAX_CHUNK_CHARS:
                        sub = f"{sub}, {p}".strip(", ")
                    else:
                        if sub:
                            chunks.append(sub)
                        sub = p
                if sub:
                    chunks.append(sub)
                buffer = ""
            else:
                buffer = sentence

    if buffer:
        chunks.append(buffer)

    return [c for c in chunks if c.strip()]


def _run_in_new_loop(text: str, voice: str, rate: str, volume: str) -> bytes:
    """
    ISSUE 4: Run synthesis in a fresh event loop in a worker thread.
    This avoids the 'asyncio.run() cannot be called when another loop is running'
    error that occurs when TTS is called from inside FastAPI's async context.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_synthesize_async(text, voice, rate, volume))
    finally:
        loop.close()


def synthesize_chunk(
    text: str,
    voice_id: str | None = None,
    speed: float = 1.0,
    volume: float = 1.0,
) -> bytes:
    """
    Phase 17 — synthesize a single short chunk (one sentence or a few),
    used by the chat streaming pipeline to speak each sentence as soon as
    it's available rather than waiting for the full response. Same
    retry/threading safety as synthesize(), just factored out so the
    streaming endpoint can call it per-chunk without re-deriving voice
    settings each time.
    """
    return synthesize(text, voice_id=voice_id, speed=speed, volume=volume)


def synthesize(
    text: str,
    voice_id: str | None = None,
    speed: float = 1.0,
    volume: float = 1.0,
) -> bytes:
    """
    Synchronous wrapper. Returns MP3 bytes ready for HTTP response.
    speed:  0.5–2.0  (1.0 = normal)
    volume: 0.1–1.0  (1.0 = 100%)

    ISSUE 4: Uses a thread executor to avoid event loop conflicts.
    Retries once on transient failure.
    """
    voice = _resolve_voice(voice_id)

    rate_pct = int((speed - 1.0) * 100)
    rate_str = f"+{rate_pct}%" if rate_pct >= 0 else f"{rate_pct}%"

    vol_pct = int((volume - 1.0) * 100)
    vol_str = f"+{vol_pct}%" if vol_pct >= 0 else f"{vol_pct}%"

    logger.info("[TTS] Synthesizing %d chars with voice=%s rate=%s", len(text), voice, rate_str)

    last_exc: Exception | None = None
    for attempt in range(2):  # retry once on failure
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_run_in_new_loop, text, voice, rate_str, vol_str)
                audio = future.result(timeout=30)
            logger.info("[TTS] Synthesis done: %d bytes (attempt %d)", len(audio), attempt + 1)
            return audio
        except Exception as exc:
            last_exc = exc
            error_logger.warning("[TTS] Attempt %d failed: %s", attempt + 1, exc)
            if attempt == 0:
                import time
                time.sleep(0.5)  # brief pause before retry

    error_logger.error("[TTS] All synthesis attempts failed: %s", last_exc)
    raise RuntimeError(f"TTS synthesis failed after retries: {last_exc}") from last_exc