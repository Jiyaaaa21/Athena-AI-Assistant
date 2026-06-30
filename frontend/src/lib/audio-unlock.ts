/**
 * audio-unlock.ts  —  Phase 17 fix
 *
 * Browsers block HTMLAudioElement.play() unless it happens close enough
 * to a real user gesture in the call stack. Streaming TTS playback is
 * several async hops removed from the click that opened Voice Mode
 * (click -> open dialog -> mic recording -> transcription -> LLM stream
 * -> first sentence ready -> fetch -> queue.push -> play()), so by the
 * time the FIRST audio chunk is ready to play, the browser may no
 * longer consider it "close enough" to the original click and silently
 * reject playback — which is the exact "I can't hear any audio" bug.
 *
 * The fix is a well-known technique: play one completely silent,
 * effectively-zero-length audio clip SYNCHRONOUSLY inside the actual
 * click handler that opens Voice Mode. Most browsers (Chrome, Firefox,
 * Safari) treat a successfully-started play() as "this tab is now
 * allowed to play audio" for the remainder of the session — so every
 * subsequent play() call, even ones buried deep in async chains, is
 * then permitted.
 *
 * Call unlockAudioPlayback() directly inside the onClick handler that
 * opens Voice Mode (NOT inside a .then() or async function body — it
 * must be in the synchronous part of the click handler to count as
 * "close enough" to the gesture).
 */

let _unlocked = false;

// A ~0.1s silent MP3, base64-encoded inline so no network request is
// needed to unlock audio (a fetch would itself be async and defeat the
// purpose).
const SILENT_MP3_BASE64 =
  "//uQxAAAAAAAAAAAAAAAAAAAAAAAWGluZwAAAA8AAAACAAACcQCA" +
  "gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA" +
  "gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA" +
  "gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA" +
  "gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA" +
  "gICAgICAgICA";

export function unlockAudioPlayback() {
  if (_unlocked) return;
  try {
    const audio = new Audio(`data:audio/mpeg;base64,${SILENT_MP3_BASE64}`);
    audio.volume = 0;
    const playPromise = audio.play();
    if (playPromise) {
      playPromise
        .then(() => {
          _unlocked = true;
          audio.pause();
        })
        .catch(() => {
          // Still blocked — not fatal, later play() calls will just
          // each individually attempt and may themselves be blocked.
          // Logged so it's diagnosable rather than silently confusing.
          console.warn(
            "[audio-unlock] Initial unlock play() was blocked. " +
            "Voice playback may require an additional user interaction."
          );
        });
    }
  } catch (err) {
    console.warn("[audio-unlock] Failed to create unlock audio element:", err);
  }
}

export function isAudioUnlocked(): boolean {
  return _unlocked;
}
