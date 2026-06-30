/**
 * Phase 17 — Voice OS Store: streaming TTS + barge-in
 *
 * Major changes from Phase 15:
 *   1. speak() now uses voiceApi.speakStream() + StreamingPlaybackQueue
 *      instead of waiting for one giant audio blob. Athena starts
 *      speaking the first sentence almost immediately instead of after
 *      the entire response has rendered.
 *   2. New barge-in system: while Athena is speaking, a lightweight VAD
 *      runs concurrently on the mic (separate from the recording VAD).
 *      The instant it detects the user's voice, playback is hard-stopped
 *      and the mic starts recording for real — no need to press anything.
 *   3. speakIncremental() — lets the chat layer feed text as it streams
 *      from the LLM, sentence by sentence, rather than waiting for the
 *      full response before calling speak() at all.
 *
 * Phase 15 fixes (state machine, stuck "Waiting…" button, pendingRef
 * reset, transcript-vs-reply display, auto-close) are preserved as-is.
 */

import { create } from "zustand";
import { toast } from "sonner";
import { voiceApi, type VoiceSettings } from "@/lib/voice-api";
import { StreamingPlaybackQueue } from "@/lib/streaming-playback-queue";

// ── Types ─────────────────────────────────────────────────────────────────────

export type VoicePhase =
  | "idle"
  | "wake_listening"
  | "listening"
  | "processing"
  | "speaking"
  | "error";

export interface VoiceState {
  phase: VoicePhase;
  transcript: string;
  athenaReply: string;
  interimTranscript: string;
  waveformData: number[];
  settings: VoiceSettings;
  settingsLoaded: boolean;
  permissionDenied: boolean;
  continuousActive: boolean;
  /** True for the brief window where barge-in just fired and we're
   *  transitioning from speaking -> listening. Lets the UI show an
   *  instant visual cut rather than a delayed state change. */
  bargedIn: boolean;

  loadSettings: () => Promise<void>;
  updateSettings: (patch: Partial<VoiceSettings>) => Promise<void>;
  startListening: () => Promise<void>;
  stopListening: () => void;
  speak: (text: string, opts?: { onDone?: () => void }) => Promise<void>;
  /** Feed a chunk of in-progress LLM text. Call repeatedly as the
   *  response streams in; internally batches into speakable sentences
   *  and queues them for playback without waiting for the full text. */
  speakIncremental: (textSoFar: string) => void;
  /** Call once the LLM stream is finished, to flush any remaining
   *  partial sentence still sitting in the incremental buffer. */
  finishIncremental: (opts?: { onDone?: () => void }) => void;
  interrupt: () => void;
  startContinuous: (onTranscript: (t: string) => void) => void;
  stopContinuous: () => void;
  resetError: () => void;
}

const DEFAULT_SETTINGS: VoiceSettings = {
  voice_id: "en-US-AriaNeural",
  speed: 1.0,
  volume: 1.0,
  wake_word_enabled: false,
  wake_word: "Hey Athena",
  continuous_mode: false,
  auto_play: true,
  vad_enabled: true,
};

// ── Internal refs ─────────────────────────────────────────────────────────────

let _mediaRecorder: MediaRecorder | null = null;
// Phase 19 fix: track ACTUAL elapsed recording time, not blob byte size.
// Byte size is an unreliable proxy for "did real speech get captured" —
// webm/opus container overhead (codec init segment, cues) can easily
// exceed a few KB even for a genuinely near-silent clip, so a byte
// floor alone still let malformed/too-short recordings through to Groq,
// which rejected them with the same 400 "could not process file" error.
// Wall-clock duration between start() and stop() is a much more direct
// signal of whether there was time to capture anything meaningful.
let _recordingStartedAt = 0;
let _audioChunks: Blob[] = [];
let _audioCtx: AudioContext | null = null;
let _analyser: AnalyserNode | null = null;
let _micStream: MediaStream | null = null;
let _waveformRaf: number | null = null;
let _silenceTimer: ReturnType<typeof setTimeout> | null = null;
let _continuousCallback: ((t: string) => void) | null = null;
let _vadActive = false;

// Streaming TTS playback
let _playbackQueue: StreamingPlaybackQueue | null = null;
let _abortSpeakStream: (() => void) | null = null;
let _incrementalSentSoFar = ""; // tracks what's already been queued for speech

// Phase 18 — single-flight TTS dispatch state. Ensures only ONE
// /voice/speak/stream request is ever in flight at a time, fixing the
// multi-minute delay caused by firing one concurrent request per
// sentence (see speakIncremental's docstring for the full explanation).
let _ttsRequestInFlight = false;
let _ttsPendingText = "";        // text accumulated since the last dispatch
let _ttsAllTextReceived = false; // true once finishIncremental() has run

// Barge-in monitor — separate lightweight VAD that runs WHILE Athena is
// speaking, independent of the recording-mode VAD above.
let _bargeInCtx: AudioContext | null = null;
let _bargeInAnalyser: AnalyserNode | null = null;
let _bargeInStream: MediaStream | null = null;
let _bargeInActive = false;

// ── Waveform helpers ──────────────────────────────────────────────────────────

function _startWaveform(setState: (patch: Partial<VoiceState>) => void) {
  if (!_analyser) return;
  const data = new Uint8Array(_analyser.frequencyBinCount);
  function tick() {
    if (!_analyser) return;
    _analyser.getByteTimeDomainData(data);
    const bucketSize = Math.floor(data.length / 32);
    const buckets = Array.from({ length: 32 }, (_, i) => {
      let sum = 0;
      for (let j = 0; j < bucketSize; j++) sum += Math.abs(data[i * bucketSize + j] - 128);
      return Math.min(1, (sum / bucketSize) / 40);
    });
    setState({ waveformData: buckets });
    _waveformRaf = requestAnimationFrame(tick);
  }
  tick();
}

function _stopWaveform() {
  if (_waveformRaf !== null) { cancelAnimationFrame(_waveformRaf); _waveformRaf = null; }
}

function _getEnergyFrom(analyser: AnalyserNode | null): number {
  if (!analyser) return 0;
  const data = new Uint8Array(analyser.frequencyBinCount);
  analyser.getByteTimeDomainData(data);
  let sum = 0;
  for (let i = 0; i < data.length; i++) sum += Math.abs(data[i] - 128);
  return sum / data.length;
}

function _cleanupMic() {
  if (_micStream) { _micStream.getTracks().forEach((t) => t.stop()); _micStream = null; }
  if (_audioCtx) { _audioCtx.close().catch(() => {}); _audioCtx = null; _analyser = null; }
}

function _cleanupBargeInMonitor() {
  _bargeInActive = false;
  if (_bargeInStream) { _bargeInStream.getTracks().forEach((t) => t.stop()); _bargeInStream = null; }
  if (_bargeInCtx) { _bargeInCtx.close().catch(() => {}); _bargeInCtx = null; _bargeInAnalyser = null; }
}

// ── Sentence batching for incremental speech ──────────────────────────────────

/**
 * Given the full text-so-far and what's already been spoken, find any
 * NEW complete sentence(s) that have appeared since the last call and
 * return them as a single chunk ready to queue for TTS. Returns null if
 * no new complete sentence is available yet (still mid-sentence).
 */
function _extractNewSpeakableChunk(fullTextSoFar: string, alreadySpoken: string): string | null {
  if (!fullTextSoFar.startsWith(alreadySpoken)) {
    // Text was reset/regenerated — treat everything as new
    alreadySpoken = "";
  }
  const unspoken = fullTextSoFar.slice(alreadySpoken.length);
  if (!unspoken.trim()) return null;

  // Find the last sentence-ending punctuation in the unspoken portion
  const match = unspoken.match(/^[\s\S]*?[.!?](?=\s|$)/);
  if (!match) return null; // no complete sentence yet

  return match[0];
}

// ── Store ─────────────────────────────────────────────────────────────────────

export const useVoice = create<VoiceState>()((set, get) => ({
  phase: "idle",
  transcript: "",
  athenaReply: "",
  interimTranscript: "",
  waveformData: new Array(32).fill(0),
  settings: DEFAULT_SETTINGS,
  settingsLoaded: false,
  permissionDenied: false,
  continuousActive: false,
  bargedIn: false,

  loadSettings: async () => {
    try {
      const settings = await voiceApi.getSettings();
      set({ settings, settingsLoaded: true });
    } catch {
      set({ settings: DEFAULT_SETTINGS, settingsLoaded: true });
    }
  },

  updateSettings: async (patch) => {
    const optimistic = { ...get().settings, ...patch };
    set({ settings: optimistic });
    try {
      const saved = await voiceApi.updateSettings(patch);
      set({ settings: saved });
    } catch {
      toast.error("Failed to save voice settings");
    }
  },

  startListening: async () => {
    const { phase } = get();
    if (phase === "listening" || phase === "processing") return;
    get().interrupt();

    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true },
      });
    } catch {
      set({ permissionDenied: true, phase: "error" });
      toast.error("Microphone permission denied.");
      return;
    }

    _micStream = stream;
    set({ phase: "listening", permissionDenied: false, interimTranscript: "", transcript: "", athenaReply: "", bargedIn: false });

    try {
      _audioCtx = new AudioContext();
      _analyser = _audioCtx.createAnalyser();
      _analyser.fftSize = 256;
      const source = _audioCtx.createMediaStreamSource(stream);
      source.connect(_analyser);
      _startWaveform(set);
    } catch { /* non-fatal */ }

    const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
      ? "audio/webm;codecs=opus"
      : MediaRecorder.isTypeSupported("audio/webm") ? "audio/webm" : "";

    _audioChunks = [];
    _mediaRecorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    _mediaRecorder.ondataavailable = (e) => { if (e.data.size > 0) _audioChunks.push(e.data); };

    _mediaRecorder.onstop = async () => {
      _stopWaveform();
      _cleanupMic();

      // Phase 19 fix: gate on actual elapsed recording duration, not
      // blob byte size. Webm/opus container overhead (codec init
      // segment, cues) can exceed a few KB even for a near-silent clip,
      // so a byte floor alone still let malformed/too-short recordings
      // reach Groq, which rejected them with the same 400 error.
      // Wall-clock duration between start() and stop() is a far more
      // direct signal of whether there was time to capture anything.
      const recordingDurationMs = Date.now() - _recordingStartedAt;
      const MIN_RECORDING_MS = 600;
      const totalBytes = _audioChunks.reduce((sum, c) => sum + c.size, 0);

      const recoverByRelistening = () => {
        set({ phase: "idle", waveformData: new Array(32).fill(0) });
        if (_continuousCallback) {
          setTimeout(() => { if (useVoice.getState().phase === "idle") useVoice.getState().startListening(); }, 300);
        }
      };

      if (_audioChunks.length === 0 || totalBytes === 0 || recordingDurationMs < MIN_RECORDING_MS) {
        _audioChunks = [];
        recoverByRelistening();
        return;
      }

      const effectiveMime = mimeType || "audio/webm";
      const blob = new Blob(_audioChunks, { type: effectiveMime });
      _audioChunks = [];
      set({ phase: "processing", waveformData: new Array(32).fill(0) });

      try {
        const { text } = await voiceApi.transcribe(blob, effectiveMime);
        const trimmed = text.trim();
        set({ transcript: trimmed, phase: "idle" });
        if (trimmed && _continuousCallback) {
          _continuousCallback(trimmed);
        } else if (!trimmed) {
          recoverByRelistening();
        }
      } catch (err) {
        // Phase 19 fix: a transcription error used to set phase to
        // "error" and stop there — permanently breaking the hands-free
        // continuous loop on the first failed clip, dropping the user
        // back to "tap the orb to talk." Now: in continuous mode, log
        // quietly and just listen again instead of showing a disruptive
        // toast. One-shot mode (no _continuousCallback) still shows the
        // error, since there's no loop to recover into.
        if (_continuousCallback) {
          console.warn("[voice store] transcription failed, auto-recovering:", (err as Error).message);
          recoverByRelistening();
        } else {
          toast.error(`Transcription failed: ${(err as Error).message}`);
          set({ phase: "error" });
        }
      }
    };

    _recordingStartedAt = Date.now();
    _mediaRecorder.start(250);

    if (get().settings.vad_enabled) {
      _vadActive = true;
      _startVAD();
    }
  },

  stopListening: () => {
    _vadActive = false;
    if (_silenceTimer) { clearTimeout(_silenceTimer); _silenceTimer = null; }
    if (_mediaRecorder && _mediaRecorder.state === "recording") {
      _mediaRecorder.stop();
    } else {
      _cleanupMic();
      set({ phase: "idle", waveformData: new Array(32).fill(0) });
    }
  },

  /**
   * Phase 17 — streaming speak(). Splits text into sentence chunks
   * server-side and plays each chunk as it arrives via a
   * StreamingPlaybackQueue, instead of waiting for one giant blob.
   * Also starts the barge-in monitor for the duration of playback.
   */
  speak: async (text, opts) => {
    if (!text.trim()) { opts?.onDone?.(); return; }
    const { settings } = get();
    if (!settings.auto_play) { opts?.onDone?.(); return; }

    set({ phase: "speaking", athenaReply: text, bargedIn: false });
    _startBargeInMonitor();

    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true;
      _cleanupBargeInMonitor();
      _playbackQueue = null;
      _abortSpeakStream = null;
      // Only clear phase if we weren't interrupted out of it already
      if (get().phase === "speaking") set({ phase: "idle", athenaReply: "" });
      opts?.onDone?.();
    };

    const queue = new StreamingPlaybackQueue({
      onError: (err) => {
        // A single chunk failing to decode/play shouldn't interrupt the
        // whole response with a disruptive toast — StreamingPlaybackQueue
        // already recovers automatically by skipping to the next chunk.
        // Log it for diagnosis without breaking the user's flow.
        console.warn("[voice store] chunk playback error (auto-recovering):", err.message);
      },
      onAllDone: finish,
    });
    _playbackQueue = queue;

    _abortSpeakStream = voiceApi.speakStream(
      text,
      (chunkBlob) => queue.push(chunkBlob),
      () => queue.markComplete(),
      (err) => {
        toast.error(`Speech failed: ${err.message}`);
        finish();
      },
      { voice_id: settings.voice_id, speed: settings.speed, volume: settings.volume },
    );
  },

  /**
   * Phase 18 fix — incremental speech, single connection at a time.
   *
   * ROOT CAUSE of the 1-2 minute delay before any audio plays: the
   * previous version called voiceApi.speakStream() ONCE PER SENTENCE,
   * each one opening a brand-new HTTP request to /voice/speak/stream.
   * For a long response with 15+ sentences, that's 15+ concurrent
   * fetches fired in quick succession. Browsers cap concurrent
   * connections to a single origin at 6 (Chrome/Firefox) — so requests
   * 7 onward sat queued in the browser's network stack, not even
   * starting, until earlier ones finished. Worse, since they were
   * independent unordered requests, nothing guaranteed sentence 3's
   * audio arrived before sentence 1's — chunks could play out of order.
   *
   * Fix: a single-flight sequential dispatcher. Only one
   * /voice/speak/stream request is ever in flight at a time. New
   * sentences detected while a request is already running are appended
   * to a pending buffer instead of firing their own request; the moment
   * the in-flight request finishes, the dispatcher immediately fires
   * the NEXT request with whatever text has accumulated in the buffer
   * since then. This keeps strict ordering, uses exactly one connection
   * per voice turn instead of 15+, and still starts speaking on the
   * very first sentence almost immediately rather than waiting for the
   * full response.
   */
  speakIncremental: (textSoFar) => {
    const { settings, phase } = get();
    if (!settings.auto_play) return;

    if (phase !== "speaking") {
      set({ phase: "speaking", bargedIn: false });
      _startBargeInMonitor();
      _playbackQueue = new StreamingPlaybackQueue({
        onError: (err) => toast.error(`Speech failed: ${err.message}`),
        onAllDone: () => {
          _cleanupBargeInMonitor();
          _playbackQueue = null;
          if (get().phase === "speaking") set({ phase: "idle", athenaReply: "" });
        },
      });
      _incrementalSentSoFar = "";
      _ttsRequestInFlight = false;
      _ttsPendingText = "";
    }

    set({ athenaReply: textSoFar });

    const newChunk = _extractNewSpeakableChunk(textSoFar, _incrementalSentSoFar);
    if (newChunk) {
      _incrementalSentSoFar += newChunk;
      _ttsPendingText += newChunk;
      _dispatchNextTtsRequestIfIdle();
    }
  },

  finishIncremental: (opts) => {
    const fullText = get().athenaReply;
    const remaining = fullText.slice(_incrementalSentSoFar.length).trim();
    if (remaining) {
      _incrementalSentSoFar = fullText;
      _ttsPendingText += (_ttsPendingText ? " " : "") + remaining;
    }
    _ttsAllTextReceived = true;

    if (_ttsPendingText.trim()) {
      // There's unsent text (either the final partial sentence, or text
      // that arrived while a request was in flight) — dispatch it now.
      // The dispatcher's own onDone will call markComplete() once this
      // (possibly last) request finishes and nothing else is pending.
      _dispatchNextTtsRequestIfIdle();
    } else if (!_ttsRequestInFlight) {
      // Nothing pending and nothing in flight — every chunk has already
      // been dispatched and completed, so it's safe to mark the
      // playback queue complete right now.
      _playbackQueue?.markComplete();
    }
    // else: a request is still in flight with nothing new pending — its
    // own onDone will correctly call markComplete() when it finishes.

    if (!_playbackQueue || !_playbackQueue.isPlaying) {
      _cleanupBargeInMonitor();
      if (get().phase === "speaking") set({ phase: "idle", athenaReply: "" });
    }
    opts?.onDone?.();
  },

  /**
   * Hard interrupt — used both for manual "stop" clicks and for
   * barge-in. Immediately silences playback (no fade) and aborts any
   * in-flight TTS stream request.
   */
  interrupt: () => {
    if (_abortSpeakStream) { _abortSpeakStream(); _abortSpeakStream = null; }
    if (_playbackQueue) { _playbackQueue.stop(); _playbackQueue = null; }
    _cleanupBargeInMonitor();
    _incrementalSentSoFar = "";
    _ttsPendingText = "";
    _ttsRequestInFlight = false;
    _ttsAllTextReceived = false;
    if (get().phase === "speaking") set({ phase: "idle", athenaReply: "" });
  },

  startContinuous: (onTranscript) => {
    _continuousCallback = onTranscript;
    set({ continuousActive: true });
    get().startListening();
  },

  stopContinuous: () => {
    _continuousCallback = null;
    set({ continuousActive: false });
    get().interrupt();
    get().stopListening();
  },

  resetError: () => set({ phase: "idle" }),
}));

/**
 * Phase 18 — single-flight TTS dispatcher.
 *
 * Call this any time new text becomes available (more sentences detected,
 * or the LLM stream finished). If a request is already in flight, this
 * is a no-op — the newly-arrived text just sits in _ttsPendingText and
 * will be picked up automatically the moment the current request's
 * onDone fires. This guarantees exactly one /voice/speak/stream
 * connection at a time, in strict order, instead of one per sentence.
 */
function _dispatchNextTtsRequestIfIdle() {
  if (_ttsRequestInFlight) return;          // a request is already running — it'll pick up new text when it finishes
  if (!_ttsPendingText.trim()) return;      // nothing new to speak yet
  if (!_playbackQueue) return;              // no active speaking session

  const textToSend = _ttsPendingText;
  _ttsPendingText = "";
  _ttsRequestInFlight = true;

  const { settings } = useVoice.getState();
  const queue = _playbackQueue;

  _abortSpeakStream = voiceApi.speakStream(
    textToSend,
    (blob) => queue.push(blob),
    () => {
      // This request's frames have all arrived. Immediately check if
      // more text accumulated while we were waiting — if so, fire the
      // next request right away (still strictly sequential, but with
      // zero idle gap between requests).
      _ttsRequestInFlight = false;
      _abortSpeakStream = null;

      if (_ttsPendingText.trim()) {
        _dispatchNextTtsRequestIfIdle();
      } else if (_ttsAllTextReceived) {
        // No more text coming and nothing pending — the playback queue
        // can be told it's safe to finish once its current audio drains.
        queue.markComplete();
      }
    },
    (err) => {
      _ttsRequestInFlight = false;
      _abortSpeakStream = null;
      toast.error(`Speech failed: ${err.message}`);
      // Don't let one failed chunk silently kill the rest of the
      // response's speech — if more text is pending, keep going.
      if (_ttsPendingText.trim()) {
        _dispatchNextTtsRequestIfIdle();
      }
    },
    { voice_id: settings.voice_id, speed: settings.speed, volume: settings.volume },
  );
}

// ── Recording VAD (auto-stop after silence while the user is talking) ────────

const VAD_SILENCE_THRESHOLD = 8;
// Phase 19 fix: was 2200ms — Alexa/Siri stop listening within ~600-800ms
// of silence. 2.2 seconds of dead air after every single sentence was
// the single biggest source of "Athena feels slow" — it wasn't generation
// or TTS, it was just sitting there waiting to confirm you'd really
// stopped talking before even starting to process anything.
const VAD_SILENCE_DURATION_MS = 700;
const VAD_POLL_MS = 100;
// Phase 19 fix: with auto-start-on-open now firing immediately when the
// full-screen Voice Mode dialog appears, the user often hasn't begun
// speaking yet in the first few hundred milliseconds (reaction time to
// seeing the orb appear). Without a grace period, the fast 700ms VAD
// would count that initial silence and auto-stop the recording before
// any real speech was captured — sending Groq a near-empty/silent clip,
// which it correctly rejects with "could not process file: is it a
// valid media file?" This mirrors the grace period composer.tsx's
// separate inline-VAD implementation already had.
const VAD_STARTUP_GRACE_MS = 800;

function _startVAD() {
  let consecutiveSilent = 0;
  const startedAt = Date.now();
  function poll() {
    if (!_vadActive) return;
    if (Date.now() - startedAt < VAD_STARTUP_GRACE_MS) {
      setTimeout(poll, VAD_POLL_MS);
      return;
    }
    const energy = _getEnergyFrom(_analyser);
    if (energy < VAD_SILENCE_THRESHOLD) { consecutiveSilent++; } else { consecutiveSilent = 0; }
    if (consecutiveSilent * VAD_POLL_MS >= VAD_SILENCE_DURATION_MS) {
      _vadActive = false;
      useVoice.getState().stopListening();
      return;
    }
    setTimeout(poll, VAD_POLL_MS);
  }
  setTimeout(poll, 200);
}

// ── Barge-in monitor ──────────────────────────────────────────────────────────
//
// Runs ONLY while Athena is speaking. Opens a second, independent mic
// stream + analyser (separate from the recording pipeline above) purely
// to watch for the user starting to talk. The moment sustained voice
// energy is detected, it:
//   1. Hard-stops TTS playback (StreamingPlaybackQueue.stop())
//   2. Tears down the monitor stream
//   3. Immediately starts real recording via startListening()
//
// Uses a slightly higher threshold and shorter confirmation window than
// the silence-detection VAD above, since this needs to react fast (a
// laggy barge-in feels broken) while still ignoring background noise and
// the tail end of Athena's own voice leaking through the mic without
// echo cancellation fully suppressing it.

const BARGE_IN_THRESHOLD = 8.5;
const BARGE_IN_CONFIRM_MS = 220; // short — must feel instant
const BARGE_IN_POLL_MS = 60;

async function _startBargeInMonitor() {
  if (_bargeInActive) return;
  const { settings } = useVoice.getState();
  if (!settings.vad_enabled) return; // user disabled VAD entirely — no barge-in either

  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true },
    });
    _bargeInStream = stream;
    _bargeInCtx = new AudioContext();
    _bargeInAnalyser = _bargeInCtx.createAnalyser();
    _bargeInAnalyser.fftSize = 256;
    _bargeInCtx.createMediaStreamSource(stream).connect(_bargeInAnalyser);
  } catch {
    return; // mic unavailable — barge-in simply won't work this session
  }

  _bargeInActive = true;
  let consecutiveVoiced = 0;

  const poll = () => {
    if (!_bargeInActive) return;
    const energy = _getEnergyFrom(_bargeInAnalyser);
    if (energy > BARGE_IN_THRESHOLD) {
      consecutiveVoiced++;
    } else {
      consecutiveVoiced = 0;
    }
    if (consecutiveVoiced * BARGE_IN_POLL_MS >= BARGE_IN_CONFIRM_MS) {
      _bargeInActive = false;
      useVoice.setState({ bargedIn: true });
      const reuseStream = _bargeInStream;
      _bargeInStream = null;
      useVoice.getState().interrupt();
      if (reuseStream) {
        _beginListeningWithStream(reuseStream);
      } else {
        useVoice.getState().startListening();
      }
      return;
    }
    setTimeout(poll, BARGE_IN_POLL_MS);
  };
  setTimeout(poll, BARGE_IN_POLL_MS);
}

/** Start the real recording pipeline reusing an already-open MediaStream
 *  (used when barge-in hands off its monitor stream directly into
 *  recording, instead of closing it and re-requesting mic permission). */
function _beginListeningWithStream(stream: MediaStream) {
  const set = useVoice.setState;
  _micStream = stream;
  set({ phase: "listening", permissionDenied: false, interimTranscript: "", transcript: "", athenaReply: "", bargedIn: false });

  try {
    _audioCtx = new AudioContext();
    _analyser = _audioCtx.createAnalyser();
    _analyser.fftSize = 256;
    _audioCtx.createMediaStreamSource(stream).connect(_analyser);
    _startWaveform(set);
  } catch { /* non-fatal */ }

  const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
    ? "audio/webm;codecs=opus"
    : MediaRecorder.isTypeSupported("audio/webm") ? "audio/webm" : "";

  _audioChunks = [];
  _mediaRecorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
  _mediaRecorder.ondataavailable = (e) => { if (e.data.size > 0) _audioChunks.push(e.data); };

  _mediaRecorder.onstop = async () => {
    _stopWaveform();
    _cleanupMic();

    const recordingDurationMs = Date.now() - _recordingStartedAt;
    const MIN_RECORDING_MS = 600;
    const totalBytes = _audioChunks.reduce((sum, c) => sum + c.size, 0);

    const recoverByRelistening = () => {
      set({ phase: "idle", waveformData: new Array(32).fill(0) });
      if (_continuousCallback) {
        setTimeout(() => { if (useVoice.getState().phase === "idle") useVoice.getState().startListening(); }, 300);
      }
    };

    if (_audioChunks.length === 0 || totalBytes === 0 || recordingDurationMs < MIN_RECORDING_MS) {
      _audioChunks = [];
      recoverByRelistening();
      return;
    }

    const effectiveMime = mimeType || "audio/webm";
    const blob = new Blob(_audioChunks, { type: effectiveMime });
    _audioChunks = [];
    set({ phase: "processing", waveformData: new Array(32).fill(0) });
    try {
      const { text } = await voiceApi.transcribe(blob, effectiveMime);
      const trimmed = text.trim();
      set({ transcript: trimmed, phase: "idle" });
      if (trimmed && _continuousCallback) _continuousCallback(trimmed);
      else if (!trimmed) recoverByRelistening();
    } catch (err) {
      if (_continuousCallback) {
        console.warn("[voice store] transcription failed, auto-recovering:", (err as Error).message);
        recoverByRelistening();
      } else {
        toast.error(`Transcription failed: ${(err as Error).message}`);
        set({ phase: "error" });
      }
    }
  };

  _recordingStartedAt = Date.now();
  _mediaRecorder.start(250);
  if (useVoice.getState().settings.vad_enabled) {
    _vadActive = true;
    _startVAD();
  }
}
