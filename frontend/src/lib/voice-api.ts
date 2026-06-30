/**
 * Phase 9 — Voice OS API client
 *
 * Extends the existing api.ts pattern with voice-specific endpoints.
 * Import from here; api.ts is left unmodified.
 *
 * Fix (transcription): the filename appended to FormData must use an
 * extension that Groq Whisper accepts. We derive it from the actual
 * mimeType so "audio/webm;codecs=opus" → "recording.webm",
 * "audio/ogg;codecs=opus" → "recording.ogg", etc.
 */

import { API_BASE_URL, isLive } from "./api";
import { getAccessToken } from "@/stores/auth";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface VoiceEntry {
  id: string;
  label: string;
  gender: "male" | "female";
  locale: string;
}

export interface VoiceSettings {
  voice_id: string;
  speed: number;          // 0.5 – 2.0
  volume: number;         // 0.1 – 1.0
  wake_word_enabled: boolean;
  wake_word: string;
  continuous_mode: boolean;
  auto_play: boolean;
  vad_enabled: boolean;
}

export interface TranscribeResult {
  text: string;
  duration_ms: number;
}

// ── Default mock settings ─────────────────────────────────────────────────────

const MOCK_SETTINGS: VoiceSettings = {
  voice_id: "en-US-AriaNeural",
  speed: 1.0,
  volume: 1.0,
  wake_word_enabled: false,
  wake_word: "Hey Athena",
  continuous_mode: false,
  auto_play: true,
  vad_enabled: true,
};

const MOCK_VOICES: VoiceEntry[] = [
  { id: "en-US-AriaNeural",    label: "Aria (US, Female)",    gender: "female", locale: "en-US" },
  { id: "en-US-JennyNeural",   label: "Jenny (US, Female)",   gender: "female", locale: "en-US" },
  { id: "en-GB-SoniaNeural",   label: "Sonia (UK, Female)",   gender: "female", locale: "en-GB" },
  { id: "en-AU-NatashaNeural", label: "Natasha (AU, Female)", gender: "female", locale: "en-AU" },
  { id: "en-IN-NeerjaNeural",  label: "Neerja (IN, Female)",  gender: "female", locale: "en-IN" },
  { id: "en-US-GuyNeural",     label: "Guy (US, Male)",       gender: "male",   locale: "en-US" },
  { id: "en-US-DavisNeural",   label: "Davis (US, Male)",     gender: "male",   locale: "en-US" },
  { id: "en-GB-RyanNeural",    label: "Ryan (UK, Male)",      gender: "male",   locale: "en-GB" },
  { id: "en-AU-WilliamNeural", label: "William (AU, Male)",   gender: "male",   locale: "en-AU" },
];

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * Derive a Groq-compatible filename extension from the MediaRecorder mimeType.
 * Groq Whisper uses the filename extension to detect the container format —
 * sending "recording.webm" for "audio/ogg;codecs=opus" causes a 400 error.
 */
function mimeTypeToFilename(mimeType: string): string {
  const base = mimeType.toLowerCase().split(";")[0].trim();
  const extMap: Record<string, string> = {
    "audio/webm":  "recording.webm",
    "audio/ogg":   "recording.ogg",
    "audio/mp4":   "recording.mp4",
    "audio/mpeg":  "recording.mp3",
    "audio/wav":   "recording.wav",
    "audio/flac":  "recording.flac",
    "audio/x-m4a": "recording.m4a",
  };
  return extMap[base] ?? "recording.webm";
}

async function voiceRequest<T>(path: string, init?: RequestInit): Promise<T> {
  // Phase 16 fix: same race-condition guard as lib/api.ts's request() —
  // wait for auth restoration before firing, otherwise this goes out
  // with no Authorization header and gets a guaranteed 401.
  try {
    const { useAuth } = await import("@/stores/auth");
    let waited = 0;
    while (useAuth.getState().initializing && waited < 5000) {
      await new Promise((r) => setTimeout(r, 50));
      waited += 50;
    }
  } catch {
    // proceed anyway
  }

  const token = getAccessToken();
  const authHeader: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {};
  const res = await fetch(`${API_BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json", ...authHeader, ...(init?.headers ?? {}) },
    ...init,
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const d = await res.clone().json();
      if (typeof d?.detail === "string") detail = d.detail;
    } catch { /* ignore */ }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

function delay<T>(value: T, ms = 300): Promise<T> {
  return new Promise((r) => setTimeout(() => r(value), ms));
}

// ── API surface ───────────────────────────────────────────────────────────────

export const voiceApi = {
  /**
   * Upload raw audio bytes (from MediaRecorder) for transcription.
   * Returns { text, duration_ms }.
   *
   * The filename passed to FormData must match the actual container format
   * so Groq Whisper can parse it correctly. We derive it from mimeType.
   */
  transcribe: async (audioBlob: Blob, mimeType: string): Promise<TranscribeResult> => {
    if (!isLive) {
      await delay(null, 800);
      return { text: "Voice mode requires a live backend connection.", duration_ms: 800 };
    }

    const filename = mimeTypeToFilename(mimeType);

    const fd = new FormData();
    fd.append("audio", audioBlob, filename);   // ← correct extension for Groq
    fd.append("mime_type", mimeType);

    const token = getAccessToken();
    const res = await fetch(`${API_BASE_URL}/voice/transcribe`, {
      method: "POST",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: fd,
    });
    if (!res.ok) {
      let detail = `${res.status} ${res.statusText}`;
      try {
        const d = await res.clone().json();
        if (typeof d?.detail === "string") detail = d.detail;
      } catch { /* ignore */ }
      throw new Error(detail);
    }
    return res.json() as Promise<TranscribeResult>;
  },

  /**
   * Phase 17 — streaming synthesis.
   *
   * Calls /voice/speak/stream and reads the response as a sequence of
   * length-prefixed MP3 frames: [4-byte big-endian length][mp3 bytes]...
   * Invokes onChunk(blob) for each frame as soon as it's fully received,
   * so the caller can start playing chunk 1 while chunk 2 is still
   * arriving over the network / still being synthesized server-side.
   *
   * Returns a function to abort the stream early (used for barge-in —
   * if the user starts talking, stop pulling more audio immediately).
   */
  speakStream: (
    text: string,
    onChunk: (blob: Blob) => void,
    onDone: () => void,
    onError: (err: Error) => void,
    opts?: { voice_id?: string; speed?: number; volume?: number },
  ): (() => void) => {
    const controller = new AbortController();
    console.log("[speakStream] starting, text length:", text.length, "opts:", opts);

    (async () => {
      if (!isLive) {
        console.log("[speakStream] not live (mock mode) — skipping actual TTS");
        await delay(null, 300);
        onDone();
        return;
      }
      try {
        const token = getAccessToken();
        console.log("[speakStream] fetching /voice/speak/stream, has token:", !!token);
        const res = await fetch(`${API_BASE_URL}/voice/speak/stream`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
          body: JSON.stringify({ text, ...opts }),
          signal: controller.signal,
        });
        console.log("[speakStream] response status:", res.status, "ok:", res.ok, "has body:", !!res.body);
        if (!res.ok || !res.body) {
          const errText = await res.text().catch(() => "");
          throw new Error(`${res.status} ${res.statusText} ${errText}`);
        }

        const reader = res.body.getReader();
        let buffer = new Uint8Array(0);
        let totalBytesReceived = 0;
        let framesEmitted = 0;

        const appendToBuffer = (incoming: Uint8Array) => {
          const merged = new Uint8Array(buffer.length + incoming.length);
          merged.set(buffer, 0);
          merged.set(incoming, buffer.length);
          buffer = merged;
        };

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          if (value) {
            appendToBuffer(value);
            totalBytesReceived += value.length;
          }

          while (buffer.length >= 4) {
            const frameLen =
              (buffer[0] << 24) | (buffer[1] << 16) | (buffer[2] << 8) | buffer[3];
            if (buffer.length < 4 + frameLen) break;

            const frameBytes = buffer.slice(4, 4 + frameLen);
            buffer = buffer.slice(4 + frameLen);
            framesEmitted++;
            console.log(`[speakStream] frame ${framesEmitted} ready, ${frameBytes.length} bytes`);

            onChunk(new Blob([frameBytes], { type: "audio/mpeg" }));
          }
        }
        console.log(`[speakStream] stream done. Total bytes: ${totalBytesReceived}, frames emitted: ${framesEmitted}`);
        if (framesEmitted === 0) {
          console.warn("[speakStream] WARNING: stream completed but zero audio frames were emitted — nothing will play.");
        }
        onDone();
      } catch (err) {
        if ((err as Error).name === "AbortError") {
          console.log("[speakStream] aborted (expected for barge-in or dialog close)");
          return;
        }
        console.error("[speakStream] FAILED:", err);
        onError(err as Error);
      }
    })();

    return () => controller.abort();
  },

  /**
   * Synthesize text to speech.
   * Returns a Blob (audio/mpeg) ready for playback.
   */
  speak: async (
    text: string,
    opts?: { voice_id?: string; speed?: number; volume?: number },
  ): Promise<Blob> => {
    if (!isLive) {
      return delay(new Blob([], { type: "audio/mpeg" }), 400);
    }

    const token = getAccessToken();
    const res = await fetch(`${API_BASE_URL}/voice/speak`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: JSON.stringify({ text, ...opts }),
    });
    if (!res.ok) {
      let detail = `${res.status} ${res.statusText}`;
      try {
        const d = await res.clone().json();
        if (typeof d?.detail === "string") detail = d.detail;
      } catch { /* ignore */ }
      throw new Error(detail);
    }
    return res.blob();
  },

  /** List available TTS voices. */
  voices: async (): Promise<VoiceEntry[]> => {
    if (isLive) {
      const data = await voiceRequest<{ voices: VoiceEntry[] }>("/voice/voices");
      return data.voices;
    }
    return delay(MOCK_VOICES);
  },

  /** Fetch persisted voice preferences. */
  getSettings: async (): Promise<VoiceSettings> => {
    if (isLive) return voiceRequest<VoiceSettings>("/voice/settings");
    try {
      return { ...MOCK_SETTINGS, ...JSON.parse(localStorage.getItem("athena-voice") ?? "{}") };
    } catch {
      return { ...MOCK_SETTINGS };
    }
  },

  /** Update voice preferences (partial patch). */
  updateSettings: async (patch: Partial<VoiceSettings>): Promise<VoiceSettings> => {
    if (isLive) {
      return voiceRequest<VoiceSettings>("/voice/settings", {
        method: "PUT",
        body: JSON.stringify(patch),
      });
    }
    try {
      const current = JSON.parse(localStorage.getItem("athena-voice") ?? "{}");
      const updated = { ...MOCK_SETTINGS, ...current, ...patch };
      localStorage.setItem("athena-voice", JSON.stringify(updated));
      return delay(updated);
    } catch {
      return delay({ ...MOCK_SETTINGS, ...patch });
    }
  },
};