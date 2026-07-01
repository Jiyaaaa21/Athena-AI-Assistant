import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import {
  Pin,
  PinOff,
  Plus,
  Search,
  StickyNote,
  Trash2,
  LayoutGrid,
  List as ListIcon,
  Tag as TagIcon,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { PageHeader } from "@/components/athena/page-header";
import { ExportMenu } from "@/components/athena/export-menu";
import { EmptyState } from "@/components/athena/empty-state";
import { notesApi } from "@/lib/api";
import type { Note } from "@/lib/mock";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogTitle,
  DialogTrigger,
  DialogFooter,
  DialogHeader,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { toast } from "sonner";
import { motion } from "framer-motion";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/notes")({
  head: () => ({
    meta: [
      { title: "Athena — Notes" },
      {
        name: "description",
        content:
          "Capture thoughts, plans, and references in your Athena workspace.",
      },
    ],
  }),
  component: NotesPage,
});

const ALL_CATEGORIES = "__all__";

function NotesPage() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["notes"],
    queryFn: notesApi.list,
  });
  const [q, setQ] = useState("");
  const [categoryFilter, setCategoryFilter] = useState(ALL_CATEGORIES);
  const [view, setView] = useState<"grid" | "list">("grid");
  const [editing, setEditing] = useState<Note | null>(null);
  // Roadmap addition: Note Tags. Edited as a single comma-separated string
  // in the dialog and only split into Note["tags"] (string[]) on save, so
  // typing a trailing comma/space doesn't get silently swallowed mid-keystroke.
  const [tagsDraft, setTagsDraft] = useState("");
  const [open, setOpen] = useState(false);

  const create = useMutation({
    mutationFn: notesApi.create,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["notes"] });
      toast.success("Note created");
    },
    onError: (e: Error) => toast.error(e.message || "Couldn't create note"),
  });
  const update = useMutation({
    mutationFn: notesApi.update,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["notes"] }),
    onError: (e: Error) => toast.error(e.message || "Couldn't save note"),
  });
  const remove = useMutation({
    mutationFn: notesApi.remove,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["notes"] });
      toast.success("Deleted");
    },
    onError: (e: Error) => toast.error(e.message || "Couldn't delete note"),
  });

  // Roadmap addition: Note Categories — distinct categories present across
  // existing notes, used to populate the filter dropdown.
  const categories = useMemo(() => {
    const set = new Set<string>();
    for (const n of data ?? []) {
      if (n.category) set.add(n.category);
    }
    return Array.from(set).sort();
  }, [data]);

  const filtered = (data ?? [])
    .filter((n) =>
      `${n.title} ${n.body} ${(n.tags ?? []).join(" ")}`
        .toLowerCase()
        .includes(q.toLowerCase()),
    )
    .filter(
      (n) => categoryFilter === ALL_CATEGORIES || n.category === categoryFilter,
    )
    .sort((a, b) => Number(b.pinned) - Number(a.pinned));

  function openForEdit(n: Note) {
    setEditing(n);
    setTagsDraft((n.tags ?? []).join(", "));
    setOpen(true);
  }

  function openForCreate() {
    setEditing({
      id: "",
      title: "",
      body: "",
      pinned: false,
      createdAt: "",
      updatedAt: "",
      category: null,
      tags: [],
    });
    setTagsDraft("");
  }

  function parseTagsDraft(): string[] {
    return tagsDraft
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean);
  }

  return (
    <div className="max-w-6xl mx-auto w-full px-4 sm:px-6 py-10">
      <PageHeader
        title="Notes"
        description="A second brain for your workspace."
        actions={
          <div className="flex items-center gap-2">
            {/* Phase 8: Export notes */}
            <ExportMenu type="notes" label="Export" />
            <div className="flex rounded-md border border-border bg-card p-0.5">
              <button
                onClick={() => setView("grid")}
                className={cn(
                  "p-1.5 rounded",
                  view === "grid" && "bg-secondary",
                )}
                aria-label="Grid view"
              >
                <LayoutGrid className="size-4" />
              </button>
              <button
                onClick={() => setView("list")}
                className={cn(
                  "p-1.5 rounded",
                  view === "list" && "bg-secondary",
                )}
                aria-label="List view"
              >
                <ListIcon className="size-4" />
              </button>
            </div>
            <Dialog
              open={open}
              onOpenChange={(o) => {
                setOpen(o);
                if (!o) {
                  setEditing(null);
                  setTagsDraft("");
                }
              }}
            >
              <DialogTrigger asChild>
                <Button onClick={openForCreate}>
                  <Plus className="size-4" /> New note
                </Button>
              </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>
                    {editing?.id ? "Edit note" : "New note"}
                  </DialogTitle>
                </DialogHeader>
                <div className="space-y-3">
                  <Input
                    placeholder="Title"
                    value={editing?.title ?? ""}
                    onChange={(e) =>
                      setEditing((n) => n && { ...n, title: e.target.value })
                    }
                  />
                  <Textarea
                    rows={6}
                    placeholder="Write something… (Markdown supported — **bold**, lists, etc.)"
                    value={editing?.body ?? ""}
                    onChange={(e) =>
                      setEditing((n) => n && { ...n, body: e.target.value })
                    }
                  />
                  <div className="grid grid-cols-2 gap-3">
                    <Input
                      placeholder="Category (optional)"
                      value={editing?.category ?? ""}
                      onChange={(e) =>
                        setEditing(
                          (n) =>
                            n && { ...n, category: e.target.value || null },
                        )
                      }
                    />
                    <Input
                      placeholder="Tags, comma separated"
                      value={tagsDraft}
                      onChange={(e) => setTagsDraft(e.target.value)}
                    />
                  </div>
                </div>
                <DialogFooter>
                  <Button
                    onClick={() => {
                      if (!editing) return;
                      const tags = parseTagsDraft();
                      if (editing.id) {
                        update.mutate({ ...editing, tags });
                      } else {
                        create.mutate({
                          title: editing.title || "Untitled",
                          body: editing.body,
                          pinned: editing.pinned,
                          category: editing.category || null,
                          tags,
                          updatedAt: null,
                        });
                      }
                      setOpen(false);
                      setEditing(null);
                      setTagsDraft("");
                    }}
                  >
                    Save
                  </Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>
          </div>
        }
      />

      {!isLoading && (data?.length ?? 0) > 0 && (
        <div className="flex flex-wrap items-center gap-3 mb-6">
          <div className="relative max-w-sm flex-1 min-w-[200px]">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
            <Input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search notes…"
              className="pl-9"
            />
          </div>
          {categories.length > 0 && (
            <Select value={categoryFilter} onValueChange={setCategoryFilter}>
              <SelectTrigger className="w-[180px]">
                <SelectValue placeholder="All categories" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL_CATEGORIES}>All categories</SelectItem>
                {categories.map((c) => (
                  <SelectItem key={c} value={c}>
                    {c}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        </div>
      )}

      {isLoading ? (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-36 rounded-xl bg-muted animate-pulse" />
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={StickyNote}
          title="No notes yet"
          description="Create your first note."
          tone="accent"
        />
      ) : (
        <div
          className={cn(
            view === "grid"
              ? "grid sm:grid-cols-2 lg:grid-cols-3 gap-4"
              : "space-y-2",
          )}
        >
          {filtered.map((n, i) => (
            <motion.div
              key={n.id}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.03 }}
              onClick={() => openForEdit(n)}
              className="rounded-xl border border-border bg-card p-4 ring-1 ring-black/5 hover:shadow-md transition-all cursor-pointer group"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="font-medium text-sm flex-1 truncate">
                  {n.title}
                </div>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    update.mutate({ ...n, pinned: !n.pinned });
                  }}
                  className="text-muted-foreground hover:text-primary"
                  aria-label={n.pinned ? "Unpin" : "Pin"}
                >
                  {n.pinned ? (
                    <Pin className="size-3.5 fill-primary text-primary" />
                  ) : (
                    <PinOff className="size-3.5" />
                  )}
                </button>
              </div>

              {n.category && (
                <Badge variant="secondary" className="mt-2">
                  {n.category}
                </Badge>
              )}

              <div className="prose prose-sm prose-zinc max-w-none text-xs text-muted-foreground mt-2 line-clamp-3 prose-p:my-0 prose-headings:my-0 prose-ul:my-0 prose-li:my-0">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {n.body}
                </ReactMarkdown>
              </div>

              {n.tags && n.tags.length > 0 && (
                <div className="flex flex-wrap items-center gap-1 mt-3">
                  <TagIcon className="size-3 text-muted-foreground" />
                  {n.tags.map((t) => (
                    <Badge
                      key={t}
                      variant="outline"
                      className="text-[10px] px-1.5 py-0"
                    >
                      {t}
                    </Badge>
                  ))}
                </div>
              )}

              <div className="flex items-center justify-between mt-4 text-[10px] text-muted-foreground">
                <span>{n.createdAt ? new Date(n.createdAt).toLocaleDateString() : "—"}</span>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    remove.mutate(n.id);
                  }}
                  className="opacity-0 group-hover:opacity-100 transition-opacity hover:text-destructive"
                  aria-label="Delete"
                >
                  <Trash2 className="size-3" />
                </button>
              </div>
            </motion.div>
          ))}
        </div>
      )}
    </div>
  );
}