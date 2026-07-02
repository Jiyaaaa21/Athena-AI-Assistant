"""
Phase 9 — Speech-to-Text service.

Uses Groq's Whisper API for fast, accurate transcription.

Phase 26 fix: the old "fallback" (SpeechRecognition + Google Web Speech)
wrote the raw browser-recorded audio (webm/opus) into a file with a
".wav" extension and handed it straight to SpeechRecognition's AudioFile
reader. AudioFile only parses genuine WAV/AIFF/FLAC containers -- a
webm/opus blob just renamed to .wav fails to parse, so on real browser
recordings that "fallback" almost certainly raised immediately and did
nothing. It's kept below as a last-resort attempt (harmless, and it
would work if the incoming bytes ever genuinely are WAV), but the real
fallback is now Hugging Face's hosted Inference API running Whisper --
same HF_TOKEN already configured for rag/embedder.py, free, no card
required (https://huggingface.co/settings/tokens). HF's ASR pipeline
decodes webm/opus/ogg/mp4 server-side on their own infrastructure, so
there's no local format-conversion problem to solve here at all.

Order: Groq (fastest, best accuracy) -> Hugging Face Whisper (free,
handles the real audio format) -> SpeechRecognition (last resort).
"""

from __future__ import annotations

import os
import tempfile

from backend.core.config import GROQ_API_KEY
from backend.core.logger import error_logger

_HF_STT_MODEL = "openai/whisper-large-v3"


def transcribe_audio(audio_bytes: bytes, mime_type: str = "audio/webm") -> str:
    """
    Transcribe raw audio bytes to text. Tries each configured provider in
    order and only moves to the next on failure, so a Groq rate limit (or
    outage) doesn't take voice input down entirely.
    """
    errors: list[str] = []

    if GROQ_API_KEY:
        try:
            return _transcribe_groq(audio_bytes, mime_type)
        except Exception as exc:
            error_logger.error("[STT] Groq transcription failed: %s", exc)
            errors.append(f"groq: {exc}")

    if os.environ.get("HF_TOKEN"):
        try:
            return _transcribe_huggingface(audio_bytes)
        except Exception as exc:
            error_logger.error("[STT] Hugging Face transcription failed: %s", exc)
            errors.append(f"huggingface: {exc}")

    try:
        return _transcribe_fallback(audio_bytes)
    except Exception as exc:
        error_logger.error("[STT] SpeechRecognition fallback failed: %s", exc)
        errors.append(f"speech_recognition: {exc}")

    raise RuntimeError(
        "Transcription failed on every configured provider: " + "; ".join(errors)
    )


def _transcribe_groq(audio_bytes: bytes, mime_type: str) -> str:
    """Use Groq's whisper-large-v3-turbo for sub-second transcription."""
    from groq import Groq

    client = Groq(api_key=GROQ_API_KEY)

    # Map MIME type → file extension so Groq knows the container format.
    # Strip codec params (e.g. "audio/webm;codecs=opus" → "audio/webm")
    # before lookup.
    ext_map = {
        "audio/webm":  "webm",
        "audio/ogg":   "ogg",
        "audio/mp4":   "mp4",
        "audio/mpeg":  "mp3",
        "audio/wav":   "wav",
        "audio/flac":  "flac",
        "audio/x-m4a": "m4a",
    }
    base_mime = mime_type.lower().split(";")[0].strip()
    ext = ext_map.get(base_mime, "webm")

    # Write to a real temp file — Groq SDK reads the filename for format
    # detection, and BytesIO + .name is unreliable across SDK versions.
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            suffix=f".{ext}", delete=False
        ) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        with open(tmp_path, "rb") as audio_file:
            transcription = client.audio.transcriptions.create(
                file=audio_file,
                model="whisper-large-v3-turbo",
                response_format="text",
                language="en",
            )
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    text = (
        transcription.strip()
        if isinstance(transcription, str)
        else (transcription.text or "").strip()
    )
    return text


def _transcribe_huggingface(audio_bytes: bytes) -> str:
    """
    Free fallback: Hugging Face's hosted Inference API running Whisper.
    Raw audio bytes are sent as-is in whatever container the browser
    recorded (webm/opus, ogg, mp4, ...) -- HF's ASR pipeline decodes
    common formats server-side on their own infrastructure via ffmpeg, so
    no local conversion is needed here, unlike the SpeechRecognition
    fallback below.
    """
    from huggingface_hub import InferenceClient

    client = InferenceClient(
        provider="hf-inference",
        api_key=os.environ.get("HF_TOKEN"),
    )
    result = client.automatic_speech_recognition(audio_bytes, model=_HF_STT_MODEL)
    return (result.text or "").strip()


def _transcribe_fallback(audio_bytes: bytes) -> str:
    """
    Last-resort fallback: SpeechRecognition + Google Web Speech API (no
    API key required, but genuinely only works if audio_bytes is already
    a real WAV/AIFF/FLAC file -- it will fail on raw webm/opus browser
    recordings, which is the common case. Kept as a final, zero-config
    attempt after both providers above have already failed or aren't
    configured.
    """
    import speech_recognition as sr

    recognizer = sr.Recognizer()

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name

    try:
        with sr.AudioFile(tmp_path) as source:
            audio = recognizer.record(source)
        text = recognizer.recognize_google(audio)
        return text
    except sr.UnknownValueError:
        return ""
    except Exception as exc:
        raise RuntimeError(f"SpeechRecognition transcription failed: {exc}") from exc
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass