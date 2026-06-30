import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useState, useCallback, useRef } from "react";
import {
  Search, StickyNote, Bell, Brain, FileText, Filter,
  ChevronRight, Loader2, Network, AlertCircle, X,
} from "lucide-react";
import { searchApi, type SearchResult, type KnowledgeGraph } from "@/lib/api";
import { PageHeader } from "@/components/athena/page-header";
import { EmptyState } from "@/components/athena/empty-state";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/search")({
  head: () => ({
    meta: [
      { title: "Athena — Search" },
      { name: "description", content: "Search across your entire Athena knowledge base." },
    ],
  }),
  component: SearchPage,
});

// ── Types & constants ────────────────────────────────────────────────────────

type SourceFilter = "all" | "notes" | "reminders" | "memory" | "documents";

const SOURCE_META: Record<string, { icon: typeof Search; color: string; label: string; route: string }> = {
  notes:     { icon: StickyNote, color: "text-amber-600 bg-amber-50 dark:bg-amber-900/20",     label: "Note",     route: "/notes" },
  reminders: { icon: Bell,       color: "text-blue-600 bg-blue-50 dark:bg-blue-900/20",         label: "Reminder", route: "/reminders" },
  memory:    { icon: Brain,      color: "text-purple-600 bg-purple-50 dark:bg-purple-900/20",   label: "Memory",   route: "/memory" },
  documents: { icon: FileText,   color: "text-red-600 bg-red-50 dark:bg-red-900/20",            label: "Document", route: "/documents" },
};

// ── Highlight renderer ───────────────────────────────────────────────────────

function HighlightedText({ text, spans }: { text: string; spans: [number, number][] }) {
  if (!spans.length) return <span>{text}</span>;

  const parts: React.ReactNode[] = [];
  let cursor = 0;

  for (const [start, end] of spans) {
    if (start > cursor) parts.push(<span key={cursor}>{text.slice(cursor, start)}</span>);
    parts.push(
      <mark key={start} className="bg-yellow-200 dark:bg-yellow-800/60 text-foreground rounded-sm px-0.5">
        {text.slice(start, end)}
      </mark>
    );
    cursor = end;
  }
  if (cursor < text.length) parts.push(<span key={cursor}>{text.slice(cursor)}</span>);

  return <>{parts}</>;
}

// ── Knowledge Graph (pure CSS/SVG, no external lib) ──────────────────────────

function KnowledgeGraphView({ graph }: { graph: KnowledgeGraph }) {
  const NODE_TYPE_COLORS: Record<string, string> = {
    query:    "#6366f1",
    note:     "#f59e0b",
    reminder: "#3b82f6",
    document: "#ef4444",
    memory:   "#a855f7",
  };

  // Simple force-free layout: query at centre, others in a circle
  const cx = 300, cy = 200, r = 140;
  const nonQuery = graph.nodes.filter((n) => n.type !== "query");
  const positions: Record<string, { x: number; y: number }> = { query: { x: cx, y: cy } };
  nonQuery.forEach((n, i) => {
    const angle = (2 * Math.PI * i) / Math.max(nonQuery.length, 1) - Math.PI / 2;
    positions[n.id] = { x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle) };
  });

  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
        <Network className="size-4 text-primary" /> Knowledge Graph
      </h3>
      <svg viewBox="0 0 600 400" className="w-full h-56 overflow-visible">
        <defs>
          <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#94a3b8" />
          </marker>
        </defs>
        {/* Edges */}
        {graph.edges.map((e, i) => {
          const from = positions[e.from];
          const to = positions[e.to];
          if (!from || !to) return null;
          const mx = (from.x + to.x) / 2;
          const my = (from.y + to.y) / 2;
          return (
            <g key={i}>
              <line
                x1={from.x} y1={from.y} x2={to.x} y2={to.y}
                stroke="#cbd5e1" strokeWidth={1.5} markerEnd="url(#arrow)"
                strokeDasharray="4 2"
              />
              <text x={mx} y={my - 4} textAnchor="middle" fontSize={9} fill="#94a3b8" className="select-none">
                {e.label}
              </text>
            </g>
          );
        })}
        {/* Nodes */}
        {graph.nodes.map((n) => {
          const pos = positions[n.id];
          if (!pos) return null;
          const color = NODE_TYPE_COLORS[n.type] ?? "#64748b";
          const isQuery = n.type === "query";
          return (
            <g key={n.id} transform={`translate(${pos.x},${pos.y})`}>
              <circle r={isQuery ? 22 : 16} fill={color} fillOpacity={0.15} stroke={color} strokeWidth={isQuery ? 2 : 1.5} />
              <text textAnchor="middle" dominantBaseline="middle" fontSize={isQuery ? 10 : 9}
                fill={color} fontWeight={isQuery ? "600" : "400"} className="select-none">
                {n.label.slice(0, 12)}{n.label.length > 12 ? "…" : ""}
              </text>
              <text y={isQuery ? 28 : 22} textAnchor="middle" fontSize={8} fill="#94a3b8" className="select-none capitalize">
                {n.type}
              </text>
            </g>
          );
        })}
      </svg>
      <p className="text-xs text-muted-foreground mt-2">
        {graph.nodes.length} entities · {graph.edges.length} connections
      </p>
    </div>
  );
}

// ── Result card ──────────────────────────────────────────────────────────────

function ResultCard({ result, onClick }: { result: SearchResult; onClick: () => void }) {
  const sm = SOURCE_META[result.source];
  const Icon = sm?.icon ?? Search;

  return (
    <button
      onClick={onClick}
      className="w-full text-left rounded-xl border border-border bg-card px-4 py-3.5 ring-1 ring-black/5 hover:shadow-md hover:border-primary/30 transition-all group"
    >
      <div className="flex items-start gap-3">
        <div className={cn("size-8 rounded-lg grid place-items-center shrink-0 mt-0.5", sm?.color)}>
          <Icon className="size-4" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-0.5 flex-wrap">
            <span className="text-sm font-medium truncate">{result.title}</span>
            <Badge variant="outline" className="text-[10px] px-1.5 py-0 capitalize shrink-0">
              {sm?.label}
            </Badge>
            {result.score < 1 && (
              <Badge variant="secondary" className="text-[10px] px-1.5 py-0 shrink-0">
                {Math.round(result.score * 100)}% match
              </Badge>
            )}
            {(result.meta as any)?.pinned && (
              <Badge variant="outline" className="text-[10px] px-1.5 py-0 text-amber-600 border-amber-300">pinned</Badge>
            )}
          </div>
          <p className="text-xs text-muted-foreground leading-relaxed">
            <HighlightedText
              text={result.excerpt}
              spans={result.highlight as [number, number][]}
            />
          </p>
          {/* Source-specific meta badges */}
          <div className="flex flex-wrap items-center gap-1.5 mt-2">
            {(result.meta as any)?.category && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-secondary text-secondary-foreground">
                {(result.meta as any).category}
              </span>
            )}
            {(result.meta as any)?.tags?.map((t: string) => (
              <span key={t} className="text-[10px] px-1.5 py-0.5 rounded bg-secondary text-secondary-foreground">
                #{t}
              </span>
            ))}
            {(result.meta as any)?.pages && (
              <span className="text-[10px] text-muted-foreground">{(result.meta as any).pages} pages</span>
            )}
            {(result.meta as any)?.dueAt && !((result.meta as any)?.done) && (
              <span className="text-[10px] text-muted-foreground">
                Due {new Date((result.meta as any).dueAt).toLocaleDateString()}
              </span>
            )}
            {(result.meta as any)?.role && (
              <span className="text-[10px] text-muted-foreground capitalize">{(result.meta as any).role} message</span>
            )}
            {(result.meta as any)?.createdAt && (
              <span className="text-[10px] text-muted-foreground">
                {new Date((result.meta as any).createdAt).toLocaleDateString()}
              </span>
            )}
          </div>
        </div>
        <ChevronRight className="size-4 text-muted-foreground shrink-0 mt-1 opacity-0 group-hover:opacity-100 transition-opacity" />
      </div>
    </button>
  );
}

// ── Main page ────────────────────────────────────────────────────────────────

function SearchPage() {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [committed, setCommitted] = useState("");
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>("all");
  const [showGraph, setShowGraph] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleInput = useCallback((v: string) => {
    setQuery(v);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => setCommitted(v.trim()), 400);
  }, []);

  const { data, isFetching, isError } = useQuery({
    queryKey: ["search", committed, sourceFilter, showGraph],
    queryFn: () =>
      searchApi.global({
        q: committed,
        sources: sourceFilter === "all" ? undefined : [sourceFilter],
        limit: 8,
        includeGraph: showGraph,
      }),
    enabled: committed.length >= 2,
    staleTime: 15_000,
  });

  const results = data?.results ?? [];

  const counts = results.reduce<Record<string, number>>((acc, r) => {
    acc[r.source] = (acc[r.source] ?? 0) + 1;
    return acc;
  }, {});

  const goToResult = (r: SearchResult) => {
    const sm = SOURCE_META[r.source];
    if (sm) navigate({ to: sm.route });
  };

  return (
    <div className="max-w-3xl mx-auto w-full px-4 sm:px-6 py-10">
      <PageHeader
        title="Search"
        description="Search across notes, reminders, memory, and documents in one place."
      />

      {/* Search bar */}
      <div className="relative mb-6">
        <Search className="absolute left-4 top-1/2 -translate-y-1/2 size-5 text-muted-foreground" />
        <Input
          ref={inputRef}
          value={query}
          onChange={(e) => handleInput(e.target.value)}
          placeholder="Search your entire knowledge base…"
          className="pl-11 pr-10 h-12 text-base rounded-xl shadow-sm"
          autoFocus
        />
        {query && (
          <button
            onClick={() => { setQuery(""); setCommitted(""); inputRef.current?.focus(); }}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
          >
            <X className="size-4" />
          </button>
        )}
      </div>

      {/* Filters + options row */}
      <div className="flex items-center justify-between gap-3 mb-6 flex-wrap">
        <Tabs value={sourceFilter} onValueChange={(v) => setSourceFilter(v as SourceFilter)}>
          <TabsList className="h-8">
            <TabsTrigger value="all" className="text-xs h-7 px-3">
              All {data && <Badge variant="secondary" className="ml-1 text-[10px] px-1.5 py-0">{data.total}</Badge>}
            </TabsTrigger>
            {(["notes", "reminders", "memory", "documents"] as const).map((s) => {
              const sm = SOURCE_META[s];
              return (
                <TabsTrigger key={s} value={s} className="text-xs h-7 px-3">
                  {sm.label}{counts[s] ? <Badge variant="secondary" className="ml-1 text-[10px] px-1.5 py-0">{counts[s]}</Badge> : null}
                </TabsTrigger>
              );
            })}
          </TabsList>
        </Tabs>

        <div className="flex items-center gap-2">
          <Button
            variant={showGraph ? "default" : "outline"}
            size="sm"
            className="h-8 text-xs gap-1.5"
            onClick={() => setShowGraph((v) => !v)}
            disabled={!committed}
          >
            <Network className="size-3.5" /> Graph
          </Button>
        </div>
      </div>

      {/* Knowledge graph panel */}
      {showGraph && data?.graph && data.graph.nodes.length > 1 && (
        <div className="mb-6">
          <KnowledgeGraphView graph={data.graph} />
        </div>
      )}

      {/* Results */}
      {!committed || committed.length < 2 ? (
        <EmptyState
          icon={Search}
          title="Start searching"
          description="Type at least 2 characters to search across your entire knowledge base."
        />
      ) : isFetching ? (
        <div className="flex items-center gap-3 py-12 justify-center text-muted-foreground">
          <Loader2 className="size-5 animate-spin" />
          <span className="text-sm">Searching across all sources…</span>
        </div>
      ) : isError ? (
        <EmptyState
          icon={AlertCircle}
          title="Search failed"
          description="Couldn't reach the backend. Make sure Athena is running."
        />
      ) : results.length === 0 ? (
        <EmptyState
          icon={Search}
          title="No results"
          description={`Nothing found for "${committed}"${sourceFilter !== "all" ? ` in ${sourceFilter}` : ""}.`}
        />
      ) : (
        <div className="space-y-3">
          {data && (
            <p className="text-xs text-muted-foreground mb-4">
              {data.total} result{data.total !== 1 ? "s" : ""} across {data.sources_searched.join(", ")}
            </p>
          )}
          {results.map((r) => (
            <ResultCard key={`${r.source}-${r.id}`} result={r} onClick={() => goToResult(r)} />
          ))}
        </div>
      )}
    </div>
  );
}
