"""
Phase 9 — Speech-to-Text service.

Uses Groq's Whisper API for fast, accurate transcription.
Falls back to local SpeechRecognition (Google) if Groq key unavailable.

Fix: write audio to a real named temp file instead of BytesIO so that
Groq's SDK can reliably detect the container format from the filename.
BytesIO with a .name attribute works in some SDK versions but fails in
others — a real file on disk is unambiguous.
"""

from __future__ import annotations

import os
import tempfile

from backend.core.config import GROQ_API_KEY
from backend.core.logger import error_logger


def transcribe_audio(audio_bytes: bytes, mime_type: str = "audio/webm") -> str:
    """
    Transcribe raw audio bytes to text.
    Tries Groq Whisper first, falls back to SpeechRecognition + Google STT.
    """
    if GROQ_API_KEY:
        return _transcribe_groq(audio_bytes, mime_type)
    return _transcribe_fallback(audio_bytes)


def _transcribe_groq(audio_bytes: bytes, mime_type: str) -> str:
    """Use Groq's whisper-large-v3-turbo for sub-second transcription."""
    try:
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

    except Exception as exc:
        error_logger.error("[STT] Groq transcription failed: %s", exc)
        try:
            return _transcribe_fallback(audio_bytes)
        except Exception:
            raise RuntimeError(f"Transcription failed: {exc}") from exc


def _transcribe_fallback(audio_bytes: bytes) -> str:
    """Fallback: SpeechRecognition + Google Web Speech API."""
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
        error_logger.error("[STT] Fallback failed: %s", exc)
        raise RuntimeError(f"Transcription failed: {exc}") from exc
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass