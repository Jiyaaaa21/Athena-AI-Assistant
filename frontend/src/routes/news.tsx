import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { PageHeader } from "@/components/athena/page-header";
import { newsApi } from "@/lib/api";
import { Newspaper, ExternalLink, AlertCircle } from "lucide-react";
import { EmptyState } from "@/components/athena/empty-state";
import { Button } from "@/components/ui/button";
import { formatDistanceToNow } from "date-fns";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/news")({
  head: () => ({
    meta: [
      { title: "Athena — News" },
      { name: "description", content: "AI, business, and technology news, summarized by Athena." },
    ],
  }),
  component: NewsPage,
});

const CATEGORIES = [
  { id: "all", label: "All" },
  { id: "ai", label: "AI" },
  { id: "technology", label: "Technology" },
  { id: "business", label: "Business" },
];

function NewsPage() {
  const [cat, setCat] = useState("all");
  const { data, isLoading, isError, refetch } = useQuery({ queryKey: ["news", cat], queryFn: () => newsApi.list(cat) });

  return (
    <div className="max-w-5xl mx-auto w-full px-4 sm:px-6 py-10">
      <PageHeader title="News Center" description="Curated, summarized, and ready to act on." />
      <div className="flex flex-wrap gap-2 mb-6">
        {CATEGORIES.map((c) => (
          <button
            key={c.id}
            onClick={() => setCat(c.id)}
            className={cn(
              "px-3 py-1.5 rounded-full text-xs font-medium border transition-colors",
              cat === c.id ? "bg-primary text-primary-foreground border-primary" : "bg-card border-border hover:bg-muted",
            )}
          >
            {c.label}
          </button>
        ))}
      </div>
      {isLoading ? (
        <div className="grid md:grid-cols-2 gap-4">{Array.from({ length: 4 }).map((_, i) => <div key={i} className="h-32 rounded-xl bg-muted animate-pulse" />)}</div>
      ) : isError ? (
        <EmptyState
          icon={AlertCircle}
          title="Couldn't load news"
          description="Something went wrong fetching the latest stories."
          action={<Button onClick={() => refetch()}>Try again</Button>}
        />
      ) : !data || data.length === 0 ? (
        <EmptyState icon={Newspaper} title="No stories yet" />
      ) : (
        <div className="grid md:grid-cols-2 gap-4">
          {data.map((n) => (
            <a key={n.id} href={n.url} className="block rounded-xl border border-border bg-card p-5 ring-1 ring-black/5 hover:shadow-md transition-shadow group">
              <div className="flex items-center justify-between text-[10px] uppercase tracking-widest text-muted-foreground mb-2">
                <span>{n.source}</span>
                <span>{n.publishedAt ? formatDistanceToNow(new Date(n.publishedAt), { addSuffix: true }) : "Recently"}</span>
              </div>
              <h3 className="text-base font-semibold tracking-tight group-hover:text-primary transition-colors">{n.title}</h3>
              <p className="text-sm text-muted-foreground mt-2 line-clamp-2">{n.summary}</p>
              <div className="mt-3 text-xs text-primary flex items-center gap-1 font-medium"><ExternalLink className="size-3" /> Read more</div>
            </a>
          ))}
        </div>
      )}
    </div>
  );
}