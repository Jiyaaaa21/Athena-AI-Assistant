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
  }

  get isPlaying() {
    return this.playing;
  }

  private _playNext() {
    if (this.stopped) return;

    const next = this.queue.shift();
    if (!next) {
      this.playing = false;
      if (this.noMoreChunksExpected) {
        this.events.onAllDone?.();
      }
      return;
    }

    this.playing = true;
    const url = URL.createObjectURL(next);
    const audio = new Audio(url);
    this.currentAudio = audio;

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
