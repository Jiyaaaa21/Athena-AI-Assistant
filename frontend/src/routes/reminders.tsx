import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Bell, Plus, Trash2, Pencil, AlertCircle } from "lucide-react";
import { PageHeader } from "@/components/athena/page-header";
import { EmptyState } from "@/components/athena/empty-state";
import { remindersApi } from "@/lib/api";
import type { Reminder } from "@/lib/mock";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { formatDistanceToNow } from "date-fns";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/reminders")({
  head: () => ({
    meta: [
      { title: "Athena — Reminders" },
      {
        name: "description",
        content: "Stay on top of what matters with Athena reminders.",
      },
    ],
  }),
  component: RemindersPage,
});

const ALL_CATEGORIES = "__all__";

// Roadmap addition: Overdue Status. The backend already derives and sends
// `overdue`, but mock/offline mode has no backend to compute it, so this is
// a client-side fallback that works either way.
function isOverdue(r: Reminder): boolean {
  if (r.overdue !== undefined) return r.overdue;
  return !r.done && new Date(r.dueAt).getTime() < Date.now();
}

function emptyDraft(): Reminder {
  return {
    id: "",
    title: "",
    dueAt: "",
    done: false,
    priority: "med",
    category: null,
  };
}

function toLocalInputValue(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function RemindersPage() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["reminders"],
    queryFn: remindersApi.list,
  });
  const [open, setOpen] = useState(false);
  const [categoryFilter, setCategoryFilter] = useState(ALL_CATEGORIES);
  // Roadmap addition: Edit Reminder. `draft` backs both the "New reminder"
  // and "Edit reminder" dialog; `draft.id` (empty vs set) decides create vs update.
  const [draft, setDraft] = useState<Reminder>(emptyDraft());
  const [dueLocal, setDueLocal] = useState("");

  const create = useMutation({
    mutationFn: remindersApi.create,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["reminders"] });
      toast.success("Reminder added");
    },
    onError: (e: Error) => toast.error(e.message || "Couldn't create reminder"),
  });
  const update = useMutation({
    mutationFn: remindersApi.update,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["reminders"] });
      toast.success("Reminder updated");
    },
    onError: (e: Error) => toast.error(e.message || "Couldn't save reminder"),
  });
  const toggle = useMutation({
    mutationFn: ({ id, done }: { id: string; done: boolean }) =>
      remindersApi.toggle(id, done),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["reminders"] }),
    onError: (e: Error) => toast.error(e.message || "Couldn't update reminder"),
  });
  const remove = useMutation({
    mutationFn: remindersApi.remove,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["reminders"] }),
    onError: (e: Error) => toast.error(e.message || "Couldn't delete reminder"),
  });

  // Roadmap addition: Reminder Categories — distinct categories present
  // across existing reminders, used to populate the filter dropdown.
  const categories = useMemo(() => {
    const set = new Set<string>();
    for (const r of data ?? []) {
      if (r.category) set.add(r.category);
    }
    return Array.from(set).sort();
  }, [data]);

  const visible = (data ?? []).filter(
    (r) => categoryFilter === ALL_CATEGORIES || r.category === categoryFilter,
  );
  const upcoming = visible.filter((r) => !r.done);
  const done = visible.filter((r) => r.done);

  function openCreate() {
    setDraft(emptyDraft());
    setDueLocal("");
    setOpen(true);
  }

  function openEdit(r: Reminder) {
    setDraft(r);
    setDueLocal(toLocalInputValue(r.dueAt));
    setOpen(true);
  }

  function save() {
    if (!draft.title.trim()) return;
    const dueAt = dueLocal
      ? new Date(dueLocal).toISOString()
      : new Date(Date.now() + 86400000).toISOString();
    if (draft.id) {
      update.mutate({ ...draft, dueAt });
    } else {
      create.mutate({
        title: draft.title,
        dueAt,
        done: false,
        priority: draft.priority ?? "med",
        category: draft.category || null,
      });
    }
    setOpen(false);
    setDraft(emptyDraft());
    setDueLocal("");
  }

  return (
    <div className="max-w-3xl mx-auto w-full px-4 sm:px-6 py-10">
      <PageHeader
        title="Reminders"
        description="Time-aware tasks Athena can surface when relevant."
        actions={
          <Dialog
            open={open}
            onOpenChange={(o) => {
              setOpen(o);
              if (!o) {
                setDraft(emptyDraft());
                setDueLocal("");
              }
            }}
          >
            <DialogTrigger asChild>
              <Button onClick={openCreate}>
                <Plus className="size-4" /> New reminder
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>
                  {draft.id ? "Edit reminder" : "New reminder"}
                </DialogTitle>
              </DialogHeader>
              <div className="space-y-3">
                <Input
                  placeholder="What's the reminder?"
                  value={draft.title}
                  onChange={(e) =>
                    setDraft((d) => ({ ...d, title: e.target.value }))
                  }
                />
                <Input
                  type="datetime-local"
                  value={dueLocal}
                  onChange={(e) => setDueLocal(e.target.value)}
                />
                <div className="grid grid-cols-2 gap-3">
                  <Select
                    value={draft.priority ?? "med"}
                    onValueChange={(v) =>
                      setDraft((d) => ({
                        ...d,
                        priority: v as Reminder["priority"],
                      }))
                    }
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="Priority" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="low">Low</SelectItem>
                      <SelectItem value="med">Medium</SelectItem>
                      <SelectItem value="high">High</SelectItem>
                    </SelectContent>
                  </Select>
                  <Input
                    placeholder="Category (optional)"
                    value={draft.category ?? ""}
                    onChange={(e) =>
                      setDraft((d) => ({
                        ...d,
                        category: e.target.value || null,
                      }))
                    }
                  />
                </div>
              </div>
              <DialogFooter>
                <Button onClick={save}>Save</Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        }
      />

      {categories.length > 0 && (
        <div className="mb-6 max-w-[200px]">
          <Select value={categoryFilter} onValueChange={setCategoryFilter}>
            <SelectTrigger>
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
        </div>
      )}

      {isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-14 rounded-lg bg-muted animate-pulse" />
          ))}
        </div>
      ) : upcoming.length + done.length === 0 ? (
        <EmptyState
          icon={Bell}
          title="Nothing scheduled"
          description="Create a reminder to get started."
        />
      ) : (
        <>
          <Section
            title="Upcoming"
            items={upcoming}
            onToggle={(id, done) => toggle.mutate({ id, done })}
            onRemove={(id) => remove.mutate(id)}
            onEdit={openEdit}
          />
          {done.length > 0 && (
            <Section
              title="Completed"
              items={done}
              onToggle={(id, d) => toggle.mutate({ id, done: d })}
              onRemove={(id) => remove.mutate(id)}
              onEdit={openEdit}
              muted
            />
          )}
        </>
      )}
    </div>
  );
}

function Section({
  title,
  items,
  onToggle,
  onRemove,
  onEdit,
  muted,
}: {
  title: string;
  items: Reminder[];
  onToggle: (id: string, done: boolean) => void;
  onRemove: (id: string) => void;
  onEdit: (r: Reminder) => void;
  muted?: boolean;
}) {
  return (
    <div className="mb-8">
      <h2 className="text-xs uppercase tracking-widest text-muted-foreground font-semibold mb-2">
        {title}
      </h2>
      <ul className="space-y-2">
        {items.map((r) => {
          const overdue = isOverdue(r);
          return (
            <li
              key={r.id}
              className={cn(
                "flex items-center gap-3 rounded-xl border border-border bg-card px-4 py-3 ring-1 ring-black/5 group hover:shadow-sm transition-all",
                muted && "opacity-60",
                overdue && !muted && "border-destructive/40",
              )}
            >
              <Checkbox
                checked={r.done}
                onCheckedChange={(v) => onToggle(r.id, Boolean(v))}
              />
              <div className="flex-1 min-w-0">
                <div
                  className={cn(
                    "text-sm font-medium",
                    r.done && "line-through text-muted-foreground",
                  )}
                >
                  {r.title}
                </div>
                <div
                  className={cn(
                    "text-xs text-muted-foreground flex items-center gap-1",
                    overdue && !r.done && "text-destructive",
                  )}
                >
                  {overdue && !r.done && <AlertCircle className="size-3" />}
                  {r.done
                    ? "Completed"
                    : overdue
                      ? `Overdue · was due ${formatDistanceToNow(new Date(r.dueAt), { addSuffix: true })}`
                      : `Due ${formatDistanceToNow(new Date(r.dueAt), { addSuffix: true })}`}
                  {r.category && (
                    <span className="text-muted-foreground/70">
                      · {r.category}
                    </span>
                  )}
                </div>
              </div>
              {r.priority === "high" && !r.done && (
                <Badge variant="destructive">High</Badge>
              )}
              {overdue && !r.done && (
                <Badge variant="destructive">Overdue</Badge>
              )}
              {r.category && (
                <Badge variant="secondary" className="hidden sm:inline-flex">
                  {r.category}
                </Badge>
              )}
              <button
                onClick={() => onEdit(r)}
                className="opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-foreground transition"
                aria-label="Edit"
              >
                <Pencil className="size-4" />
              </button>
              <button
                onClick={() => onRemove(r.id)}
                className="opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive transition"
                aria-label="Delete"
              >
                <Trash2 className="size-4" />
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}