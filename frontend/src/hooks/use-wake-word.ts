/**
 * Phase 9 — Wake Word Detection Hook
 *
 * Runs a lightweight background listening loop when wake_word_enabled=true.
 * When the wake phrase is detected in the transcribed audio, it fires
 * the onWakeWord callback and stops background listening.
 *
 * Uses the Web Speech API SpeechRecognition if available (Chrome/Edge)
 * for low-latency wake word detection — no audio upload required.
 * Falls back gracefully on unsupported browsers.
 */

import { useEffect, useRef, useCallback } from "react";

interface UseWakeWordOptions {
  phrase: string;         // e.g. "hey athena" or "athena"
  enabled: boolean;
  paused: boolean;        // true while user is already in conversation
  onWakeWord: () => void;
}

export function useWakeWord({
  phrase,
  enabled,
  paused,
  onWakeWord,
}: UseWakeWordOptions) {
  const recognitionRef = useRef<SpeechRecognition | null>(null);
  const activeRef = useRef(false);
  const onWakeWordRef = useRef(onWakeWord);
  onWakeWordRef.current = onWakeWord;

  const normalise = (s: string) =>
    s.toLowerCase().replace(/[^a-z0-9 ]/g, "").trim();

  const start = useCallback(() => {
    const SR =
      (window as Window & { SpeechRecognition?: typeof SpeechRecognition; webkitSpeechRecognition?: typeof SpeechRecognition }).SpeechRecognition ||
      (window as Window & { SpeechRecognition?: typeof SpeechRecognition; webkitSpeechRecognition?: typeof SpeechRecognition }).webkitSpeechRecognition;

    if (!SR) return; // Browser doesn't support Web Speech API

    if (recognitionRef.current) {
      try { recognitionRef.current.stop(); } catch { /* ignore */ }
    }

    const recognition = new SR();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = "en-US";
    recognition.maxAlternatives = 1;

    recognition.onresult = (event: SpeechRecognitionEvent) => {
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const transcript = normalise(event.results[i][0].transcript);
        const target = normalise(phrase);
        if (transcript.includes(target)) {
          activeRef.current = false;
          try { recognition.stop(); } catch { /* ignore */ }
          onWakeWordRef.current();
          return;
        }
      }
    };

    recognition.onerror = (event: SpeechRecognitionErrorEvent) => {
      // Phase 24 fix: "no-speech" fires constantly during normal
      // continuous listening (any few-second gap where nobody's talking
      // triggers it) -- it's not a real error, just Chrome's way of
      // saying "nothing to report." Treating it the same as a genuine
      // error (network failure, mic permission revoked) and waiting a
      // full second before restarting meant the wake-word listener spent
      // a real chunk of its life sitting idle after every quiet moment --
      // directly adding to "why did it take so long to notice I said the
      // wake word." Restart it almost immediately instead; reserve the
      // longer backoff for errors that are actually unusual.
      if (!activeRef.current) return;
      const isNoSpeech = event?.error === "no-speech";
      setTimeout(() => { if (activeRef.current) start(); }, isNoSpeech ? 50 : 1000);
    };

    recognition.onend = () => {
      // Restart if still supposed to be active. Phase 24: shortened from
      // 200ms -- Chrome's SpeechRecognition doesn't support truly
      // unbounded continuous listening and silently ends the session
      // periodically even with no error at all; every one of those
      // silent restarts was adding 200ms of dead air where a spoken wake
      // word simply wouldn't be heard.
      if (activeRef.current) {
        setTimeout(() => { if (activeRef.current) start(); }, 50);
      }
    };

    recognitionRef.current = recognition;
    try {
      recognition.start();
    } catch {
      // Permission denied or already running — ignore
    }
  }, [phrase]);

  const stop = useCallback(() => {
    activeRef.current = false;
    if (recognitionRef.current) {
      try { recognitionRef.current.stop(); } catch { /* ignore */ }
      recognitionRef.current = null;
    }
  }, []);

  useEffect(() => {
    if (enabled && !paused) {
      activeRef.current = true;
      start();
    } else {
      stop();
    }

    return stop;
  }, [enabled, paused, start, stop]);
}
