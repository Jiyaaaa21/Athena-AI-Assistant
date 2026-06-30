import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { format, parseISO } from "date-fns";
import { PageHeader } from "@/components/athena/page-header";
import { EmptyState } from "@/components/athena/empty-state";
import { KpiCard } from "@/components/athena/kpi-card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  MessageSquare,
  FileText,
  StickyNote,
  Bell,
  AlertCircle,
  RefreshCw,
  Send,
  Flame,
  TrendingUp,
  BarChart2,
  Activity,
  Zap,
} from "lucide-react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  RadialBar,
  RadialBarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  Legend,
  Line,
  LineChart,
} from "recharts";
import { analyticsApi } from "@/lib/api";

export const Route = createFileRoute("/analytics")({
  head: () => ({
    meta: [
      { title: "Athena — Analytics" },
      {
        name: "description",
        content: "Usage insights for your Athena workspace.",
      },
    ],
  }),
  component: AnalyticsPage,
});

// ─── Types ────────────────────────────────────────────────────────────────────

interface AnalyticsData {
  conversations: { total: number; thisWeek: number };
  documents: { total: number; thisWeek: number };
  notes: { total: number; thisWeek: number };
  reminders: { total: number; dueSoon: number };
  messages_sent?: { total: number; thisWeek: number };
  activity: { date: string; conversations: number; documents: number; notes?: number }[];
  tool_usage?: { tool: string; count: number }[];
  top_features?: { feature: string; count: number; pct: number }[];
  weekly_trend?: { week: string; label: string; conversations: number; documents: number; notes: number }[];
  monthly_trend?: { month: string; label: string; conversations: number; documents: number; notes: number }[];
  heatmap?: { day: number; dayLabel: string; hours: number[] }[];
  hourly_distribution?: { hour: number; count: number }[];
  streak?: number;
  avg_messages_per_day?: number;
  reminders_active?: number;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

const CHART_COLORS = {
  primary: "hsl(var(--primary))",
  blue: "#3b82f6",
  emerald: "#10b981",
  amber: "#f59e0b",
  violet: "#8b5cf6",
  rose: "#f43f5e",
};

const TOOL_COLORS: Record<string, string> = {
  calculator: CHART_COLORS.amber,
  rag: CHART_COLORS.violet,
  weather: CHART_COLORS.blue,
  news: CHART_COLORS.emerald,
  notes: CHART_COLORS.primary,
  reminder: CHART_COLORS.rose,
};

function SectionTitle({ icon: Icon, title, subtitle }: { icon: React.ElementType; title: string; subtitle?: string }) {
  return (
    <div className="flex items-center gap-2 mb-4">
      <Icon className="size-4 text-muted-foreground" />
      <div>
        <h3 className="text-base font-semibold tracking-tight">{title}</h3>
        {subtitle && <p className="text-xs text-muted-foreground">{subtitle}</p>}
      </div>
    </div>
  );
}

const cardCls = "rounded-2xl border border-border bg-card p-6 ring-1 ring-black/5";

type TrendKey = "14d" | "weekly" | "monthly";

// ─── Heatmap component ────────────────────────────────────────────────────────

function ActivityHeatmap({ data }: { data: AnalyticsData["heatmap"] }) {
  if (!data?.length) return <p className="text-sm text-muted-foreground">No data yet.</p>;

  const maxVal = Math.max(...data.flatMap((r) => r.hours));

  return (
    <div className="overflow-x-auto">
      <div className="min-w-[560px]">
        {/* Hour labels */}
        <div className="flex ml-10 mb-1">
          {[0, 3, 6, 9, 12, 15, 18, 21].map((h) => (
            <div key={h} className="text-[9px] text-muted-foreground" style={{ width: `${(3 / 24) * 100}%` }}>
              {h === 0 ? "12am" : h < 12 ? `${h}am` : h === 12 ? "12pm" : `${h - 12}pm`}
            </div>
          ))}
        </div>
        {data.map((row) => (
          <div key={row.day} className="flex items-center gap-1 mb-0.5">
            <span className="text-[9px] text-muted-foreground w-9 shrink-0 text-right pr-1">{row.dayLabel}</span>
            <div className="flex gap-0.5 flex-1">
              {row.hours.map((v, h) => {
                const intensity = maxVal > 0 ? v / maxVal : 0;
                const bg = intensity === 0
                  ? "bg-muted"
                  : intensity < 0.25
                  ? "bg-primary/20"
                  : intensity < 0.5
                  ? "bg-primary/40"
                  : intensity < 0.75
                  ? "bg-primary/65"
                  : "bg-primary";
                return (
                  <div
                    key={h}
                    title={`${row.dayLabel} ${h}:00 — ${v} messages`}
                    className={`${bg} rounded-[3px] flex-1 aspect-square transition-colors cursor-default`}
                  />
                );
              })}
            </div>
          </div>
        ))}
        {/* Legend */}
        <div className="flex items-center gap-1.5 mt-3 ml-10">
          <span className="text-[9px] text-muted-foreground">Less</span>
          {["bg-muted", "bg-primary/20", "bg-primary/40", "bg-primary/65", "bg-primary"].map((c, i) => (
            <div key={i} className={`${c} size-3 rounded-[2px]`} />
          ))}
          <span className="text-[9px] text-muted-foreground">More</span>
        </div>
      </div>
    </div>
  );
}

// ─── Top Features bar ─────────────────────────────────────────────────────────

function TopFeatures({ data }: { data: AnalyticsData["top_features"] }) {
  if (!data?.length) return <p className="text-sm text-muted-foreground">No feature data yet.</p>;
  const FEAT_COLORS = [CHART_COLORS.primary, CHART_COLORS.blue, CHART_COLORS.emerald, CHART_COLORS.amber, CHART_COLORS.violet, CHART_COLORS.rose];

  return (
    <div className="space-y-3">
      {data.map((f, i) => (
        <div key={f.feature}>
          <div className="flex items-center justify-between text-xs mb-1">
            <span className="font-medium">{f.feature}</span>
            <span className="text-muted-foreground">{f.count} uses · {f.pct}%</span>
          </div>
          <div className="h-2 rounded-full bg-muted overflow-hidden">
            <div
              className="h-full rounded-full transition-all"
              style={{ width: `${f.pct}%`, background: FEAT_COLORS[i % FEAT_COLORS.length] }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

// ─── Hourly distribution ──────────────────────────────────────────────────────

function HourlyDistribution({ data }: { data: AnalyticsData["hourly_distribution"] }) {
  if (!data?.length) return null;
  const formatted = data.map((d) => ({
    hour: d.hour === 0 ? "12a" : d.hour < 12 ? `${d.hour}a` : d.hour === 12 ? "12p" : `${d.hour - 12}p`,
    count: d.count,
  }));
  return (
    <div className="h-44">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={formatted} margin={{ top: 0, right: 0, left: -28, bottom: 0 }}>
          <CartesianGrid stroke="var(--border)" vertical={false} />
          <XAxis dataKey="hour" fontSize={9} stroke="var(--muted-foreground)" interval={1} />
          <YAxis fontSize={9} stroke="var(--muted-foreground)" />
          <Tooltip
            contentStyle={{ borderRadius: 10, border: "1px solid var(--border)", background: "var(--card)" }}
            labelFormatter={(l) => `${l} — messages`}
          />
          <Bar dataKey="count" fill={CHART_COLORS.primary} radius={[3, 3, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

function AnalyticsPage() {
  const { data, isLoading, isError, isFetching, refetch } = useQuery({
    queryKey: ["analytics"],
    queryFn: analyticsApi.get,
  });

  const [trendView, setTrendView] = useState<TrendKey>("14d");

  const d = data as AnalyticsData | undefined;

  // Trend chart data based on selected view
  const trendData = (() => {
    if (!d) return [];
    if (trendView === "14d") {
      return d.activity.map((a) => ({
        label: format(parseISO(a.date), "MMM d"),
        conversations: a.conversations,
        documents: a.documents,
        notes: a.notes ?? 0,
      }));
    }
    if (trendView === "weekly" && d.weekly_trend?.length) {
      return d.weekly_trend.map((w) => ({
        label: w.label,
        conversations: w.conversations,
        documents: w.documents,
        notes: w.notes,
      }));
    }
    if (trendView === "monthly" && d.monthly_trend?.length) {
      return d.monthly_trend.map((m) => ({
        label: m.label,
        conversations: m.conversations,
        documents: m.documents,
        notes: m.notes,
      }));
    }
    return d.activity.map((a) => ({
      label: format(parseISO(a.date), "MMM d"),
      conversations: a.conversations,
      documents: a.documents,
      notes: a.notes ?? 0,
    }));
  })();

  return (
    <div className="max-w-6xl mx-auto w-full px-4 sm:px-6 py-10">
      <PageHeader
        title="Analytics"
        description="Your productivity at a glance."
        actions={
          <Button variant="outline" size="sm" onClick={() => refetch()} disabled={isFetching}>
            <RefreshCw className={`size-4 ${isFetching ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        }
      />

      {isLoading ? (
        <div className="space-y-6">
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {Array.from({ length: 8 }).map((_, i) => (
              <div key={i} className="h-28 rounded-2xl bg-muted animate-pulse" />
            ))}
          </div>
          <div className="h-64 rounded-2xl bg-muted animate-pulse" />
        </div>
      ) : isError ? (
        <EmptyState
          icon={AlertCircle}
          title="Couldn't load analytics"
          description="Something went wrong fetching your usage data."
          action={<Button onClick={() => refetch()}>Try again</Button>}
        />
      ) : !d ? null : (
        <div className="space-y-8">

          {/* ── KPI Grid ────────────────────────────────────────────────── */}
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <KpiCard
              icon={MessageSquare}
              label="Conversations"
              value={d.conversations.total}
              delta={d.conversations.thisWeek > 0 ? `+${d.conversations.thisWeek} this week` : undefined}
            />
            <KpiCard
              icon={Send}
              label="Messages Sent"
              value={d.messages_sent?.total ?? d.conversations.total * 2}
              delta={d.messages_sent?.thisWeek ? `+${d.messages_sent.thisWeek} this week` : undefined}
            />
            <KpiCard
              icon={FileText}
              label="Documents"
              value={d.documents.total}
              delta={d.documents.thisWeek > 0 ? `+${d.documents.thisWeek} this week` : undefined}
            />
            <KpiCard
              icon={StickyNote}
              label="Notes"
              value={d.notes.total}
              delta={d.notes.thisWeek > 0 ? `+${d.notes.thisWeek} this week` : undefined}
            />
            <KpiCard
              icon={Bell}
              label="Reminders"
              value={d.reminders.total}
              delta={d.reminders.dueSoon > 0 ? `${d.reminders.dueSoon} due soon` : undefined}
            />
            <KpiCard
              icon={Flame}
              label="Active Streak"
              value={`${d.streak ?? 0} day${(d.streak ?? 0) !== 1 ? "s" : ""}`}
              delta="consecutive days"
            />
            <KpiCard
              icon={TrendingUp}
              label="Avg / Day"
              value={d.avg_messages_per_day ?? 0}
              delta="messages (30-day avg)"
            />
            <KpiCard
              icon={Activity}
              label="Active Reminders"
              value={d.reminders_active ?? d.reminders.total}
              delta="pending"
            />
          </div>

          {/* ── Trend Chart ─────────────────────────────────────────────── */}
          <div className={cardCls}>
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
              <SectionTitle icon={TrendingUp} title="Activity Trends" subtitle="Conversations, documents and notes over time" />
              <div className="flex items-center gap-1 border border-border rounded-lg p-0.5 self-start sm:self-auto">
                {(["14d", "weekly", "monthly"] as TrendKey[]).map((v) => (
                  <button
                    key={v}
                    onClick={() => setTrendView(v)}
                    className={`px-3 py-1 rounded-md text-xs font-medium transition-all ${
                      trendView === v ? "bg-primary text-primary-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    {v === "14d" ? "14 Days" : v === "weekly" ? "8 Weeks" : "12 Months"}
                  </button>
                ))}
              </div>
            </div>
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={trendData} margin={{ top: 0, right: 0, left: -28, bottom: 0 }}>
                  <defs>
                    <linearGradient id="gConv" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={CHART_COLORS.primary} stopOpacity={0.35} />
                      <stop offset="100%" stopColor={CHART_COLORS.primary} stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="gDocs" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={CHART_COLORS.blue} stopOpacity={0.3} />
                      <stop offset="100%" stopColor={CHART_COLORS.blue} stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="gNotes" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={CHART_COLORS.emerald} stopOpacity={0.3} />
                      <stop offset="100%" stopColor={CHART_COLORS.emerald} stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke="var(--border)" vertical={false} />
                  <XAxis dataKey="label" stroke="var(--muted-foreground)" fontSize={10} />
                  <YAxis stroke="var(--muted-foreground)" fontSize={10} />
                  <Tooltip
                    contentStyle={{ borderRadius: 12, border: "1px solid var(--border)", background: "var(--card)", fontSize: 12 }}
                  />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Area dataKey="conversations" name="Conversations" stroke={CHART_COLORS.primary} fill="url(#gConv)" strokeWidth={2} />
                  <Area dataKey="documents" name="Documents" stroke={CHART_COLORS.blue} fill="url(#gDocs)" strokeWidth={2} />
                  <Area dataKey="notes" name="Notes" stroke={CHART_COLORS.emerald} fill="url(#gNotes)" strokeWidth={2} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* ── Activity Heatmap + Hourly ────────────────────────────────── */}
          <div className="grid lg:grid-cols-2 gap-6">
            <div className={cardCls}>
              <SectionTitle icon={Activity} title="Activity Heatmap" subtitle="Last 12 weeks by day & hour" />
              <ActivityHeatmap data={d.heatmap} />
            </div>
            <div className={cardCls}>
              <SectionTitle icon={BarChart2} title="Usage by Hour" subtitle="All-time messages per hour of day" />
              <HourlyDistribution data={d.hourly_distribution} />
            </div>
          </div>

          {/* ── Tool Usage + Top Features ────────────────────────────────── */}
          <div className="grid lg:grid-cols-2 gap-6">
            {/* Tool usage bar chart */}
            <div className={cardCls}>
              <SectionTitle icon={Zap} title="Tool Usage" subtitle="Inferred from conversation content" />
              {!d.tool_usage?.some((t) => t.count > 0) ? (
                <p className="text-sm text-muted-foreground">No tool usage detected yet.</p>
              ) : (
                <div className="h-52">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart
                      data={d.tool_usage.filter((t) => t.count > 0)}
                      layout="vertical"
                      margin={{ top: 0, right: 16, left: 8, bottom: 0 }}
                    >
                      <CartesianGrid stroke="var(--border)" horizontal={false} />
                      <XAxis type="number" fontSize={10} stroke="var(--muted-foreground)" />
                      <YAxis dataKey="tool" type="category" fontSize={11} stroke="var(--muted-foreground)" width={70} />
                      <Tooltip
                        contentStyle={{ borderRadius: 10, border: "1px solid var(--border)", background: "var(--card)", fontSize: 12 }}
                      />
                      <Bar dataKey="count" radius={[0, 4, 4, 0]}>
                        {d.tool_usage.filter((t) => t.count > 0).map((t) => (
                          <Cell key={t.tool} fill={TOOL_COLORS[t.tool] ?? CHART_COLORS.primary} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>

            {/* Top features */}
            <div className={cardCls}>
              <SectionTitle icon={TrendingUp} title="Top Features" subtitle="Most used capabilities" />
              <TopFeatures data={d.top_features} />
            </div>
          </div>

          {/* ── Monthly bar ──────────────────────────────────────────────── */}
          {d.monthly_trend && (
            <div className={cardCls}>
              <SectionTitle icon={BarChart2} title="Monthly Overview" subtitle="Last 12 months of activity" />
              <div className="h-56">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={d.monthly_trend} margin={{ top: 0, right: 0, left: -28, bottom: 0 }}>
                    <CartesianGrid stroke="var(--border)" vertical={false} />
                    <XAxis dataKey="label" fontSize={10} stroke="var(--muted-foreground)" />
                    <YAxis fontSize={10} stroke="var(--muted-foreground)" />
                    <Tooltip
                      contentStyle={{ borderRadius: 12, border: "1px solid var(--border)", background: "var(--card)", fontSize: 12 }}
                    />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <Bar dataKey="conversations" name="Conversations" fill={CHART_COLORS.primary} radius={[3, 3, 0, 0]} stackId="a" />
                    <Bar dataKey="notes" name="Notes" fill={CHART_COLORS.emerald} radius={[0, 0, 0, 0]} stackId="a" />
                    <Bar dataKey="documents" name="Documents" fill={CHART_COLORS.blue} radius={[3, 3, 0, 0]} stackId="a" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}

        </div>
      )}
    </div>
  );
}
