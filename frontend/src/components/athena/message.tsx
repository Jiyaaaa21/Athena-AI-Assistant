/**
 * message.tsx — Agent badge now shown permanently on every assistant message.
 * Shows which specialist handled the response (Research, Reminder, RAG, etc.)
 */

import { motion } from "framer-motion";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Copy, RotateCcw, Check, Square, Brain, Bell, StickyNote, FileSearch, Globe, Cpu, Zap } from "lucide-react";
import { useState } from "react";
import { format, isToday } from "date-fns";
import { AthenaLogo } from "./logo";
import { CitationCard } from "./citation-card";
import type { ChatMessage } from "@/lib/mock";
import { cn } from "@/lib/utils";

function formatTimestamp(iso: string | null): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return isToday(date) ? format(date, "h:mm a") : format(date, "MMM d, h:mm a");
}

// ── Agent badge config ────────────────────────────────────────────────────────
const AGENT_META: Record<string, { label: string; icon: React.ElementType; color: string; bg: string }> = {
  research:   { label: "Research",   icon: Brain,      color: "text-violet-600", bg: "bg-violet-500/10" },
  planner:    { label: "Planner",    icon: Zap,        color: "text-amber-600",  bg: "bg-amber-500/10"  },
  note:       { label: "Notes",      icon: StickyNote, color: "text-emerald-600",bg: "bg-emerald-500/10"},
  reminder:   { label: "Reminders",  icon: Bell,       color: "text-rose-600",   bg: "bg-rose-500/10"   },
  rag:        { label: "Documents",  icon: FileSearch,  color: "text-blue-600",   bg: "bg-blue-500/10"   },
  web_search: { label: "Web Search", icon: Globe,      color: "text-cyan-600",   bg: "bg-cyan-500/10"   },
  athena:     { label: "Athena",     icon: Cpu,        color: "text-primary",    bg: "bg-primary/10"    },
};

function AgentBadge({ agentName }: { agentName: string }) {
  const isMulti = agentName.startsWith("multi:");
  const meta = isMulti
    ? { label: "Multi-Agent", icon: Cpu, color: "text-primary", bg: "bg-primary/10" }
    : AGENT_META[agentName];

  if (!meta) return null;
  const Icon = meta.icon;

  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium ${meta.bg} ${meta.color}`}>
      <Icon className="size-2.5" />
      {meta.label}
    </span>
  );
}

// ── Streaming cursor ──────────────────────────────────────────────────────────
export function StreamingCursor() {
  return (
    <motion.span
      className="inline-block w-[2px] h-[1em] bg-primary align-middle ml-0.5 rounded-sm"
      animate={{ opacity: [1, 0, 1] }}
      transition={{ duration: 0.9, repeat: Infinity, ease: "easeInOut" }}
    />
  );
}

// ── Message component ─────────────────────────────────────────────────────────
export function Message({
  message,
  onRegenerate,
  isLast,
  isStreaming,
  onCancel,
}: {
  message: ChatMessage;
  onRegenerate?: () => void;
  isLast?: boolean;
  isStreaming?: boolean;
  onCancel?: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const isUser = message.role === "user";
  const timestamp = formatTimestamp(message.createdAt);

  const copy = async () => {
    await navigator.clipboard.writeText(message.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
      className={cn("flex flex-col gap-3", isUser ? "items-end" : "items-start")}
    >
      {!isUser && (
        <div className="flex items-center gap-2 flex-wrap">
          <AthenaLogo className="size-5" />
          <span className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
            Athena
          </span>

          {/* ── Agent badge — shown when agent is known ── */}
          {message.agentName && message.agentName !== "athena" && !isStreaming && (
            <AgentBadge agentName={message.agentName} />
          )}

          {timestamp && !isStreaming && (
            <span className="text-[10px] text-muted-foreground/70">
              · {timestamp}
            </span>
          )}
        </div>
      )}

      {isUser ? (
        <div className="flex flex-col items-end gap-1 max-w-[85%]">
          {message.imagePreview && (
            <div className="mb-1">
              <img
                src={message.imagePreview}
                alt={message.imageFilename || "Attached image"}
                className="max-w-xs max-h-48 rounded-xl object-cover border border-border shadow-sm"
              />
            </div>
          )}
          {message.content && (
            <div className="bg-secondary border border-border px-4 py-2.5 rounded-2xl text-sm text-foreground">
              {message.content}
            </div>
          )}
          {timestamp && (
            <span className="text-[10px] text-muted-foreground/70 px-1">
              {timestamp}
            </span>
          )}
        </div>
      ) : (
        <div className="max-w-full w-full space-y-3">
          <div className="prose prose-sm prose-zinc max-w-none text-foreground prose-p:leading-relaxed prose-pre:bg-zinc-900 prose-pre:text-zinc-100 prose-pre:rounded-lg prose-code:before:hidden prose-code:after:hidden prose-code:bg-secondary prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded prose-code:text-xs prose-code:font-medium prose-headings:tracking-tight">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {message.content}
            </ReactMarkdown>
            {isStreaming && <StreamingCursor />}
          </div>

          {message.sources && message.sources.length > 0 && (
            <div className="space-y-2 pt-1">
              <div className="text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">
                Sources · {message.sources.length}
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {message.sources.map((s) => (
                  <CitationCard key={s.id} source={s} />
                ))}
              </div>
            </div>
          )}

          <div className="flex items-center gap-1 pt-1">
            {!isStreaming && (
              <button
                onClick={copy}
                className="text-muted-foreground hover:text-foreground text-xs flex items-center gap-1 px-2 py-1 rounded hover:bg-black/5 transition-colors"
                aria-label="Copy"
              >
                {copied ? <Check className="size-3" /> : <Copy className="size-3" />}
                {copied ? "Copied" : "Copy"}
              </button>
            )}

            {isStreaming && onCancel && (
              <button
                onClick={onCancel}
                className="text-muted-foreground hover:text-destructive text-xs flex items-center gap-1 px-2 py-1 rounded hover:bg-black/5 transition-colors"
                aria-label="Stop generating"
              >
                <Square className="size-3" />
                Stop
              </button>
            )}

            {isLast && !isStreaming && onRegenerate && (
              <button
                onClick={onRegenerate}
                className="text-muted-foreground hover:text-foreground text-xs flex items-center gap-1 px-2 py-1 rounded hover:bg-black/5 transition-colors"
                aria-label="Regenerate"
              >
                <RotateCcw className="size-3" />
                Regenerate
              </button>
            )}
          </div>
        </div>
      )}
    </motion.div>
  );
}

// ── Thinking indicator ────────────────────────────────────────────────────────
export function ThinkingIndicator({ statusText }: { statusText?: string }) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="flex items-center gap-2"
    >
      <AthenaLogo className="size-5" />
      <span className="athena-shimmer-text text-sm font-medium">
        {statusText || "Thinking…"}
      </span>
    </motion.div>
  );
}
