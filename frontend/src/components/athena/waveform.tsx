/**
 * Phase 9 — Live Waveform Visualizer
 *
 * Renders 32 animated bars driven by real-time microphone amplitude data
 * from the voice store's waveformData array.
 *
 * States:
 *  listening  → blue bars, bouncy
 *  speaking   → purple/accent bars, gentle pulse
 *  processing → spinning gradient indicator
 *  idle       → flat baseline
 */

import { motion } from "framer-motion";
import { cn } from "@/lib/utils";
import type { VoicePhase } from "@/stores/voice";

interface WaveformProps {
  data: number[];      // 32 values in [0, 1]
  phase: VoicePhase;
  className?: string;
}

const BAR_COUNT = 32;

const phaseColor: Record<VoicePhase, string> = {
  idle:           "bg-muted-foreground/30",
  wake_listening: "bg-primary/40",
  listening:      "bg-primary",
  processing:     "bg-accent",
  speaking:       "bg-accent",
  error:          "bg-destructive/60",
};

export function Waveform({ data, phase, className }: WaveformProps) {
  const color = phaseColor[phase];
  const isActive = phase === "listening" || phase === "speaking";

  return (
    <div
      className={cn(
        "flex items-end justify-center gap-[2px] h-12",
        className,
      )}
      aria-label={`Voice waveform — ${phase}`}
      role="img"
    >
      {Array.from({ length: BAR_COUNT }, (_, i) => {
        const amplitude = data[i] ?? 0;
        // Minimum bar height = 3px, scales up to 48px (full h-12)
        const heightPct = Math.max(0.06, amplitude);

        return (
          <motion.div
            key={i}
            className={cn("w-[3px] rounded-full", color)}
            animate={{ scaleY: heightPct, opacity: isActive ? 1 : 0.5 }}
            transition={{
              duration: 0.08,
              ease: "easeOut",
            }}
            style={{
              height: 48,
              transformOrigin: "bottom",
            }}
          />
        );
      })}
    </div>
  );
}

// ── Compact inline waveform for the composer bar ──────────────────────────────

export function MiniWaveform({ data, phase, className }: WaveformProps) {
  const isActive = phase === "listening";

  return (
    <div
      className={cn("flex items-end justify-center gap-[1px] h-5", className)}
      aria-hidden
    >
      {Array.from({ length: 12 }, (_, i) => {
        // Sample from 32 data points down to 12
        const idx = Math.floor((i / 12) * data.length);
        const amplitude = data[idx] ?? 0;
        const heightPct = Math.max(0.1, amplitude);

        return (
          <motion.div
            key={i}
            className={cn(
              "w-[2px] rounded-full",
              isActive ? "bg-primary" : "bg-muted-foreground/40",
            )}
            animate={{ scaleY: heightPct }}
            transition={{ duration: 0.08, ease: "easeOut" }}
            style={{ height: 20, transformOrigin: "bottom" }}
          />
        );
      })}
    </div>
  );
}
