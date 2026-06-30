/**
 * Phase 19 — Voice Mode: full-screen immersive redesign
 *
 * Previous versions used a small boxed Dialog/modal — settings toggles,
 * a labeled button, a bordered card. That reads as "a settings panel
 * with a microphone," not "a voice assistant." Real assistants (Siri,
 * Alexa app) take over the FULL screen the moment voice activates: a
 * large glowing presence, a big live caption, minimal chrome, nothing
 * fighting for attention.
 *
 * This rewrite keeps 100% of the underlying state machine logic from
 * prior phases (pendingRef/exchangeDoneRef tracking, auto-close timers,
 * barge-in via the voice store, continuous mode, settings) — only the
 * visual shell changed, from a Dialog component to a full-viewport
 * fixed overlay with backdrop blur.
 */

import { useEffect, useCallback, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X, Settings2, Square } from "lucide-react";
import { toast } from "sonner";
import { VoiceOrb } from "./voice-orb";
import { useVoice } from "@/stores/voice";
import { useAuth } from "@/stores/auth";
import { unlockAudioPlayback } from "@/lib/audio-unlock";
import { Switch } from "@/components/ui/switch";

interface VoiceDialogProps {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  onSendMessage: (text: string) => Promise<{ reply: string }>;
}

export function VoiceDialog({ open, onOpenChange, onSendMessage }: VoiceDialogProps) {
  const {
    phase,
    transcript,
    athenaReply,
    waveformData,
    settings,
    settingsLoaded,
    permissionDenied,
    continuousActive,
    loadSettings,
    startListening,
    stopListening,
    interrupt,
    startContinuous,
    stopContinuous,
    updateSettings,
    resetError,
  } = useVoice();

  const pendingRef = useRef(false);
  const idleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const exchangeDoneRef = useRef(false);
  const [showSettings, setShowSettings] = useState(false);
  const [, forceRerender] = useState(0); // exchangeDoneRef/pendingRef are refs — this forces a repaint when their derived UI needs updating

  // ── Close handler ────────────────────────────────────────────────────────
  const handleClose = useCallback(
    (o: boolean) => {
      if (!o) {
        interrupt();
        stopListening();
        stopContinuous();
        pendingRef.current = false;
        exchangeDoneRef.current = false;
        setShowSettings(false);
        if (idleTimerRef.current) clearTimeout(idleTimerRef.current);
      }
      onOpenChange(o);
    },
    [interrupt, stopListening, stopContinuous, onOpenChange],
  );

  // Close on Escape key — standard full-screen-overlay convention
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") handleClose(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, handleClose]);

  // ── Auto-close logic (unchanged from prior phases) ──────────────────────
  useEffect(() => {
    if (!open) {
      if (idleTimerRef.current) clearTimeout(idleTimerRef.current);
      return;
    }
    if (phase === "idle" && exchangeDoneRef.current && !continuousActive) {
      if (idleTimerRef.current) clearTimeout(idleTimerRef.current);
      idleTimerRef.current = setTimeout(() => handleClose(false), 8_000);
    } else if (phase === "idle" && !pendingRef.current && !continuousActive) {
      if (idleTimerRef.current) clearTimeout(idleTimerRef.current);
      idleTimerRef.current = setTimeout(() => handleClose(false), 120_000);
    } else {
      if (idleTimerRef.current) { clearTimeout(idleTimerRef.current); idleTimerRef.current = null; }
    }
    return () => { if (idleTimerRef.current) clearTimeout(idleTimerRef.current); };
  }, [open, phase, continuousActive, handleClose]);

  const { initializing: authInitializing, user: authUser } = useAuth();
  useEffect(() => {
    if (authInitializing || !authUser) return;
    if (!open) return;
    if (!settingsLoaded) loadSettings();
  }, [authInitializing, authUser, open, settingsLoaded, loadSettings]);

  // ── Shared transcript handler (unchanged logic from prior phases) ──────
  const handleTranscript = useCallback(
    async (text: string) => {
      if (!text.trim() || pendingRef.current) return;
      pendingRef.current = true;
      exchangeDoneRef.current = false;
      forceRerender((n) => n + 1);

      try {
        await onSendMessage(text);

        if (settings.auto_play) {
          const waitForSpeechToFinish = () =>
            new Promise<void>((resolve) => {
              const startedAt = Date.now();
              const SAFETY_CEILING_MS = 180_000;
              const check = () => {
                if (useVoice.getState().phase !== "speaking") { resolve(); return; }
                if (Date.now() - startedAt > SAFETY_CEILING_MS) {
                  console.warn("[VoiceDialog] waitForSpeechToFinish hit safety ceiling — forcing resolve");
                  resolve();
                  return;
                }
                setTimeout(check, 150);
              };
              check();
            });
          await waitForSpeechToFinish();
        }

        pendingRef.current = false;
        exchangeDoneRef.current = true;
        forceRerender((n) => n + 1);
        if (continuousActive) {
          exchangeDoneRef.current = false;
          setTimeout(() => startContinuous(handleTranscript), 400);
        }
      } catch (err) {
        toast.error(`Chat error: ${(err as Error).message}`);
        pendingRef.current = false;
        exchangeDoneRef.current = false;
        forceRerender((n) => n + 1);
      }
    },
    [onSendMessage, settings.auto_play, continuousActive, startContinuous],
  );

  // ── One-shot: watch for processing → idle transition ────────────────────
  const prevPhaseRef = useRef(phase);
  useEffect(() => {
    const prev = prevPhaseRef.current;
    prevPhaseRef.current = phase;
    if (prev === "processing" && phase === "idle" && transcript && !continuousActive) {
      handleTranscript(transcript);
    }
  }, [phase, transcript, continuousActive, handleTranscript]);

  // Phase 19 fix: "don't need to click on it" — the dialog previously
  // only auto-started the FIRST recording; every turn after that fell
  // back to idle and required a manual tap on the orb. That's not
  // hands-free, it's "auto-start once." Real assistants keep listening
  // after every reply until you explicitly stop them.
  //
  // Fix: the full-screen Voice Mode overlay now defaults to continuous
  // mode the instant it opens — startContinuous() (not plain
  // startListening()) sets _continuousCallback, which is what makes
  // every subsequent turn auto-relisten after Athena finishes speaking,
  // with no tap required. The "Continuous mode" toggle in settings still
  // works — turning it off falls back to the old manual tap-per-turn
  // behavior for anyone who prefers that.
  const autoStartedRef = useRef(false);
  useEffect(() => {
    if (open && !autoStartedRef.current && phase === "idle" && !pendingRef.current) {
      autoStartedRef.current = true;
      unlockAudioPlayback();
      startContinuous(handleTranscript);
    }
    if (!open) autoStartedRef.current = false;
  }, [open, phase, startContinuous, handleTranscript]);

  const isBusy = phase === "processing" || phase === "speaking" || (phase === "idle" && pendingRef.current);

  // Live status line — short, first-person, matches what's actually happening
  const statusLine = (() => {
    if (phase === "listening") return "Listening…";
    if (phase === "processing") return "Thinking…";
    if (phase === "speaking") return null; // caption shown separately, larger
    if (pendingRef.current) return "Thinking…";
    if (permissionDenied) return "Microphone access needed";
    return "Tap the orb to talk";
  })();

  if (!open) return null;

  return (
    <AnimatePresence>
      <motion.div
        key="voice-overlay"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.2 }}
        className="fixed inset-0 z-[100] flex flex-col items-center justify-center"
        style={{
          background:
            "radial-gradient(ellipse at center, rgba(30,20,45,0.97) 0%, rgba(12,8,20,0.99) 70%)",
        }}
        role="dialog"
        aria-modal="true"
        aria-label="Voice mode"
      >
        {/* Top bar — minimal chrome, just close + settings */}
        <div className="absolute top-0 inset-x-0 flex items-center justify-between px-5 pt-5 sm:px-8 sm:pt-8">
          <button
            onClick={() => setShowSettings((s) => !s)}
            className="size-10 grid place-items-center rounded-full text-white/50 hover:text-white/90 hover:bg-white/10 transition-colors"
            aria-label="Voice settings"
          >
            <Settings2 className="size-5" />
          </button>
          <button
            onClick={() => handleClose(false)}
            className="size-10 grid place-items-center rounded-full text-white/50 hover:text-white/90 hover:bg-white/10 transition-colors"
            aria-label="Close voice mode"
          >
            <X className="size-5" />
          </button>
        </div>

        {/* Settings drawer — slides down from top, stays minimal */}
        <AnimatePresence>
          {showSettings && (
            <motion.div
              initial={{ opacity: 0, y: -12 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -12 }}
              className="absolute top-16 sm:top-20 inset-x-4 sm:inset-x-auto sm:right-8 sm:w-72 rounded-2xl bg-white/[0.07] backdrop-blur-xl border border-white/10 p-4 space-y-3"
            >
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-white/90">Continuous mode</p>
                  <p className="text-xs text-white/40">Auto-listen after each reply</p>
                </div>
                <Switch
                  checked={continuousActive}
                  disabled={phase !== "idle" || permissionDenied}
                  onCheckedChange={(checked) => {
                    if (checked) startContinuous(handleTranscript);
                    else stopContinuous();
                  }}
                />
              </div>
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-white/90">Auto-play replies</p>
                  <p className="text-xs text-white/40">Speak responses aloud</p>
                </div>
                <Switch
                  checked={settings.auto_play}
                  onCheckedChange={(v) => updateSettings({ auto_play: v })}
                />
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Center stage — the orb, large and unmissable */}
        <div className="flex flex-col items-center gap-8 px-6 max-w-lg w-full">
          <VoiceOrb
            phase={phase}
            waveformData={waveformData}
            transcript={phase === "speaking" ? undefined : undefined}
            athenaReply={athenaReply}
            continuousActive={continuousActive}
            onInterrupt={interrupt}
            onStopContinuous={stopContinuous}
            size="xl"
            onClick={() => {
              if (phase === "listening") { stopListening(); return; }
              if (isBusy) return;
              unlockAudioPlayback();
              exchangeDoneRef.current = false;
              startListening();
            }}
          />

          {/* Live caption — large, centered, what Siri does */}
          <div className="min-h-[3.5rem] flex items-center justify-center text-center px-4">
            {phase === "speaking" && athenaReply ? (
              <p className="text-white/90 text-lg sm:text-xl leading-snug font-medium max-w-md">
                {athenaReply.length > 140 ? athenaReply.slice(-140) : athenaReply}
              </p>
            ) : phase === "listening" && transcript ? (
              <p className="text-white/80 text-lg sm:text-xl leading-snug italic max-w-md">
                "{transcript}"
              </p>
            ) : (
              <p className="text-white/40 text-base sm:text-lg">{statusLine}</p>
            )}
          </div>

          {/* Stop button — only while speaking, minimal */}
          {phase === "speaking" && (
            <button
              onClick={interrupt}
              className="flex items-center gap-2 px-4 py-2 rounded-full bg-white/10 hover:bg-white/15 text-white/80 text-sm transition-colors"
            >
              <Square className="size-3 fill-current" /> Stop
            </button>
          )}

          {phase === "error" && (
            <button
              onClick={resetError}
              className="px-4 py-2 rounded-full bg-white/10 hover:bg-white/15 text-white/70 text-sm transition-colors"
            >
              Dismiss error
            </button>
          )}

          {permissionDenied && (
            <p className="text-center text-sm text-red-300/90 max-w-xs">
              Microphone access was denied. Allow it in your browser's site settings to use voice mode.
            </p>
          )}
        </div>

        {/* Bottom hint — auto-close notice, subtle */}
        {phase === "idle" && exchangeDoneRef.current && !continuousActive && (
          <p className="absolute bottom-8 inset-x-0 text-center text-xs text-white/30">
            Tap the orb to continue, or this will close shortly
          </p>
        )}
        {continuousActive && (
          <p className="absolute bottom-8 inset-x-0 text-center text-xs text-white/30">
            Continuous mode — say "stop" or tap the orb to pause
          </p>
        )}
      </motion.div>
    </AnimatePresence>
  );
}
