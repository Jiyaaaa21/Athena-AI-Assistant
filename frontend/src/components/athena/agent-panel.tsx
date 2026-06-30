/**
 * components/athena/agent-panel.tsx  —  Phase 13
 *
 * Displays the multi-agent ecosystem status:
 *  - Which agent is currently active / was last used
 *  - Real-time step trace during streaming
 *  - Available agent cards with descriptions
 *  - Collapses to a thin badge when idle
 */

import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Brain,
  Search,
  StickyNote,
  Bell,
  FileSearch,
  Globe,
  Cpu,
  ChevronDown,
  ChevronUp,
  Zap,
  CheckCircle2,
  Loader2,
} from "lucide-react";
import { useChat } from "@/stores/chat";
import { API_BASE_URL, isLive } from "@/lib/api";

// ── Agent metadata (mirrors backend) ─────────────────────────────────────────

interface AgentMeta {
  name: string;
  label: string;
  icon: typeof Brain;
  color: string;        // Tailwind text color
  bgColor: string;      // Tailwind bg color
  description: string;
}

const AGENT_META: Record<string, AgentMeta> = {
  research: {
    name: "research",
    label: "Research",
    icon: Brain,
    color: "text-violet-600",
    bgColor: "bg-violet-500/10",
    description: "Deep analysis, topic overviews, multi-source synthesis",
  },
  planner: {
    name: "planner",
    label: "Planner",
    icon: Zap,
    color: "text-amber-600",
    bgColor: "bg-amber-500/10",
    description: "Step-by-step plans, roadmaps, milestone tracking",
  },
  note: {
    name: "note",
    label: "Notes",
    icon: StickyNote,
    color: "text-emerald-600",
    bgColor: "bg-emerald-500/10",
    description: "Capture, search, and summarise your notes",
  },
  reminder: {
    name: "reminder",
    label: "Reminders",
    icon: Bell,
    color: "text-rose-600",
    bgColor: "bg-rose-500/10",
    description: "Natural language reminders and deadline tracking",
  },
  rag: {
    name: "rag",
    label: "Documents",
    icon: FileSearch,
    color: "text-blue-600",
    bgColor: "bg-blue-500/10",
    description: "Semantic search and Q&A over your uploaded files",
  },
  web_search: {
    name: "web_search",
    label: "Web Search",
    icon: Globe,
    color: "text-cyan-600",
    bgColor: "bg-cyan-500/10",
    description: "Live news, current events, and weather data",
  },
  athena: {
    name: "athena",
    label: "Athena",
    icon: Cpu,
    color: "text-primary",
    bgColor: "bg-primary/10",
    description: "Direct conversational AI without specialist tools",
  },
};

function getAgentMeta(rawName: string | null): AgentMeta | null {
  if (!rawName) return null;
  // Handle multi-agent names like "multi:research+planner"
  if (rawName.startsWith("multi:")) {
    return {
      name: rawName,
      label: "Multi-Agent",
      icon: Cpu,
      color: "text-primary",
      bgColor: "bg-primary/10",
      description: "Multiple specialist agents collaborated on this response",
    };
  }
  return AGENT_META[rawName] ?? null;
}

// ── Sub-components ────────────────────────────────────────────────────────────

function AgentBadge({ meta, streaming }: { meta: AgentMeta; streaming: boolean }) {
  const Icon = meta.icon;
  return (
    <div
      className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${meta.bgColor} ${meta.color}`}
    >
      {streaming ? (
        <Loader2 className="size-3 animate-spin" />
      ) : (
        <Icon className="size-3" />
      )}
      {meta.label}
    </div>
  );
}

function StepTrace({ steps, streaming }: { steps: string[]; streaming: boolean }) {
  if (!steps.length && !streaming) return null;
  return (
    <div className="mt-3 space-y-1.5">
      {steps.map((step, i) => (
        <motion.div
          key={i}
          initial={{ opacity: 0, x: -6 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: i * 0.05 }}
          className="flex items-start gap-2 text-xs text-muted-foreground"
        >
          <CheckCircle2 className="size-3 mt-0.5 shrink-0 text-emerald-500" />
          <span>{step}</span>
        </motion.div>
      ))}
      {streaming && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="size-3 animate-spin text-primary" />
          <span className="animate-pulse">Running…</span>
        </div>
      )}
    </div>
  );
}

function AgentCard({ meta }: { meta: AgentMeta }) {
  const Icon = meta.icon;
  return (
    <div className={`flex gap-3 p-3 rounded-xl border border-border/60 ${meta.bgColor}`}>
      <div className={`mt-0.5 ${meta.color}`}>
        <Icon className="size-4" />
      </div>
      <div>
        <div className={`text-xs font-semibold ${meta.color}`}>{meta.label}</div>
        <div className="text-[11px] text-muted-foreground mt-0.5 leading-snug">
          {meta.description}
        </div>
      </div>
    </div>
  );
}

// ── Main Panel ────────────────────────────────────────────────────────────────

export function AgentPanel() {
  const { activeAgentName, agentSteps, streaming, statusText } = useChat();
  const [expanded, setExpanded] = useState(false);
  const [liveAgents, setLiveAgents] = useState<{ name: string; description: string }[]>([]);

  // Fetch agent list from backend once
  useEffect(() => {
    if (!isLive) return;
    fetch(`${API_BASE_URL}/agents`)
      .then((r) => r.json())
      .then((d) => setLiveAgents(d.agents ?? []))
      .catch(() => {});
  }, []);

  const activeMeta = getAgentMeta(streaming ? activeAgentName : activeAgentName);

  // Visible agents: backend list if available, otherwise use our local map
  const agentList =
    liveAgents.length > 0
      ? liveAgents.map((a) => AGENT_META[a.name]).filter(Boolean)
      : Object.values(AGENT_META).filter((m) => m.name !== "athena");

  const hasActivity = streaming || activeAgentName;

  return (
    <div className="rounded-2xl border border-border/60 bg-card/60 backdrop-blur-sm overflow-hidden">
      {/* Header */}
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-muted/30 transition-colors"
      >
        <div className="flex items-center gap-2">
          <Cpu className="size-4 text-primary" />
          <span className="text-sm font-medium">Agent Ecosystem</span>

          {/* Live status badge */}
          <AnimatePresence mode="wait">
            {hasActivity && activeMeta && (
              <motion.div
                key={activeAgentName}
                initial={{ opacity: 0, scale: 0.8 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.8 }}
              >
                <AgentBadge meta={activeMeta} streaming={streaming} />
              </motion.div>
            )}
            {streaming && !activeMeta && (
              <motion.div
                key="routing"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-primary/10 text-primary"
              >
                <Loader2 className="size-3 animate-spin" />
                Routing…
              </motion.div>
            )}
          </AnimatePresence>
        </div>
        <div className="text-muted-foreground">
          {expanded ? <ChevronUp className="size-4" /> : <ChevronDown className="size-4" />}
        </div>
      </button>

      {/* Status text while streaming */}
      <AnimatePresence>
        {streaming && statusText && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
          >
            <div className="px-4 pb-2 flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="size-3 animate-spin text-primary shrink-0" />
              {statusText}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Step trace — shows when there are steps from last agent run */}
      <AnimatePresence>
        {agentSteps.length > 0 && !expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
          >
            <div className="px-4 pb-3">
              <StepTrace steps={agentSteps} streaming={streaming} />
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Expanded: agent directory + steps */}
      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
          >
            <div className="px-4 pb-4 space-y-4">
              {/* Step trace in expanded mode */}
              {agentSteps.length > 0 && (
                <div>
                  <div className="text-[10px] uppercase tracking-widest text-muted-foreground font-semibold mb-2">
                    Last run trace
                  </div>
                  <StepTrace steps={agentSteps} streaming={streaming} />
                </div>
              )}

              {/* Agent directory */}
              <div>
                <div className="text-[10px] uppercase tracking-widest text-muted-foreground font-semibold mb-2">
                  Available agents ({agentList.length})
                </div>
                <div className="grid grid-cols-1 gap-2">
                  {agentList.map((meta) => (
                    <AgentCard key={meta.name} meta={meta as AgentMeta} />
                  ))}
                </div>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
