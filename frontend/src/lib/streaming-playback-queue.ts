/**
 * StreamingPlaybackQueue  —  Phase 17
 *
 * Plays a sequence of audio Blobs back-to-back with no gap between them,
 * as they arrive from voiceApi.speakStream(). This is what turns a series
 * of separately-synthesized TTS chunks into what sounds like one
 * continuous voice, instead of audible stutters between sentences.
 *
 * Also the core of barge-in support: calling stop() immediately halts
 * whatever is currently playing and discards anything still queued —
 * critical for the "user starts talking, Athena shuts up instantly"
 * interaction. A setTimeout-based fade or anything that waits for the
 * current chunk to finish would feel laggy and broken; this is a hard
 * stop on the actual <audio> element.
 */

type QueueEvents = {
  onStart?: () => void;       // fired when the first chunk begins playing
  onChunkStart?: (index: number) => void;
  onAllDone?: () => void;     // fired when the queue is empty AND no more chunks are coming
  onError?: (err: Error) => void;
  /**
   * Fired repeatedly (~60fps) with a 0-1 amplitude reading of the audio
   * actually being played, so the UI (VoiceOrb) can react to Athena's
   * real voice energy instead of a canned animation loop. Purely
   * additive — if Web Audio analysis can't be set up for any reason
   * (unsupported browser, suspended AudioContext, etc.) this simply
   * never fires and playback proceeds exactly as before via the plain
   * HTMLAudioElement path.
   */
  onLevel?: (level: number) => void;
};

export class StreamingPlaybackQueue {
  private queue: Blob[] = [];
  private currentAudio: HTMLAudioElement | null = null;
  private playing = false;
  private stopped = false;
  private noMoreChunksExpected = false;
  private hasStartedOnce = false;
  private events: QueueEvents;
  private chunkIndex = 0;

  // Optional real-time amplitude analysis for onLevel. Set up lazily and
  // defensively — analysisAttempted gates a single setup attempt so a
  // failure doesn't retry (and doesn't throw) on every subsequent chunk.
  private analysisAttempted = false;
  private audioCtx: AudioContext | null = null;
  private analyser: AnalyserNode | null = null;
  private levelRaf: number | null = null;

  constructor(events: QueueEvents = {}) {
    this.events = events;
  }

  /** Push a new chunk onto the queue. Starts playback immediately if idle. */
  push(blob: Blob) {
    if (this.stopped) return;
    this.queue.push(blob);
    if (!this.playing) {
      this._playNext();
    }
  }

  /** Call once the source stream has no more chunks coming. */
  markComplete() {
    this.noMoreChunksExpected = true;
    // If the queue is already empty and nothing is playing, we're done now.
    if (!this.playing && this.queue.length === 0) {
      this.events.onAllDone?.();
    }
  }

  /**
   * Hard stop — used for barge-in. Immediately silences any currently
   * playing audio and discards everything still queued. No fade, no
   * waiting for the current sentence to finish — the user started
   * talking and Athena needs to go quiet NOW.
   */
  stop() {
    this.stopped = true;
    this.queue = [];
    if (this.currentAudio) {
      this.currentAudio.pause();
      this.currentAudio.src = "";
      this.currentAudio = null;
    }
    this.playing = false;
    this._stopLevelLoop();
    if (this.audioCtx) {
      this.audioCtx.close().catch(() => {});
      this.audioCtx = null;
      this.analyser = null;
    }
  }

  get isPlaying() {
    return this.playing;
  }

  /**
   * One-shot, defensive attempt to stand up a Web Audio analyser tapped
   * onto this queue's audio output. Only called if the caller actually
   * wants onLevel readings. Never throws — any failure just leaves
   * audioCtx/analyser null, and every call site checks for that before
   * touching the audio graph, falling back to plain, unmodified
   * HTMLAudioElement playback.
   */
  private _trySetupAnalysis() {
    if (this.analysisAttempted) return;
    this.analysisAttempted = true;
    if (!this.events.onLevel) return;
    try {
      const AudioContextCtor =
        window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (!AudioContextCtor) return;
      this.audioCtx = new AudioContextCtor();
      this.analyser = this.audioCtx.createAnalyser();
      this.analyser.fftSize = 256;
      // Analyser must reach destination or the tapped audio would be
      // silent — this is the one line that matters most for safety.
      this.analyser.connect(this.audioCtx.destination);
    } catch {
      this.audioCtx = null;
      this.analyser = null;
    }
  }

  /**
   * Routes one <audio> element's output through the analyser so onLevel
   * can read real amplitude. Returns true only if the tap is fully live
   * (context confirmed running) — if false, the caller leaves the audio
   * element to play directly through its default output, completely
   * unaffected by any of this.
   */
  private _tapForAnalysis(audio: HTMLAudioElement): boolean {
    if (!this.audioCtx || !this.analyser) return false;
    try {
      if (this.audioCtx.state === "suspended") {
        // Fire-and-forget resume; if it doesn't come back in time for
        // THIS chunk we simply skip tapping this one chunk and try
        // again on the next (the audioCtx persists for the queue's
        // lifetime, so a later chunk can still succeed).
        this.audioCtx.resume().catch(() => {});
      }
      if (this.audioCtx.state !== "running") return false;
      const source = this.audioCtx.createMediaElementSource(audio);
      source.connect(this.analyser);
      return true;
    } catch {
      return false;
    }
  }

  private _startLevelLoop() {
    if (!this.analyser || !this.events.onLevel) return;
    const data = new Uint8Array(this.analyser.frequencyBinCount);
    const tick = () => {
      if (!this.analyser || !this.playing) { this.levelRaf = null; return; }
      this.analyser.getByteTimeDomainData(data);
      let sum = 0;
      for (let i = 0; i < data.length; i++) sum += Math.abs(data[i] - 128);
      const level = Math.min(1, (sum / data.length) / 40);
      this.events.onLevel?.(level);
      this.levelRaf = requestAnimationFrame(tick);
    };
    tick();
  }

  private _stopLevelLoop() {
    if (this.levelRaf !== null) { cancelAnimationFrame(this.levelRaf); this.levelRaf = null; }
    this.events.onLevel?.(0);
  }

  private _playNext() {
    if (this.stopped) return;

    const next = this.queue.shift();
    if (!next) {
      this.playing = false;
      this._stopLevelLoop();
      if (this.noMoreChunksExpected) {
        this.events.onAllDone?.();
      }
      return;
    }

    this.playing = true;
    const url = URL.createObjectURL(next);
    const audio = new Audio(url);
    this.currentAudio = audio;

    // Best-effort, additive analyser tap. If this fails or the context
    // isn't confirmed running, `tapped` is false and audio.play() below
    // proceeds exactly as it always has — untouched direct playback.
    this._trySetupAnalysis();
    const tapped = this._tapForAnalysis(audio);
    if (tapped && this.levelRaf === null) this._startLevelLoop();

    if (!this.hasStartedOnce) {
      this.hasStartedOnce = true;
      this.events.onStart?.();
    }
    this.events.onChunkStart?.(this.chunkIndex++);

    audio.onended = () => {
      URL.revokeObjectURL(url);
      if (this.currentAudio === audio) this.currentAudio = null;
      this._playNext();
    };
    audio.onerror = () => {
      URL.revokeObjectURL(url);
      if (this.currentAudio === audio) this.currentAudio = null;

      // Surface the REAL reason instead of a generic message. HTMLMediaElement
      // exposes a MediaError with a numeric `code` — without this, "Audio
      // chunk playback failed" tells us nothing about whether the blob was
      // empty, malformed, or genuinely undecodable.
      const mediaError = audio.error;
      const codeNames: Record<number, string> = {
        1: "MEDIA_ERR_ABORTED",
        2: "MEDIA_ERR_NETWORK",
        3: "MEDIA_ERR_DECODE",
        4: "MEDIA_ERR_SRC_NOT_SUPPORTED",
      };
      const codeName = mediaError ? (codeNames[mediaError.code] ?? `unknown(${mediaError.code})`) : "no MediaError object";
      const blobSize = next.size;
      const detail = `${codeName}, blob size: ${blobSize} bytes, blob type: ${next.type}`;
      console.error("[StreamingPlaybackQueue] chunk playback failed:", detail, mediaError);

      this.events.onError?.(new Error(`Audio chunk playback failed (${codeName})`));
      this._playNext(); // skip the bad chunk, keep going
    };

    audio.play().catch((err) => {
      // Autoplay policies can reject play() if it's not close enough to a
      // user gesture in the call stack — this can happen here because
      // playback is several async hops removed from the original click/
      // tap (LLM token arrives -> speakIncremental -> fetch -> queue.push
      // -> play()). When this happens the OLD code died silently: it
      // reported the error but never called _playNext(), so the entire
      // rest of the queue just sat there forever with nothing audible
      // and no obvious symptom beyond an easy-to-miss toast.
      //
      // Fix: log loudly to the console (so this is diagnosable without
      // guessing), surface the error to the caller, AND keep draining
      // the queue — if the browser unblocks audio after the first user
      // interaction completes (common case: it blocks the very first
      // chunk but allows subsequent ones once ANY audio successfully
      // started elsewhere on the page), later chunks still have a
      // chance to play instead of the whole response going silent.
      console.error("[StreamingPlaybackQueue] audio.play() rejected:", err);
      URL.revokeObjectURL(url);
      if (this.currentAudio === audio) this.currentAudio = null;
      this.playing = false;
      this.events.onError?.(err);
      this._playNext();
    });
  }
}
