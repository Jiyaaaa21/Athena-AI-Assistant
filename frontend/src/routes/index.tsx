import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useRef, useState, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Upload,
  Mic,
  Newspaper,
  StickyNote,
  Sparkles,
  TrendingUp,
  Lightbulb,
  FileSearch,
  AlertCircle,
  Clock,
  Target,
  FolderOpen,
  ChevronRight,
  RefreshCw,
  MessageCircle,
  CalendarDays,
} from "lucide-react";
import { Composer } from "@/components/athena/composer";
import { Message, ThinkingIndicator } from "@/components/athena/message";
import { VoiceDialog } from "@/components/athena/voice-dialog";
import { QuickChip } from "@/components/athena/quick-chip";
import { useChat } from "@/stores/chat";
import { useAuth } from "@/stores/auth";
import { briefingApi, type BriefingData } from "@/lib/api";
import { isLive, API_BASE_URL } from "@/lib/api";
import { unlockAudioPlayback } from "@/lib/audio-unlock";
import { useVoiceActivation } from "@/stores/voice-activation";
import { ProactiveInsightsFeed } from "@/components/athena/proactive-insights";

export const Route = createFileRoute("/")(  {
  head: () => ({
    meta: [
      { title: "Athena — Chat" },
      {
        name: "description",
        content:
          "Your intelligent foundation for focus. Chat, retrieve, and act with Athena.",
      },
      { property: "og:title", content: "Athena — Chat" },
      {
        property: "og:description",
        content: "Your intelligent foundation for focus.",
      },
    ],
  }),
  component: ChatHome,
});

const SUGGESTED_PROMPTS = [
  {
    tag: "Research",
    icon: FileSearch,
    text: "Summarize the key findings from my latest uploaded documents.",
  },
  {
    tag: "Productivity",
    icon: TrendingUp,
    text: "What's on my plate this week? Pull from reminders and notes.",
  },
  {
    tag: "Insight",
    icon: Lightbulb,
    text: "Compare the major themes in this week's AI news.",
  },
  {
    tag: "Draft",
    icon: Sparkles,
    text: "Draft a 5-bullet status update for my team based on recent activity.",
  },
];

// ── Personal Briefing Widget ──────────────────────────────────────────────────
//
// Phase 16 redesign: the previous layout scattered three disconnected
// blocks (greeting text, a 2-column stat grid, an oversized red "Needs
// attention" banner) down the page with no shared visual frame, leaving
// a large empty void beside the greeting on wide screens and making a
// single overdue item look like an alarm. Rebuilt as one cohesive card:
// a compact header row, three small stat pills inline (not full-width
// tiles), and a tightened single list merging overdue + upcoming with
// clear status dots instead of a separate full-width warning banner.

function BriefingWidget({
  onSend,
  suppressSpokenLine = false,
}: {
  onSend: (text: string) => void;
  /** True while ProactiveInsightsFeed is already showing something —
   *  Athena has already "spoken" once on this screen, so both the
   *  briefing's spoken line AND its itemized overdue/upcoming list are
   *  skipped, leaving only the aggregate counts row. Prevents the same
   *  specific reminder title from being named three times on one screen
   *  (insight banner + spoken line + itemized list). */
  suppressSpokenLine?: boolean;
}) {
  const [briefing, setBriefing] = useState<BriefingData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [now, setNow] = useState(new Date());
  const [calendarEvents, setCalendarEvents] = useState<{ id: string; title: string; start: string; allDay: boolean }[]>([]);
  const { user, initializing } = useAuth();

  // Phase 20: surface REAL Google Calendar events for today on the
  // briefing, not just internal reminders. Silently no-ops if calendar
  // isn't connected — this is a nice-to-have addition to the briefing,
  // not a blocking requirement.
  useEffect(() => {
    if (initializing || !user || !isLive) return;
    (async () => {
      try {
        const tok = (await import("@/stores/auth")).getAccessToken();
        const statusRes = await fetch(`${API_BASE_URL}/calendar/status`, {
          headers: tok ? { Authorization: `Bearer ${tok}` } : {},
        });
        if (!statusRes.ok) return;
        const status = await statusRes.json();
        if (!status.connected) return;

        const evRes = await fetch(`${API_BASE_URL}/calendar/events?days_ahead=1`, {
          headers: tok ? { Authorization: `Bearer ${tok}` } : {},
        });
        if (!evRes.ok) return;
        const data = await evRes.json();
        setCalendarEvents((data.events ?? []).slice(0, 3));
      } catch {
        // Calendar fetch is a nice-to-have on the briefing — fail silently
      }
    })();
  }, [initializing, user]);

  const load = useCallback(async () => {
    if (!isLive) { setLoading(false); return; }
    try {
      setLoading(true);
      setError(false);
      const data = await briefingApi.get();
      setBriefing(data);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (initializing) return;
    if (!user) { setLoading(false); return; }
    load();
  }, [initializing, user, load]);

  // Live clock — gives the page a pulse instead of feeling static
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 30_000);
    return () => clearInterval(t);
  }, []);

  const firstName = user?.name?.split(" ")[0] ?? "there";
  const timeStr = now.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  const dateStr = now.toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" });

  if (loading) {
    return (
      <div className="w-full max-w-xl mx-auto">
        <div className="flex items-center gap-3 mb-6">
          <div className="size-11 rounded-full bg-muted animate-pulse" />
          <div className="space-y-2">
            <div className="h-4 w-32 bg-muted rounded animate-pulse" />
            <div className="h-3 w-20 bg-muted rounded animate-pulse" />
          </div>
        </div>
        <div className="h-28 bg-muted rounded-2xl animate-pulse" />
      </div>
    );
  }

  if (error || !briefing) {
    return (
      <div className="flex flex-col items-center text-center pt-2">
        <PresenceOrb size={56} />
        <h2 className="athena-voice text-[26px] font-medium tracking-tight mt-4 mb-1.5">
          Good to see you, {firstName}.
        </h2>
        <p className="athena-voice italic text-muted-foreground text-[15px] max-w-xs leading-relaxed">
          I'm ready when you are — ask me anything, or upload a document to get started.
        </p>
      </div>
    );
  }

  const { greeting, summary, overdue_reminders, upcoming_reminders, goals, active_projects, recent_conversations, recent_notes } = briefing;

  const timeline = [
    ...overdue_reminders.slice(0, 2).map((r) => ({ ...r, status: "overdue" as const })),
    ...upcoming_reminders.slice(0, 3 - Math.min(overdue_reminders.length, 2)).map((r) => ({ ...r, status: "upcoming" as const })),
  ].slice(0, 3);

  const hasStats = summary.overdue_count > 0 || summary.upcoming_count > 0 || summary.goals_count > 0;
  const hasTimeline = timeline.length > 0;
  const hasGoalsOrProjects = goals.length > 0 || active_projects.length > 0;
  const isQuiet = !hasStats && !hasTimeline && !hasGoalsOrProjects;

  // First-person voice line — what an assistant would actually say,
  // not a stats-panel label. Picks the most relevant thing to surface.
  const spokenLine = (() => {
    if (overdue_reminders.length > 0) {
      const r = overdue_reminders[0];
      return `Heads up — "${r.title}" is overdue${overdue_reminders.length > 1 ? `, and ${overdue_reminders.length - 1} more ${overdue_reminders.length === 2 ? "is" : "are"} waiting` : ""}.`;
    }
    if (upcoming_reminders.length > 0) {
      const r = upcoming_reminders[0];
      return `Next up: "${r.title}"${r.due ? ` — ${r.due}` : ""}.`;
    }
    if (goals.length > 0) {
      return `You're making progress on ${goals.length === 1 ? "your goal" : `${goals.length} goals`} — want to keep going?`;
    }
    return "Nothing urgent on your plate. A good moment to start something new.";
  })();

  const activityItems = [
    ...recent_conversations.slice(0, 2).map((c) => ({
      kind: "conversation" as const,
      id: c.id,
      label: c.title,
      meta: c.updatedAt ? new Date(c.updatedAt).toLocaleDateString([], { month: "short", day: "numeric" }) : "",
    })),
    ...recent_notes.slice(0, 2).map((n) => ({
      kind: "note" as const,
      id: n.id,
      label: n.title,
      meta: "",
    })),
  ].slice(0, 4);

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="w-full max-w-xl mx-auto"
    >
      {/* Presence header — orb + name + live clock, not a stats title */}
      <div className="flex items-center gap-3.5 mb-1">
        <PresenceOrb size={44} active={hasTimeline} />
        <div className="min-w-0 flex-1">
          <h2 className="athena-voice text-[26px] font-medium tracking-tight leading-tight">
            {greeting}, {firstName}.
          </h2>
          <p className="text-[12px] text-muted-foreground">
            {dateStr} · {timeStr}
          </p>
        </div>
        <button
          onClick={load}
          className="shrink-0 text-muted-foreground hover:text-foreground p-1.5 rounded-lg hover:bg-muted transition-colors"
          title="Refresh"
        >
          <RefreshCw className="size-3.5" />
        </button>
      </div>

      {/* Spoken line — Athena talking, not a panel label. Skipped when
          Athena already "spoke" via the proactive insights feed above,
          so the same fact never gets surfaced twice in one breath. */}
      {suppressSpokenLine ? (
        <div className="mt-4" />
      ) : (
        <p className="athena-voice italic text-[16px] text-foreground/75 leading-relaxed mt-3 mb-5 pl-[58px]">
          "{spokenLine}"
        </p>
      )}

      {!isQuiet && (
        <div className="rounded-2xl border border-border/60 bg-card overflow-hidden mb-5 shadow-[0_2px_2px_-1px_rgba(0,0,0,0.03),0_12px_24px_-12px_rgba(0,0,0,0.10)] dark:shadow-[0_2px_2px_-1px_rgba(0,0,0,0.2),0_12px_24px_-12px_rgba(0,0,0,0.4)]">
          {hasStats && (
            <div className="flex items-stretch divide-x divide-border border-b border-border">
              {summary.overdue_count > 0 && (
                <button
                  onClick={() => onSend("Show me my overdue reminders and help me prioritize them")}
                  className="flex-1 flex items-center gap-2 px-4 py-3 hover:bg-destructive/5 transition-colors text-left"
                >
                  <span className="size-1.5 rounded-full bg-destructive shrink-0" />
                  <span className="text-sm">
                    <span className="font-semibold text-destructive">{summary.overdue_count}</span>
                    <span className="text-muted-foreground ml-1">overdue</span>
                  </span>
                </button>
              )}
              {summary.upcoming_count > 0 && (
                <button
                  onClick={() => onSend("What are my upcoming reminders for this week?")}
                  className="flex-1 flex items-center gap-2 px-4 py-3 hover:bg-amber-500/5 transition-colors text-left"
                >
                  <span className="size-1.5 rounded-full bg-amber-500 shrink-0" />
                  <span className="text-sm">
                    <span className="font-semibold">{summary.upcoming_count}</span>
                    <span className="text-muted-foreground ml-1">upcoming</span>
                  </span>
                </button>
              )}
              {summary.goals_count > 0 && (
                <button
                  onClick={() => onSend("Review my active goals and suggest what I should focus on today")}
                  className="flex-1 flex items-center gap-2 px-4 py-3 hover:bg-primary/5 transition-colors text-left"
                >
                  <span className="size-1.5 rounded-full bg-primary shrink-0" />
                  <span className="text-sm">
                    <span className="font-semibold">{summary.goals_count}</span>
                    <span className="text-muted-foreground ml-1">goals</span>
                  </span>
                </button>
              )}
            </div>
          )}

          {hasTimeline && !suppressSpokenLine && (
            <div className="px-4 py-3 space-y-0.5">
              {timeline.map((r) => (
                <button
                  key={`${r.status}-${r.id}`}
                  onClick={() =>
                    onSend(
                      r.status === "overdue"
                        ? `Help me handle this overdue task: "${r.title}"`
                        : `Tell me more about this reminder: "${r.title}"`
                    )
                  }
                  className="w-full flex items-center gap-2.5 py-1.5 text-left group rounded-lg hover:bg-muted/60 px-1.5 -mx-1.5 transition-colors"
                >
                  <span className={`size-1.5 rounded-full shrink-0 ${r.status === "overdue" ? "bg-destructive" : "bg-amber-500/70"}`} />
                  <span className="flex-1 text-sm text-foreground/85 truncate">{r.title}</span>
                  {r.due && <span className="text-[11px] text-muted-foreground shrink-0">{r.due}</span>}
                  <ChevronRight className="size-3 text-muted-foreground opacity-0 group-hover:opacity-60 transition-opacity shrink-0" />
                </button>
              ))}
            </div>
          )}

          {hasGoalsOrProjects && (
            <div className={`grid ${goals.length > 0 && active_projects.length > 0 ? "grid-cols-2 divide-x divide-border" : "grid-cols-1"} border-t border-border`}>
              {goals.length > 0 && (
                <div className="px-4 py-3">
                  <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide mb-2">Goals</p>
                  <div className="space-y-2">
                    {goals.slice(0, 2).map((g) => (
                      <button key={g.id} onClick={() => onSend(`What should I do today to make progress on my goal: "${g.title}"?`)} className="w-full text-left group">
                        <div className="text-[13px] text-foreground/85 truncate group-hover:text-foreground transition-colors">{g.title}</div>
                        <div className="mt-1 h-1 rounded-full bg-muted overflow-hidden">
                          <div className="h-full bg-primary/60 rounded-full transition-all" style={{ width: `${g.progress}%` }} />
                        </div>
                      </button>
                    ))}
                  </div>
                </div>
              )}
              {active_projects.length > 0 && (
                <div className="px-4 py-3">
                  <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide mb-2">Projects</p>
                  <div className="space-y-1.5">
                    {active_projects.slice(0, 3).map((p) => (
                      <button key={p.id} onClick={() => onSend(`Give me a status update on my project: "${p.name}". What should I do next?`)} className="w-full text-left text-[13px] text-foreground/85 hover:text-foreground flex items-center gap-2 group">
                        <span className="size-1 rounded-full bg-primary/40 shrink-0" />
                        <span className="flex-1 truncate">{p.name}</span>
                        <ChevronRight className="size-3 opacity-0 group-hover:opacity-60 transition-opacity shrink-0" />
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Phase 20: real Google Calendar events for today — distinct from
          internal reminders, this is the user's ACTUAL schedule */}
      {calendarEvents.length > 0 && (
        <div className="mb-5 rounded-2xl border border-border bg-card overflow-hidden">
          <div className="px-4 py-2.5 border-b border-border flex items-center gap-1.5">
            <CalendarDays className="size-3.5 text-primary" />
            <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">
              Today on your calendar
            </p>
          </div>
          <div className="px-4 py-2 space-y-0.5">
            {calendarEvents.map((ev) => (
              <button
                key={ev.id}
                onClick={() => onSend(`Tell me more about my calendar event "${ev.title}"`)}
                className="w-full flex items-center gap-2.5 py-1.5 text-left group rounded-lg hover:bg-muted/60 px-1.5 -mx-1.5 transition-colors"
              >
                <span className="size-1.5 rounded-full bg-primary/60 shrink-0" />
                <span className="flex-1 text-sm text-foreground/85 truncate">{ev.title}</span>
                {!ev.allDay && (
                  <span className="text-[11px] text-muted-foreground shrink-0">
                    {new Date(ev.start).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}
                  </span>
                )}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Recent activity — keeps the page alive below the headline card
          instead of trailing off into empty space */}
      {activityItems.length > 0 && (
        <div className="mb-5">
          <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide mb-2.5 pl-1">
            Recently
          </p>
          <div className="space-y-1">
            {activityItems.map((item) => (
              <button
                key={`${item.kind}-${item.id}`}
                onClick={() =>
                  onSend(
                    item.kind === "conversation"
                      ? `Let's continue our conversation about "${item.label}"`
                      : `Show me my note: "${item.label}"`
                  )
                }
                className="w-full flex items-center gap-2.5 py-1.5 px-2 -mx-2 rounded-lg hover:bg-muted/50 transition-colors text-left group"
              >
                {item.kind === "conversation" ? (
                  <MessageCircle className="size-3.5 text-muted-foreground shrink-0" />
                ) : (
                  <StickyNote className="size-3.5 text-muted-foreground shrink-0" />
                )}
                <span className="flex-1 text-[13px] text-foreground/75 truncate">{item.label}</span>
                {item.meta && <span className="text-[11px] text-muted-foreground shrink-0">{item.meta}</span>}
              </button>
            ))}
          </div>
        </div>
      )}

      {!hasStats && !hasTimeline && (
        <div className="grid grid-cols-2 gap-2.5">
          {SUGGESTED_PROMPTS.map((p) => {
            const Icon = p.icon;
            return (
              <button key={p.text} onClick={() => onSend(p.text)} className="p-3.5 rounded-xl border border-border bg-card text-left hover:border-primary/30 hover:bg-primary/[0.03] transition-all group">
                <div className="flex items-center gap-1.5 text-[11px] font-medium text-primary mb-1.5">
                  <Icon className="size-3" />
                  {p.tag}
                </div>
                <div className="text-[13px] text-foreground/85 leading-snug line-clamp-2">{p.text}</div>
              </button>
            );
          })}
        </div>
      )}
    </motion.div>
  );
}

// ── Presence Orb ─────────────────────────────────────────────────────────────
// Gives Athena a visual "self" on the home page instead of a static emoji
// in a box. A soft breathing pulse when idle; a slightly brighter, faster
// pulse when there's something for Athena to flag (active === true).

function PresenceOrb({ size = 44, active = false }: { size?: number; active?: boolean }) {
  return (
    <div className="relative shrink-0 grid place-items-center" style={{ width: size, height: size }}>
      <motion.div
        className="absolute inset-0 rounded-full bg-gradient-to-br from-primary to-accent"
        animate={{
          scale: active ? [1, 1.06, 1] : [1, 1.03, 1],
          opacity: active ? [0.9, 1, 0.9] : [0.85, 0.95, 0.85],
        }}
        transition={{ duration: active ? 2.2 : 3.4, repeat: Infinity, ease: "easeInOut" }}
      />
      <div className="absolute inset-[3px] rounded-full bg-background/10 ring-1 ring-white/20" />
    </div>
  );
}

// ── Main Chat Page ─────────────────────────────────────────────────────────────

function ChatHome() {
  const {
    messages,
    pending,
    hydrating,
    hydrated,
    sendStream,
    cancelStream,
    regenerate,
    hydrate,
    streaming,
    statusText,
  } = useChat();

  const [voiceOpen, setVoiceOpen] = useState(false);
  const [hasInsight, setHasInsight] = useState(false);

  // Phase 21 fix: this effect previously called useVoice.getState()
  // .startListening() directly — a ONE-SHOT recording with no
  // continuous-mode callback attached. That meant the wake word worked
  // exactly once: it correctly opened the dialog and captured your
  // first sentence, but since that was a one-shot (not
  // startContinuous()), nothing re-triggered listening after Athena
  // replied — leaving you back at "tap the orb to talk" for every turn
  // after the first. Worse, this one-shot start could RACE against
  // VoiceDialog's own auto-start effect (which correctly calls
  // startContinuous()), since by the time that effect checked
  // `phase === "idle"`, this one might have already flipped it to
  // "listening" — causing the dialog's continuous-mode auto-start to
  // be skipped entirely depending on timing.
  //
  // Fix: just open the dialog. VoiceDialog's own auto-start effect
  // (added in Phase 19) already calls startContinuous() the instant it
  // mounts with open=true — that's the ONE place this should happen,
  // so the hands-free loop is correctly established from the very
  // first turn, not just turns after the first manual tap.
  const wakeEventId = useVoiceActivation((s) => s.wakeEventId);
  const wakeEventIdRef = useRef(wakeEventId);
  useEffect(() => {
    if (wakeEventId === wakeEventIdRef.current) return; // skip initial mount
    wakeEventIdRef.current = wakeEventId;
    unlockAudioPlayback();
    setVoiceOpen(true);
  }, [wakeEventId]);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!hydrated && !hydrating) hydrate();
  }, [hydrated, hydrating, hydrate]);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [messages, streaming]);

  // ── Voice message handler ──────────────────────────────────────────────────
  // Phase 17 fix: the original 30s timeout only accounted for how long
  // text generation (state.streaming) takes. With incremental speech now
  // playing audio chunks as they're synthesized, total time-to-finish for
  // a long response is (LLM generation time) + (remaining audio still
  // queued for playback after the last sentence streams in) — which can
  // comfortably exceed 30s for a long, detailed answer. The promise was
  // rejecting with "Voice response timed out" while Athena was still
  // actively speaking, which both showed a confusing error toast AND
  // (depending on timing) could race with the natural completion path.
  //
  // Fix: this promise now ONLY waits for the TEXT stream to finish
  // (state.streaming === false) — that's the original, correct, and
  // still-relevant 30s ceiling, since text generation genuinely should
  // never take that long. Waiting for SPEECH playback to finish is
  // handled separately and indefinitely in voice-dialog.tsx's
  // handleTranscript (via waitForSpeechToFinish), which has no timeout
  // because audio playback duration is unbounded by design — a long
  // answer should be allowed to finish speaking, however long that takes.
  const handleVoiceMessage = useCallback(
    async (text: string): Promise<{ reply: string }> => {
      return new Promise((resolve, reject) => {
        sendStream(text, null, true);

        const poll = setInterval(() => {
          const state = useChat.getState();
          if (!state.streaming) {
            clearInterval(poll);
            const reply = [...state.messages]
              .reverse()
              .find((m) => m.role === "assistant");
            if (reply?.content) {
              resolve({ reply: reply.content });
            } else {
              reject(new Error("No reply received"));
            }
          }
        }, 200);

        // This timeout covers TEXT generation only, not speech playback.
        // Raised from 30s to 90s: a long, detailed answer (the kind
        // voice mode users actually ask for — "explain X in detail")
        // can legitimately take the LLM 20-40+ seconds to fully stream,
        // especially when an agent does multi-step work (web search,
        // RAG retrieval, multi-agent synthesis) before the first token
        // even arrives. 30s was tripping on genuinely-still-working
        // requests, not stuck ones.
        setTimeout(() => {
          clearInterval(poll);
          reject(new Error("Athena is taking longer than expected to respond. Please try again."));
        }, 90_000);
      });
    },
    [sendStream],
  );

  const isEmpty = messages.length === 0 && !hydrating;

  return (
    <div className="relative flex flex-col h-svh overflow-hidden">
      {/* Message thread */}
      <div
        ref={scrollRef}
        className="relative z-10 flex-1 overflow-y-auto px-4 md:px-6 py-6 pb-40 scroll-smooth"
      >
        <div className="relative max-w-2xl mx-auto">
          <AnimatePresence mode="wait">
            {isEmpty ? (
              <motion.div
                key="empty"
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                className="relative z-10 pt-8"
              >
                {/* Phase 23: unprompted insights, shown above the briefing when present */}
                <ProactiveInsightsFeed onHasInsightChange={setHasInsight} />

                {/* Personal Briefing replaces the generic empty state */}
                <BriefingWidget onSend={sendStream} suppressSpokenLine={hasInsight} />

                {/* Quick chips always visible below */}
                <div className="flex flex-wrap gap-2 justify-center mt-6">
                  <QuickChip
                    icon={Upload}
                    label="Upload doc"
                    onClick={() => (window.location.href = "/documents")}
                  />
                  <QuickChip
                    icon={Mic}
                    label="Voice mode"
                    onClick={() => { unlockAudioPlayback(); setVoiceOpen(true); }}
                  />
                  <QuickChip
                    icon={Newspaper}
                    label="Check news"
                    onClick={() => (window.location.href = "/news")}
                  />
                  <QuickChip
                    icon={StickyNote}
                    label="Open notes"
                    onClick={() => (window.location.href = "/notes")}
                  />
                </div>
              </motion.div>
            ) : (
              <motion.div
                key="thread"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="space-y-8"
              >
                {messages.map((m, i) => {
                  const isLastMsg = i === messages.length - 1;
                  const isLastAssistant = isLastMsg && m.role === "assistant";
                  const isStreamingThis = isLastAssistant && streaming;

                  return (
                    <Message
                      key={m.id}
                      message={m}
                      isLast={isLastAssistant}
                      isStreaming={isStreamingThis}
                      onCancel={isStreamingThis ? cancelStream : undefined}
                      onRegenerate={regenerate}
                    />
                  );
                })}

                {streaming && statusText && messages[messages.length - 1]?.content === "" && (
                  <ThinkingIndicator statusText={statusText} />
                )}

                {pending && !streaming && <ThinkingIndicator />}
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>

      {/* Floating composer */}
      <div className="absolute bottom-0 left-0 right-0 px-4 pb-6 pt-10 bg-gradient-to-t from-background via-background/95 to-transparent pointer-events-none">
        <div className="pointer-events-auto">
          <Composer
            onSend={sendStream}
            pending={pending}
            streaming={streaming}
            onStop={cancelStream}
            onVoiceToggle={() => { unlockAudioPlayback(); setVoiceOpen(true); }}
          />
        </div>
      </div>

      {/* Voice mode dialog */}
      <VoiceDialog
        open={voiceOpen}
        onOpenChange={setVoiceOpen}
        onSendMessage={handleVoiceMessage}
      />
    </div>
  );
}
