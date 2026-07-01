/**
 * frontend/src/components/athena/proactive-insights.tsx  —  Phase 23
 *
 * Renders the small "Athena noticed something" feed: undismissed
 * ProactiveInsight rows the backend's background engine
 * (core/proactive_engine.py) generated on its own, without the user
 * asking anything. Polls periodically rather than using a websocket —
 * an insight is, by design, generated at most once every
 * PROACTIVE_MIN_GAP_MINUTES per user, so a 2-minute poll interval is
 * more than fast enough and keeps this component dependency-free.
 *
 * Renders nothing at all (not even a placeholder) when there's nothing
 * to show — this is meant to feel like an occasional aside, never a
 * permanent fixture taking up space on the home screen.
 */
import { useCallback, useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Sparkles, X } from "lucide-react";
import { proactiveApi, type ProactiveInsight } from "@/lib/proactive-api";
import { isLive } from "@/lib/api";
import { useAuth } from "@/stores/auth";

const POLL_INTERVAL_MS = 2 * 60 * 1000;

export function ProactiveInsightsFeed({
  onHasInsightChange,
}: {
  /** Phase 24: lets a parent (the home screen) know whether this banner
   *  is currently showing anything, so a sibling widget can avoid
   *  independently repeating the same fact (e.g. an overdue reminder). */
  onHasInsightChange?: (hasInsight: boolean) => void;
} = {}) {
  const { user, initializing } = useAuth();
  const [insights, setInsights] = useState<ProactiveInsight[]>([]);

  const load = useCallback(async () => {
    if (!isLive) return;
    try {
      const rows = await proactiveApi.list();
      setInsights(rows);
    } catch {
      // Best-effort widget — a failed poll just means nothing renders
      // this cycle, not a user-facing error state.
    }
  }, []);

  useEffect(() => {
    onHasInsightChange?.(insights.length > 0);
  }, [insights.length, onHasInsightChange]);

  useEffect(() => {
    if (initializing || !user || !isLive) return;
    load();
    const t = setInterval(load, POLL_INTERVAL_MS);
    return () => clearInterval(t);
  }, [initializing, user, load]);

  const dismiss = async (id: number) => {
    // Optimistic — remove immediately, don't make the user wait on the
    // network round-trip to see it go away.
    setInsights((prev) => prev.filter((i) => i.id !== id));
    try {
      await proactiveApi.dismiss(id);
    } catch {
      // If the dismiss call failed, the next poll cycle will bring it
      // back — acceptable for a low-stakes nudge like this.
    }
  };

  if (insights.length === 0) return null;

  // Show one at a time, not a stack — this is meant to feel like Athena
  // saying one thing, not a pile of banners competing for attention.
  // Dismissing (or the next poll clearing) the top one reveals the next,
  // rather than showing all of them simultaneously.
  const visible = insights.slice(0, 1);

  return (
    <div className="w-full max-w-xl mx-auto mb-6 space-y-2">
      <AnimatePresence initial={false}>
        {visible.map((insight) => (
          <motion.div
            key={insight.id}
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, height: 0, marginBottom: 0 }}
            className="flex items-start gap-3 rounded-xl border border-primary/20 bg-primary/5 px-4 py-3"
          >
            <Sparkles className="size-4 text-primary shrink-0 mt-0.5" />
            <p className="text-sm flex-1 leading-relaxed">{insight.message}</p>
            <button
              onClick={() => dismiss(insight.id)}
              className="text-muted-foreground hover:text-foreground shrink-0"
              aria-label="Dismiss"
            >
              <X className="size-3.5" />
            </button>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}
