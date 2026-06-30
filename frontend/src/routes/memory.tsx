import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, useMemo } from "react";
import {
  Brain, User, MessageSquare, Search, RefreshCw, AlertCircle, Trash2,
  BarChart3, Clock, Filter, ChevronDown, ChevronUp, Pencil, Check, X,
  TrendingUp, Folder, Lightbulb, Zap, CalendarDays, List as ListIcon,
  PieChart, Sparkles,
} from "lucide-react";
import { PageHeader } from "@/components/athena/page-header";
import { ExportMenu } from "@/components/athena/export-menu";
import { EmptyState } from "@/components/athena/empty-state";
import { memoryApi, type EnrichedMemory, type MemoryStats, type MemoryPreferences } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/memory")({
  head: () => ({
    meta: [
      { title: "Athena — Memory OS" },
      { name: "description", content: "Long-term memory and personal intelligence layer for Athena." },
    ],
  }),
  component: MemoryPage,
});

// ─── Constants ────────────────────────────────────────────────────────────────

const CATEGORIES = ["All", "Personal", "Preferences", "Projects", "Work", "Learning", "Conversations", "Documents", "Reminders", "Notes"];
const IMPORTANCE_OPTIONS = ["All", "critical", "high", "medium", "low"];

const IMPORTANCE_STYLES: Record<string, string> = {
  critical: "bg-purple-100 text-purple-700 border-purple-200 dark:bg-purple-900/30 dark:text-purple-300 dark:border-purple-700",
  high:     "bg-red-100 text-red-700 border-red-200 dark:bg-red-900/30 dark:text-red-300 dark:border-red-700",
  medium:   "bg-amber-100 text-amber-700 border-amber-200 dark:bg-amber-900/30 dark:text-amber-300 dark:border-amber-700",
  low:      "bg-slate-100 text-slate-600 border-slate-200 dark:bg-slate-800 dark:text-slate-400 dark:border-slate-700",
};

const ICON_MAP: Record<string, typeof Brain> = {
  brain: Brain,
  "trending-up": TrendingUp,
  clock: Clock,
  folder: Folder,
};

// ─── Sub-components ───────────────────────────────────────────────────────────

function StatCard({ label, value, sub, accent }: { label: string; value: string | number; sub?: string; accent?: boolean }) {
  return (
    <div className={cn(
      "flex flex-col gap-0.5 rounded-xl border px-4 py-3",
      accent ? "border-primary/30 bg-primary/5" : "border-border bg-card",
    )}>
      <span className="text-xs text-muted-foreground uppercase tracking-widest">{label}</span>
      <span className="text-xl font-semibold">{value}</span>
      {sub && <span className="text-[11px] text-muted-foreground">{sub}</span>}
    </div>
  );
}

function ImportanceBadge({ level }: { level: string }) {
  return (
    <span className={cn(
      "inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium border",
      IMPORTANCE_STYLES[level] ?? IMPORTANCE_STYLES.low,
    )}>
      {level === "critical" && <Zap className="size-2.5 mr-0.5" />}
      {level}
    </span>
  );
}

function CategoryBadge({ category }: { category: string }) {
  return (
    <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] bg-secondary text-secondary-foreground">
      {category}
    </span>
  );
}

// Inline editing component
function EditableContent({
  id, content, onSave, onCancel,
}: { id: string; content: string; onSave: (id: string, val: string) => void; onCancel: () => void }) {
  const [val, setVal] = useState(content);
  return (
    <div className="flex-1 min-w-0 space-y-2">
      <Textarea
        value={val}
        onChange={(e) => setVal(e.target.value)}
        rows={3}
        className="text-sm resize-none"
        autoFocus
      />
      <div className="flex gap-2">
        <Button size="sm" onClick={() => onSave(id, val)} disabled={!val.trim()}>
          <Check className="size-3 mr-1" /> Save
        </Button>
        <Button size="sm" variant="outline" onClick={onCancel}>
          <X className="size-3 mr-1" /> Cancel
        </Button>
      </div>
    </div>
  );
}

function MemoryItem({
  m, isDeleting, onDelete, onEdit,
}: {
  m: EnrichedMemory;
  isDeleting: boolean;
  onDelete: () => void;
  onEdit: (id: string) => void;
}) {
  const Icon = m.role === "user" ? User : m.role === "assistant" ? MessageSquare : Brain;
  const date = m.createdAt
    ? new Date(m.createdAt).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })
    : null;

  return (
    <li className={cn(
      "flex items-start gap-3 rounded-xl border bg-card px-4 py-3 ring-1 ring-black/5 hover:shadow-sm transition group",
      m.importance === "critical" && "border-purple-200 dark:border-purple-800/50",
    )}>
      <div className="size-8 rounded-lg bg-secondary grid place-items-center shrink-0 mt-0.5">
        <Icon className="size-4 text-muted-foreground" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-sm leading-snug">{m.label}</div>
        <div className="flex items-center flex-wrap gap-1.5 mt-1.5">
          <CategoryBadge category={m.category} />
          <ImportanceBadge level={m.importance} />
          {date && (
            <span className="text-[10px] text-muted-foreground flex items-center gap-0.5">
              <Clock className="size-2.5" /> {date}
            </span>
          )}
        </div>
      </div>
      <div className="flex items-center gap-1 shrink-0 mt-0.5">
        <button
          onClick={() => onEdit(m.id)}
          className="opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-foreground p-1 rounded transition-all"
          title="Edit"
        >
          <Pencil className="size-3.5" />
        </button>
        <AlertDialog>
          <AlertDialogTrigger asChild>
            <button
              disabled={isDeleting}
              className="opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive disabled:opacity-50 p-1 rounded transition-all"
              title="Forget this"
            >
              <Trash2 className="size-3.5" />
            </button>
          </AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Forget this memory?</AlertDialogTitle>
              <AlertDialogDescription>
                Athena will permanently forget this entry. This cannot be undone.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>Cancel</AlertDialogCancel>
              <AlertDialogAction
                onClick={onDelete}
                className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              >
                Forget
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </div>
    </li>
  );
}

function EditableMemoryItem({
  m, isDeleting, onDelete, editingId, onStartEdit, onSaveEdit, onCancelEdit, isSaving,
}: {
  m: EnrichedMemory;
  isDeleting: boolean;
  onDelete: () => void;
  editingId: string | null;
  onStartEdit: (id: string) => void;
  onSaveEdit: (id: string, content: string) => void;
  onCancelEdit: () => void;
  isSaving: boolean;
}) {
  const Icon = m.role === "user" ? User : m.role === "assistant" ? MessageSquare : Brain;
  const date = m.createdAt
    ? new Date(m.createdAt).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })
    : null;
  const isEditing = editingId === m.id;

  return (
    <li className={cn(
      "flex items-start gap-3 rounded-xl border bg-card px-4 py-3 ring-1 ring-black/5 hover:shadow-sm transition group",
      m.importance === "critical" && "border-purple-200 dark:border-purple-800/50",
      isEditing && "ring-2 ring-primary/30",
    )}>
      <div className="size-8 rounded-lg bg-secondary grid place-items-center shrink-0 mt-0.5">
        <Icon className="size-4 text-muted-foreground" />
      </div>

      {isEditing ? (
        <EditableContent
          id={m.id}
          content={m.label}
          onSave={onSaveEdit}
          onCancel={onCancelEdit}
        />
      ) : (
        <>
          <div className="flex-1 min-w-0">
            <div className="text-sm leading-snug">{m.label}</div>
            <div className="flex items-center flex-wrap gap-1.5 mt-1.5">
              <CategoryBadge category={m.category} />
              <ImportanceBadge level={m.importance} />
              {date && (
                <span className="text-[10px] text-muted-foreground flex items-center gap-0.5">
                  <Clock className="size-2.5" /> {date}
                </span>
              )}
            </div>
          </div>
          <div className="flex items-center gap-1 shrink-0 mt-0.5">
            <button
              onClick={() => onStartEdit(m.id)}
              className="opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-foreground p-1 rounded transition-all"
              title="Edit"
            >
              <Pencil className="size-3.5" />
            </button>
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <button
                  disabled={isDeleting}
                  className="opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive disabled:opacity-50 p-1 rounded transition-all"
                  title="Forget"
                >
                  <Trash2 className="size-3.5" />
                </button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Forget this memory?</AlertDialogTitle>
                  <AlertDialogDescription>Permanent. Cannot be undone.</AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Cancel</AlertDialogCancel>
                  <AlertDialogAction onClick={onDelete} className="bg-destructive text-destructive-foreground hover:bg-destructive/90">
                    Forget
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          </div>
        </>
      )}
    </li>
  );
}

// ─── Distribution bar chart (pure CSS) ──────────────────────────────────────

function DistributionBar({ label, count, total, color }: { label: string; count: number; total: number; color: string }) {
  const pct = total > 0 ? Math.round(count / total * 100) : 0;
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <span className="text-muted-foreground capitalize">{label}</span>
        <span className="font-medium">{count} <span className="text-muted-foreground">({pct}%)</span></span>
      </div>
      <div className="h-1.5 rounded-full bg-muted overflow-hidden">
        <div className={cn("h-full rounded-full transition-all", color)} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

// Active hours sparkline (pure CSS)
function HourBar({ hour, count, max }: { hour: number; count: number; max: number }) {
  const h = max > 0 ? Math.max(4, Math.round(count / max * 40)) : 4;
  const label = hour === 0 ? "12a" : hour < 12 ? `${hour}a` : hour === 12 ? "12p" : `${hour - 12}p`;
  const isActive = count > 0;
  return (
    <div className="flex flex-col items-center gap-0.5" title={`${label}: ${count} messages`}>
      <div className="flex items-end" style={{ height: 44 }}>
        <div
          className={cn("w-2 rounded-sm transition-all", isActive ? "bg-primary/70" : "bg-muted")}
          style={{ height: h }}
        />
      </div>
      {[0, 6, 12, 18, 23].includes(hour) && (
        <span className="text-[9px] text-muted-foreground">{label}</span>
      )}
    </div>
  );
}

// ─── Personalization panel ─────────────────────────────────────────────────

function PersonalizationPanel() {
  const { data, isLoading } = useQuery({
    queryKey: ["memory-preferences"],
    queryFn: memoryApi.preferences,
  });
  const { data: topics, isLoading: topicsLoading } = useQuery({
    queryKey: ["memory-topics"],
    queryFn: memoryApi.topics,
  });

  const prefs = data as MemoryPreferences | undefined;
  const maxHour = prefs ? Math.max(...prefs.active_hours.map((h) => h.count)) : 0;

  if (isLoading) {
    return (
      <div className="space-y-4">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="h-24 rounded-xl bg-muted animate-pulse" />
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Personalized Suggestions */}
      {prefs && prefs.suggestions.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
            <Sparkles className="size-4 text-primary" /> Personalized Suggestions
          </h3>
          <div className="grid sm:grid-cols-2 gap-3">
            {prefs.suggestions.map((s, i) => {
              const Icon = ICON_MAP[s.icon] ?? Brain;
              return (
                <div key={i} className="rounded-xl border border-border bg-card p-4 flex gap-3">
                  <div className="size-8 rounded-lg bg-primary/10 grid place-items-center shrink-0">
                    <Icon className="size-4 text-primary" />
                  </div>
                  <div className="min-w-0">
                    <div className="text-sm font-medium leading-tight">{s.title}</div>
                    <div className="text-xs text-muted-foreground mt-0.5 line-clamp-2">{s.detail}</div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Frequently Discussed Topics */}
      {topics && topics.topics.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
            <TrendingUp className="size-4 text-primary" />
            Frequently Discussed Topics
            <span className="text-xs font-normal text-muted-foreground ml-1">
              from {topics.total_analyzed} messages
            </span>
          </h3>
          <div className="flex flex-wrap gap-2">
            {topics.topics.map((t) => (
              <div
                key={t.topic}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-full border border-border bg-card text-sm hover:border-primary/40 transition-colors"
              >
                <span>{t.topic}</span>
                <Badge variant="secondary" className="text-[10px] px-1.5 py-0 ml-0.5">
                  {t.count}
                </Badge>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Interaction Patterns */}
      {prefs && (
        <div className="grid sm:grid-cols-2 gap-6">
          {/* Active hours */}
          <div>
            <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
              <Clock className="size-4 text-primary" /> Active Hours
              {prefs.peak_hour !== null && (
                <span className="text-xs font-normal text-muted-foreground">
                  Peak: {prefs.peak_hour < 12 ? `${prefs.peak_hour}AM` : prefs.peak_hour === 12 ? "12PM" : `${prefs.peak_hour - 12}PM`}
                </span>
              )}
            </h3>
            <div className="rounded-xl border border-border bg-card p-4">
              <div className="flex items-end gap-0.5 overflow-hidden">
                {prefs.active_hours.map((h) => (
                  <HourBar key={h.hour} hour={h.hour} count={h.count} max={maxHour} />
                ))}
              </div>
            </div>
          </div>

          {/* Most active days + top categories */}
          <div className="space-y-4">
            {prefs.most_active_days.length > 0 && (
              <div>
                <h3 className="text-sm font-semibold mb-2 flex items-center gap-2">
                  <CalendarDays className="size-4 text-primary" /> Most Active Days
                </h3>
                <div className="rounded-xl border border-border bg-card p-4 space-y-2.5">
                  {prefs.most_active_days.map((d) => (
                    <DistributionBar
                      key={d.day}
                      label={d.day}
                      count={d.count}
                      total={prefs.most_active_days.reduce((s, x) => s + x.count, 0)}
                      color="bg-blue-500"
                    />
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Preferred topics / categories */}
      {prefs && prefs.top_categories.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
            <Folder className="size-4 text-primary" /> Preferred Categories
          </h3>
          <div className="rounded-xl border border-border bg-card p-4 space-y-3">
            {prefs.top_categories.map((c) => (
              <DistributionBar
                key={c.category}
                label={c.category}
                count={c.count}
                total={prefs.total_user_messages}
                color="bg-primary/60"
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Analytics panel ─────────────────────────────────────────────────────────

function AnalyticsPanel({ stats }: { stats: MemoryStats | undefined }) {
  if (!stats || stats.total === 0) {
    return (
      <EmptyState
        icon={PieChart}
        title="No analytics yet"
        description="Chat with Athena to build up memory analytics."
      />
    );
  }

  const imp = stats.by_importance;
  const impTotal = (imp.critical ?? 0) + imp.high + imp.medium + imp.low;
  const catEntries = Object.entries(stats.by_category).sort((a, b) => b[1] - a[1]);

  const impColors: Record<string, string> = {
    critical: "bg-purple-500",
    high: "bg-red-500",
    medium: "bg-amber-500",
    low: "bg-slate-400",
  };

  return (
    <div className="space-y-6">
      {/* Overview KPIs */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatCard label="Total Memories" value={stats.total} accent />
        <StatCard label="Critical" value={imp.critical ?? 0}
          sub={`${imp.high} high, ${imp.medium} med`} />
        <StatCard label="Top Category" value={stats.most_active_category ?? "—"}
          sub={stats.most_active_category ? `${stats.by_category[stats.most_active_category]} entries` : undefined} />
        <StatCard label="Your Messages" value={stats.by_role.user}
          sub={`${stats.by_role.assistant} from Athena`} />
      </div>

      <div className="grid sm:grid-cols-2 gap-6">
        {/* Importance distribution */}
        <div>
          <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
            <BarChart3 className="size-4 text-primary" /> By Importance
          </h3>
          <div className="rounded-xl border border-border bg-card p-4 space-y-3">
            {(["critical", "high", "medium", "low"] as const).map((level) => (
              <DistributionBar
                key={level}
                label={level}
                count={imp[level] ?? 0}
                total={impTotal}
                color={impColors[level]}
              />
            ))}
          </div>
        </div>

        {/* Category distribution */}
        <div>
          <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
            <Folder className="size-4 text-primary" /> By Category
          </h3>
          <div className="rounded-xl border border-border bg-card p-4 space-y-3">
            {catEntries.slice(0, 6).map(([cat, cnt]) => (
              <DistributionBar
                key={cat}
                label={cat}
                count={cnt}
                total={stats.total}
                color="bg-blue-500/70"
              />
            ))}
          </div>
        </div>
      </div>

      {/* Date range info */}
      {(stats.oldest || stats.newest) && (
        <div className="rounded-xl border border-border bg-card p-4 flex flex-wrap gap-6">
          {stats.oldest && (
            <div>
              <div className="text-xs text-muted-foreground uppercase tracking-wider mb-0.5">Oldest memory</div>
              <div className="text-sm font-medium">
                {new Date(stats.oldest).toLocaleDateString(undefined, { month: "long", day: "numeric", year: "numeric" })}
              </div>
            </div>
          )}
          {stats.newest && (
            <div>
              <div className="text-xs text-muted-foreground uppercase tracking-wider mb-0.5">Most recent</div>
              <div className="text-sm font-medium">
                {new Date(stats.newest).toLocaleDateString(undefined, { month: "long", day: "numeric", year: "numeric" })}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

// ── Phase 16: Athena Knows Panel ─────────────────────────────────────────────

const FACT_CATEGORY_META: Record<string, { label: string; color: string }> = {
  goal:       { label: "Goal",       color: "bg-blue-50 text-blue-700 border-blue-200" },
  preference: { label: "Preference", color: "bg-purple-50 text-purple-700 border-purple-200" },
  context:    { label: "Context",    color: "bg-amber-50 text-amber-700 border-amber-200" },
  skill:      { label: "Skill",      color: "bg-emerald-50 text-emerald-700 border-emerald-200" },
};

interface UserFact { id: number; fact: string; category: string; confidence: number; createdAt: string | null; }

function AthenaKnowsPanel() {
  const qc = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: ["user-facts"],
    queryFn: async () => {
      const res = await fetch(`${import.meta.env.VITE_API_URL || ""}/memory/facts`, {
        headers: localStorage.getItem("athena_access_token")
          ? { Authorization: `Bearer ${localStorage.getItem("athena_access_token")}` }
          : {},
      });
      if (!res.ok) return { facts: [] };
      return res.json() as Promise<{ facts: UserFact[] }>;
    },
  });

  const deleteFact = useMutation({
    mutationFn: async (id: number) => {
      const tok = localStorage.getItem("athena_access_token");
      await fetch(`${import.meta.env.VITE_API_URL || ""}/memory/facts/${id}`, {
        method: "DELETE",
        headers: tok ? { Authorization: `Bearer ${tok}` } : {},
      });
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["user-facts"] }); toast.success("Fact forgotten"); },
  });

  const clearAll = useMutation({
    mutationFn: async () => {
      const tok = localStorage.getItem("athena_access_token");
      await fetch(`${import.meta.env.VITE_API_URL || ""}/memory/facts`, {
        method: "DELETE",
        headers: tok ? { Authorization: `Bearer ${tok}` } : {},
      });
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["user-facts"] }); toast.success("All Athena memories cleared"); },
  });

  const facts = data?.facts ?? [];
  const byCategory = facts.reduce((acc: Record<string, UserFact[]>, f) => {
    acc[f.category] = acc[f.category] ?? [];
    acc[f.category].push(f);
    return acc;
  }, {});

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h3 className="text-sm font-semibold mb-1">What Athena Knows About You</h3>
          <p className="text-xs text-muted-foreground max-w-md">
            Athena builds a long-term profile from your conversations — goals, preferences,
            context, and skills. This makes every response more personal and relevant.
            Delete anything you want Athena to forget.
          </p>
        </div>
        {facts.length > 0 && (
          <Button variant="outline" size="sm" onClick={() => clearAll.mutate()} disabled={clearAll.isPending}>
            <Trash2 className="size-3.5 mr-1.5" /> Clear All
          </Button>
        )}
      </div>

      {isLoading ? (
        <div className="space-y-2">
          {[0,1,2].map(i => <div key={i} className="h-14 bg-muted rounded-xl animate-pulse" />)}
        </div>
      ) : facts.length === 0 ? (
        <div className="text-center py-16 border border-dashed border-border rounded-xl">
          <Brain className="size-10 mx-auto text-muted-foreground/30 mb-3" />
          <p className="text-sm text-muted-foreground mb-1 font-medium">No memories yet</p>
          <p className="text-xs text-muted-foreground max-w-xs mx-auto">
            Start chatting with Athena. After each conversation, Athena will
            extract and remember key facts about you here.
          </p>
        </div>
      ) : (
        <div className="space-y-6">
          {Object.entries(FACT_CATEGORY_META).map(([cat, meta]) => {
            const catFacts = byCategory[cat];
            if (!catFacts?.length) return null;
            return (
              <div key={cat}>
                <p className={`inline-flex text-[10px] font-semibold px-2 py-0.5 rounded-full border mb-2 ${meta.color}`}>
                  {meta.label}s · {catFacts.length}
                </p>
                <div className="space-y-2">
                  {catFacts.map(f => (
                    <div key={f.id}
                      className="group flex items-start gap-3 p-3 rounded-xl border border-border bg-card hover:border-primary/20 transition-colors"
                    >
                      <div className="flex-1 min-w-0">
                        <p className="text-sm leading-relaxed">{f.fact}</p>
                        <p className="text-[10px] text-muted-foreground mt-0.5">
                          {f.confidence}% confidence
                          {f.createdAt ? ` · ${new Date(f.createdAt).toLocaleDateString()}` : ""}
                        </p>
                      </div>
                      <button
                        onClick={() => deleteFact.mutate(f.id)}
                        className="opacity-0 group-hover:opacity-100 p-1.5 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition-all shrink-0"
                        title="Forget this"
                      >
                        <Trash2 className="size-3.5" />
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function MemoryPage() {
  const qc = useQueryClient();

  const { data, isLoading, isError, isFetching, refetch } = useQuery({
    queryKey: ["memory"],
    queryFn: memoryApi.list,
  });
  const statsQuery = useQuery({
    queryKey: ["memory-stats"],
    queryFn: memoryApi.stats,
  });
  const timelineQuery = useQuery({
    queryKey: ["memory-timeline"],
    queryFn: memoryApi.timeline,
  });

  const [q, setQ] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("All");
  const [importanceFilter, setImportanceFilter] = useState("All");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [sortBy, setSortBy] = useState<"date" | "importance">("date");
  const [sortDir, setSortDir] = useState<"desc" | "asc">("desc");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState("list");

  const remove = useMutation({
    mutationFn: memoryApi.remove,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["memory"] });
      qc.invalidateQueries({ queryKey: ["memory-stats"] });
      qc.invalidateQueries({ queryKey: ["memory-timeline"] });
      toast.success("Forgotten");
    },
    onError: (e: Error) => toast.error(e.message || "Couldn't forget that"),
  });

  const edit = useMutation({
    mutationFn: ({ id, content }: { id: string; content: string }) =>
      memoryApi.update(id, content),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["memory"] });
      qc.invalidateQueries({ queryKey: ["memory-stats"] });
      qc.invalidateQueries({ queryKey: ["memory-timeline"] });
      setEditingId(null);
      toast.success("Memory updated");
    },
    onError: (e: Error) => toast.error(e.message || "Couldn't update memory"),
  });

  const filtered = useMemo(() => {
    let list: EnrichedMemory[] = (data ?? []) as EnrichedMemory[];

    if (q) {
      const lo = q.toLowerCase();
      list = list.filter((m) =>
        m.label?.toLowerCase().includes(lo) || m.category?.toLowerCase().includes(lo)
      );
    }
    if (categoryFilter !== "All") list = list.filter((m) => m.category === categoryFilter);
    if (importanceFilter !== "All") list = list.filter((m) => m.importance === importanceFilter);
    if (dateFrom) list = list.filter((m) => m.createdAt && m.createdAt >= dateFrom);
    if (dateTo) list = list.filter((m) => m.createdAt && m.createdAt <= dateTo + "T23:59:59Z");

    const impOrder: Record<string, number> = { critical: 4, high: 3, medium: 2, low: 1 };
    list = [...list].sort((a, b) => {
      if (sortBy === "importance") {
        const diff = (impOrder[b.importance] ?? 0) - (impOrder[a.importance] ?? 0);
        return sortDir === "desc" ? diff : -diff;
      }
      const da = a.createdAt ?? "";
      const db_ = b.createdAt ?? "";
      return sortDir === "desc" ? db_.localeCompare(da) : da.localeCompare(db_);
    });

    return list;
  }, [data, q, categoryFilter, importanceFilter, dateFrom, dateTo, sortBy, sortDir]);

  const stats = statsQuery.data as MemoryStats | undefined;

  const toggleSort = (field: "date" | "importance") => {
    if (sortBy === field) setSortDir((d) => (d === "desc" ? "asc" : "desc"));
    else { setSortBy(field); setSortDir("desc"); }
  };

  const hasFilters = q || categoryFilter !== "All" || importanceFilter !== "All" || dateFrom || dateTo;

  const clearFilters = () => {
    setQ(""); setCategoryFilter("All"); setImportanceFilter("All"); setDateFrom(""); setDateTo("");
  };

  const refreshAll = () => {
    refetch();
    statsQuery.refetch();
    timelineQuery.refetch();
    qc.invalidateQueries({ queryKey: ["memory-preferences"] });
    qc.invalidateQueries({ queryKey: ["memory-topics"] });
  };

  return (
    <div className="max-w-4xl mx-auto w-full px-4 sm:px-6 py-10">
      <PageHeader
        title="Memory OS"
        description="Athena's personal intelligence layer — what it knows about you."
        actions={
          <div className="flex items-center gap-2">
            {/* Phase 8: Export memories */}
            <ExportMenu type="memories" label="Export" />
            <Button
              variant="outline"
              size="sm"
              onClick={refreshAll}
              disabled={isFetching}
            >
              <RefreshCw className={cn("size-4", isFetching && "animate-spin")} />
              Refresh
            </Button>
          </div>
        }
      />

      {/* Personalization banner */}
      <div className="rounded-2xl border border-border bg-gradient-to-br from-primary/5 to-accent/5 p-5 ring-1 ring-black/5 mb-6">
        <div className="flex items-start gap-4">
          <div className="size-11 rounded-2xl bg-white dark:bg-background ring-1 ring-border grid place-items-center shrink-0">
            <Brain className="size-5 text-primary" />
          </div>
          <div className="flex-1 min-w-0">
            <h2 className="text-base font-semibold tracking-tight">Personalization is on</h2>
            <p className="text-sm text-muted-foreground mt-0.5">
              Athena learns from every conversation. You can view, edit, or forget any entry at any time.
            </p>
          </div>
          {stats && stats.total > 0 && (
            <div className="text-right shrink-0 hidden sm:block">
              <div className="text-2xl font-bold">{stats.total}</div>
              <div className="text-xs text-muted-foreground">memories</div>
            </div>
          )}
        </div>
      </div>

      {/* Main tabs */}
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList className="mb-6">
          <TabsTrigger value="list" className="flex items-center gap-1.5">
            <ListIcon className="size-3.5" /> Memory List
          </TabsTrigger>
          <TabsTrigger value="timeline" className="flex items-center gap-1.5">
            <Clock className="size-3.5" /> Timeline
          </TabsTrigger>
          <TabsTrigger value="analytics" className="flex items-center gap-1.5">
            <PieChart className="size-3.5" /> Analytics
          </TabsTrigger>
          <TabsTrigger value="personalization" className="flex items-center gap-1.5">
            <Sparkles className="size-3.5" /> Insights
          </TabsTrigger>
          <TabsTrigger value="athena_knows" className="flex items-center gap-1.5">
            <Brain className="size-3.5" /> Athena Knows
          </TabsTrigger>
        </TabsList>

        {/* ── LIST TAB ─────────────────────────────────────────────────── */}
        <TabsContent value="list">
          {/* Search + filters */}
          <div className="space-y-3 mb-4">
            <div className="flex flex-col sm:flex-row gap-3">
              <div className="relative flex-1">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
                <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search memory…" className="pl-9" />
              </div>
              <Select value={categoryFilter} onValueChange={setCategoryFilter}>
                <SelectTrigger className="w-full sm:w-44">
                  <Filter className="size-3.5 mr-1.5 text-muted-foreground" />
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {CATEGORIES.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}
                </SelectContent>
              </Select>
              <Select value={importanceFilter} onValueChange={setImportanceFilter}>
                <SelectTrigger className="w-full sm:w-36">
                  <SelectValue placeholder="Importance" />
                </SelectTrigger>
                <SelectContent>
                  {IMPORTANCE_OPTIONS.map((o) => (
                    <SelectItem key={o} value={o}>{o === "All" ? "All importance" : o}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Date range filter */}
            <div className="flex flex-wrap items-center gap-3">
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <CalendarDays className="size-3.5" /> Date range:
              </div>
              <Input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} className="w-36 h-8 text-xs" />
              <span className="text-xs text-muted-foreground">to</span>
              <Input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} className="w-36 h-8 text-xs" />
              {hasFilters && (
                <Button variant="ghost" size="sm" className="h-8 text-xs" onClick={clearFilters}>
                  Clear filters
                </Button>
              )}
            </div>
          </div>

          {/* Sort controls */}
          {filtered.length > 0 && (
            <div className="flex items-center gap-2 mb-4 text-xs text-muted-foreground">
              <span>Sort by</span>
              {(["date", "importance"] as const).map((f) => (
                <button
                  key={f}
                  onClick={() => toggleSort(f)}
                  className={cn(
                    "flex items-center gap-0.5 px-2 py-0.5 rounded border transition",
                    sortBy === f
                      ? "border-primary/40 text-primary bg-primary/5"
                      : "border-border hover:border-primary/30",
                  )}
                >
                  {f}
                  {sortBy === f && (sortDir === "desc" ? <ChevronDown className="size-3" /> : <ChevronUp className="size-3" />)}
                </button>
              ))}
              <span className="ml-auto">{filtered.length} {filtered.length === 1 ? "entry" : "entries"}</span>
            </div>
          )}

          {isLoading ? (
            <ul className="space-y-2">
              {Array.from({ length: 5 }).map((_, i) => (
                <li key={i} className="h-16 rounded-xl bg-muted animate-pulse" />
              ))}
            </ul>
          ) : isError ? (
            <EmptyState
              icon={AlertCircle}
              title="Couldn't load memory"
              description="Something went wrong fetching what Athena remembers."
              action={<Button onClick={() => refetch()}>Try again</Button>}
            />
          ) : filtered.length === 0 ? (
            <EmptyState
              icon={Brain}
              title={hasFilters ? "No matches" : "Nothing remembered yet"}
              description={hasFilters ? "Try adjusting your search or filters." : "Chat with Athena and it'll start remembering things here."}
            />
          ) : (
            <ul className="space-y-2">
              {filtered.map((m) => (
                <EditableMemoryItem
                  key={m.id}
                  m={m}
                  isDeleting={remove.isPending && String(remove.variables) === String(m.id)}
                  onDelete={() => remove.mutate(m.id)}
                  editingId={editingId}
                  onStartEdit={(id) => setEditingId(id)}
                  onSaveEdit={(id, content) => edit.mutate({ id, content })}
                  onCancelEdit={() => setEditingId(null)}
                  isSaving={edit.isPending}
                />
              ))}
            </ul>
          )}
        </TabsContent>

        {/* ── TIMELINE TAB ─────────────────────────────────────────────── */}
        <TabsContent value="timeline">
          {timelineQuery.isLoading ? (
            <div className="space-y-6">
              {Array.from({ length: 3 }).map((_, i) => (
                <div key={i} className="space-y-2">
                  <div className="h-5 w-24 bg-muted rounded animate-pulse" />
                  <div className="h-16 rounded-xl bg-muted animate-pulse" />
                  <div className="h-16 rounded-xl bg-muted animate-pulse" />
                </div>
              ))}
            </div>
          ) : !timelineQuery.data?.timeline?.length ? (
            <EmptyState icon={Clock} title="No timeline data" description="Chat with Athena to build up your memory timeline." />
          ) : (
            <div className="space-y-8">
              {timelineQuery.data.timeline.map((period) => (
                <div key={period.period}>
                  <div className="flex items-center gap-3 mb-3">
                    <div className="text-xs font-semibold text-muted-foreground uppercase tracking-widest">
                      {period.period}
                    </div>
                    <div className="flex-1 h-px bg-border" />
                    <Badge variant="secondary" className="text-[10px]">{period.count}</Badge>
                  </div>
                  <ul className="space-y-2">
                    {period.entries.map((m) => (
                      <MemoryItem
                        key={m.id}
                        m={m}
                        isDeleting={remove.isPending && String(remove.variables) === String(m.id)}
                        onDelete={() => {
                          remove.mutate(m.id);
                          timelineQuery.refetch();
                        }}
                        onEdit={(id) => {
                          setEditingId(id);
                          setActiveTab("list");
                        }}
                      />
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          )}
        </TabsContent>

        {/* ── ANALYTICS TAB ────────────────────────────────────────────── */}
        <TabsContent value="analytics">
          {statsQuery.isLoading ? (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {Array.from({ length: 4 }).map((_, i) => (
                <div key={i} className="h-20 rounded-xl bg-muted animate-pulse" />
              ))}
            </div>
          ) : (
            <AnalyticsPanel stats={stats} />
          )}
        </TabsContent>

        {/* ── INSIGHTS / PERSONALIZATION TAB ───────────────────────────── */}
        <TabsContent value="personalization">
          <PersonalizationPanel />
        </TabsContent>

        {/* ── ATHENA KNOWS TAB (Phase 16: semantic long-term memory) ────── */}
        <TabsContent value="athena_knows">
          <AthenaKnowsPanel />
        </TabsContent>
      </Tabs>
    </div>
  );
}
