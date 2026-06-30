/**
 * Phase 19 — Voice Orb, redesigned for full-screen immersive Voice Mode
 *
 * Previously a small (size-40) light-themed orb meant to sit inside a
 * boxed dialog with its own status text, transcript, and action buttons
 * stacked below it. The new VoiceDialog handles all of that chrome
 * itself (status line, live caption, stop button) in a dark full-screen
 * layout — so this component is now JUST the orb: large, glowing,
 * tappable, designed to be looked at against a dark backdrop the way
 * Siri's animated blob or Alexa's light ring is the entire visual focus.
 */

import { motion } from "framer-motion";
import { cn } from "@/lib/utils";
import { Waveform } from "./waveform";
import type { VoicePhase } from "@/stores/voice";

interface VoiceOrbProps {
  phase: VoicePhase;
  waveformData: number[];
  transcript?: string;
  athenaReply?: string;
  continuousActive?: boolean;
  onInterrupt?: () => void;
  onStopContinuous?: () => void;
  /** "xl" = full-screen immersive Voice Mode (default for new usage).
   *  "md" kept for any future compact embedding elsewhere. */
  size?: "md" | "xl";
  onClick?: () => void;
  className?: string;
}

const ORB_GRADIENT: Record<VoicePhase, string> = {
  idle:           "from-violet-500 via-fuchsia-500 to-purple-600",
  wake_listening: "from-violet-400/70 via-fuchsia-400/70 to-purple-500/70",
  listening:      "from-sky-400 via-cyan-400 to-blue-500",
  processing:     "from-fuchsia-500 via-purple-500 to-violet-600",
  speaking:       "from-fuchsia-400 via-pink-400 to-rose-400",
  error:          "from-red-500 to-orange-500",
};

const GLOW_COLOR: Record<VoicePhase, string> = {
  idle:           "rgba(168,85,247,0.45)",
  wake_listening: "rgba(168,85,247,0.3)",
  listening:      "rgba(56,189,248,0.5)",
  processing:     "rgba(192,38,211,0.45)",
  speaking:       "rgba(244,114,182,0.5)",
  error:          "rgba(239,68,68,0.45)",
};

export function VoiceOrb({
  phase,
  waveformData,
  continuousActive,
  size = "xl",
  onClick,
  className,
}: VoiceOrbProps) {
  const isAnimating = phase !== "idle" && phase !== "error";
  const dimension = size === "xl" ? 200 : 140;
  const innerDimension = size === "xl" ? 132 : 92;

  return (
    <div className={cn("flex flex-col items-center", className)}>
      <button
        type="button"
        onClick={onClick}
        disabled={!onClick}
        className="relative grid place-items-center rounded-full transition-transform active:scale-[0.97] disabled:cursor-default"
        style={{ width: dimension, height: dimension }}
        aria-label={phase === "idle" ? "Tap to talk" : phase}
      >
        {/* Outer glow halo — soft, large, color-coded to phase */}
        <motion.div
          className="absolute inset-0 rounded-full blur-2xl"
          style={{ background: GLOW_COLOR[phase] }}
          animate={{
            scale: isAnimating ? [1, 1.25, 1] : [1, 1.06, 1],
            opacity: isAnimating ? [0.6, 0.9, 0.6] : [0.35, 0.5, 0.35],
          }}
          transition={{ duration: phase === "listening" ? 1.4 : 2.2, repeat: Infinity, ease: "easeInOut" }}
        />

        {/* Secondary ring — gives depth, expands more loosely than the core */}
        <motion.div
          className="absolute rounded-full border border-white/20"
          style={{ width: dimension, height: dimension }}
          animate={{
            scale: isAnimating ? [1, 1.15, 1] : 1,
            opacity: isAnimating ? [0.5, 0, 0.5] : 0.25,
          }}
          transition={{ duration: 1.8, repeat: isAnimating ? Infinity : 0, ease: "easeOut" }}
        />

        {/* Core orb */}
        <motion.div
          animate={
            phase === "listening"
              ? { scale: [1, 1.07, 1] }
              : phase === "processing"
              ? { scale: [1, 0.94, 1], rotate: [0, 180, 360] }
              : phase === "speaking"
              ? { scale: [1, 1.05, 0.97, 1.04, 1] }
              : { scale: [1, 1.02, 1] }
          }
          transition={{
            duration: phase === "processing" ? 2.4 : phase === "listening" ? 1.1 : 1.8,
            repeat: Infinity,
            ease: "easeInOut",
          }}
          className={cn(
            "relative rounded-full bg-gradient-to-br shadow-[0_0_80px_-10px_rgba(168,85,247,0.6)] ring-1 ring-white/30",
            ORB_GRADIENT[phase],
          )}
          style={{ width: innerDimension, height: innerDimension }}
        >
          {/* Inner sheen — gives the orb a glassy, dimensional look rather
              than a flat circle */}
          <div
            className="absolute inset-0 rounded-full opacity-40"
            style={{
              background: "radial-gradient(circle at 35% 30%, rgba(255,255,255,0.9), transparent 55%)",
            }}
          />
        </motion.div>
      </button>

      {/* Waveform — visible only while listening, sits just under the orb */}
      <motion.div
        animate={{ opacity: phase === "listening" ? 1 : 0, height: phase === "listening" ? "auto" : 0 }}
        transition={{ duration: 0.25 }}
        className="mt-5 overflow-hidden"
      >
        <Waveform data={waveformData} phase={phase} className="w-56" />
      </motion.div>

      {continuousActive && phase === "idle" && (
        <p className="mt-3 text-xs text-white/40 tracking-wide uppercase">Continuous mode</p>
      )}
    </div>
  );
}
