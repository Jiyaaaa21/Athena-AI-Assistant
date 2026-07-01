/**
 * Goals & Projects — Phase 15 Frontend
 * 
 * The backend (Phase 14) already has full Goals and Projects APIs.
 * This page wires them up for the first time in the frontend.
 * 
 * Features:
 *  - Create / edit / delete goals with progress tracking
 *  - Create / archive / delete projects  
 *  - Ask Athena about a goal/project directly from the card
 */
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { PageHeader } from "@/components/athena/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Card, CardContent, CardHeader, CardTitle,
} from "@/components/ui/card";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Slider } from "@/components/ui/slider";
import {
  Target, FolderOpen, Plus, Trash2, Edit2, MessageSquare,
  CheckCircle2, Pause, TrendingUp, Archive,
} from "lucide-react";
import { goalsApi, projectsApi, type Goal, type Project } from "@/lib/api";
import { useChat } from "@/stores/chat";
import { toast } from "sonner";
import { EmptyState } from "@/components/athena/empty-state";

export const Route = createFileRoute("/goals")({
  head: () => ({
    meta: [{ title: "Athena — Goals & Projects" }],
  }),
  component: GoalsPage,
});

const TIMEFRAME_LABELS: Record<string, string> = {
  short: "Short-term",
  medium: "Medium-term",
  long: "Long-term",
};

const TIMEFRAME_COLORS: Record<string, string> = {
  short: "bg-emerald-50 text-emerald-700 border-emerald-200",
  medium: "bg-blue-50 text-blue-700 border-blue-200",
  long: "bg-purple-50 text-purple-700 border-purple-200",
};

const STATUS_ICONS: Record<string, React.ReactNode> = {
  active: <TrendingUp className="size-3" />,
  completed: <CheckCircle2 className="size-3" />,
  paused: <Pause className="size-3" />,
};

// ── Goal Card ─────────────────────────────────────────────────────────────────

function GoalCard({ goal, onEdit, onDelete, onAsk }: {
  goal: Goal;
  onEdit: (g: Goal) => void;
  onDelete: (id: number) => void;
  onAsk: (title: string) => void;
}) {
  const qc = useQueryClient();
  const progressMut = useMutation({
    mutationFn: ({ id, progress }: { id: number; progress: number }) =>
      goalsApi.updateProgress(id, progress),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["goals"] }),
  });

  return (
    <Card className="group relative hover:border-primary/30 transition-colors">
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-2">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <span className={`inline-flex items-center gap-1 text-[10px] font-medium px-1.5 py-0.5 rounded-full border ${TIMEFRAME_COLORS[goal.timeframe] ?? ""}`}>
                {TIMEFRAME_LABELS[goal.timeframe] ?? goal.timeframe}
              </span>
              <span className="inline-flex items-center gap-1 text-[10px] text-muted-foreground">
                {STATUS_ICONS[goal.status]}
                {goal.status}
              </span>
            </div>
            <CardTitle className="text-sm font-medium leading-snug">{goal.title}</CardTitle>
            {goal.description && (
              <p className="text-xs text-muted-foreground mt-1 leading-relaxed">{goal.description}</p>
            )}
          </div>
          <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
            <button onClick={() => onAsk(goal.title)} title="Ask Athena"
              className="p-1.5 rounded hover:bg-primary/10 text-muted-foreground hover:text-primary transition-colors">
              <MessageSquare className="size-3.5" />
            </button>
            <button onClick={() => onEdit(goal)} title="Edit"
              className="p-1.5 rounded hover:bg-muted text-muted-foreground hover:text-foreground transition-colors">
              <Edit2 className="size-3.5" />
            </button>
            <button onClick={() => onDelete(goal.id)} title="Delete"
              className="p-1.5 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition-colors">
              <Trash2 className="size-3.5" />
            </button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="pt-0">
        <div className="flex items-center gap-3">
          <div className="flex-1 h-2 bg-muted rounded-full overflow-hidden">
            <div
              className="h-full bg-primary/70 rounded-full transition-all duration-300"
              style={{ width: `${goal.progress}%` }}
            />
          </div>
          <span className="text-xs font-medium tabular-nums text-muted-foreground w-8 text-right">
            {goal.progress}%
          </span>
        </div>
        <div className="mt-2">
          <Slider
            value={[goal.progress]}
            min={0}
            max={100}
            step={5}
            onValueCommit={([v]) => progressMut.mutate({ id: goal.id, progress: v })}
            className="[&_[role=slider]]:h-3 [&_[role=slider]]:w-3"
          />
        </div>
      </CardContent>
    </Card>
  );
}

// ── Project Card ──────────────────────────────────────────────────────────────

function ProjectCard({ project, onEdit, onDelete, onAsk }: {
  project: Project;
  onEdit: (p: Project) => void;
  onDelete: (id: number) => void;
  onAsk: (name: string) => void;
}) {
  return (
    <Card className="group relative hover:border-primary/30 transition-colors">
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-2">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <Badge variant={project.status === "active" ? "default" : "secondary"}
                className="text-[10px] h-4">
                {project.status}
              </Badge>
            </div>
            <CardTitle className="text-sm font-medium">{project.name}</CardTitle>
            {project.description && (
              <p className="text-xs text-muted-foreground mt-1 leading-relaxed">
                {project.description}
              </p>
            )}
          </div>
          <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
            <button onClick={() => onAsk(project.name)} title="Ask Athena"
              className="p-1.5 rounded hover:bg-primary/10 text-muted-foreground hover:text-primary transition-colors">
              <MessageSquare className="size-3.5" />
            </button>
            <button onClick={() => onEdit(project)} title="Edit"
              className="p-1.5 rounded hover:bg-muted text-muted-foreground hover:text-foreground transition-colors">
              <Edit2 className="size-3.5" />
            </button>
            <button onClick={() => onDelete(project.id)} title="Delete"
              className="p-1.5 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition-colors">
              <Trash2 className="size-3.5" />
            </button>
          </div>
        </div>
      </CardHeader>
    </Card>
  );
}

// ── Goal Dialog ───────────────────────────────────────────────────────────────

function GoalDialog({ open, onClose, initial }: {
  open: boolean;
  onClose: () => void;
  initial?: Goal | null;
}) {
  const qc = useQueryClient();
  const [title, setTitle] = useState(initial?.title ?? "");
  const [desc, setDesc] = useState(initial?.description ?? "");
  const [timeframe, setTimeframe] = useState<string>(initial?.timeframe ?? "medium");
  const [status, setStatus] = useState<string>(initial?.status ?? "active");

  const save = useMutation({
    mutationFn: () =>
      initial
        ? goalsApi.update(initial.id, { title, description: desc || null, timeframe, status } as Partial<Goal>)
        : goalsApi.create({ title, description: desc || undefined, timeframe }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["goals"] }); onClose(); toast.success(initial ? "Goal updated" : "Goal created"); },
    onError: () => toast.error("Failed to save goal"),
  });

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{initial ? "Edit Goal" : "New Goal"}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div>
            <label className="text-sm font-medium mb-1 block">Title</label>
            <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Launch Athena v2" />
          </div>
          <div>
            <label className="text-sm font-medium mb-1 block">Description (optional)</label>
            <Textarea value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="What does success look like?" rows={3} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-sm font-medium mb-1 block">Timeframe</label>
              <Select value={timeframe} onValueChange={setTimeframe}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="short">Short-term</SelectItem>
                  <SelectItem value="medium">Medium-term</SelectItem>
                  <SelectItem value="long">Long-term</SelectItem>
                </SelectContent>
              </Select>
            </div>
            {initial && (
              <div>
                <label className="text-sm font-medium mb-1 block">Status</label>
                <Select value={status} onValueChange={setStatus}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="active">Active</SelectItem>
                    <SelectItem value="paused">Paused</SelectItem>
                    <SelectItem value="completed">Completed</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            )}
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button onClick={() => save.mutate()} disabled={!title.trim() || save.isPending}>
            {save.isPending ? "Saving…" : "Save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── Project Dialog ────────────────────────────────────────────────────────────

function ProjectDialog({ open, onClose, initial }: {
  open: boolean;
  onClose: () => void;
  initial?: Project | null;
}) {
  const qc = useQueryClient();
  const [name, setName] = useState(initial?.name ?? "");
  const [desc, setDesc] = useState(initial?.description ?? "");
  const [status, setStatus] = useState<string>(initial?.status ?? "active");

  const save = useMutation({
    mutationFn: () =>
      initial
        ? projectsApi.update(initial.id, { name, description: desc || null, status } as Partial<Project>)
        : projectsApi.create({ name, description: desc || undefined }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["projects"] }); onClose(); toast.success(initial ? "Project updated" : "Project created"); },
    onError: () => toast.error("Failed to save project"),
  });

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{initial ? "Edit Project" : "New Project"}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div>
            <label className="text-sm font-medium mb-1 block">Name</label>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Product Launch Q3" />
          </div>
          <div>
            <label className="text-sm font-medium mb-1 block">Description (optional)</label>
            <Textarea value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="What is this project about?" rows={3} />
          </div>
          {initial && (
            <div>
              <label className="text-sm font-medium mb-1 block">Status</label>
              <Select value={status} onValueChange={setStatus}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="active">Active</SelectItem>
                  <SelectItem value="archived">Archived</SelectItem>
                </SelectContent>
              </Select>
            </div>
          )}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button onClick={() => save.mutate()} disabled={!name.trim() || save.isPending}>
            {save.isPending ? "Saving…" : "Save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

function GoalsPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const sendStream = useChat((s) => s.sendStream);
  const resetChat = useChat((s) => s.reset);

  const [goalDialog, setGoalDialog] = useState<{ open: boolean; item?: Goal | null }>({ open: false });
  const [projectDialog, setProjectDialog] = useState<{ open: boolean; item?: Project | null }>({ open: false });

  const { data: goals = [], isLoading: goalsLoading } = useQuery({
    queryKey: ["goals"],
    queryFn: goalsApi.list,
  });

  const { data: projects = [], isLoading: projectsLoading } = useQuery({
    queryKey: ["projects"],
    queryFn: projectsApi.list,
  });

  const deleteGoal = useMutation({
    mutationFn: goalsApi.remove,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["goals"] }); toast.success("Goal deleted"); },
  });

  const deleteProject = useMutation({
    mutationFn: projectsApi.remove,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["projects"] }); toast.success("Project deleted"); },
  });

  const handleAskGoal = (title: string) => {
    resetChat();
    navigate({ to: "/" });
    setTimeout(() => sendStream(`What should I do today to make progress on my goal: "${title}"?`), 100);
  };

  const handleAskProject = (name: string) => {
    resetChat();
    navigate({ to: "/" });
    setTimeout(() => sendStream(`Give me a detailed status and next steps for my project: "${name}"`), 100);
  };

  const activeGoals = goals.filter((g) => g.status === "active");
  const otherGoals = goals.filter((g) => g.status !== "active");
  const activeProjects = projects.filter((p) => p.status === "active");
  const archivedProjects = projects.filter((p) => p.status === "archived");

  return (
    <div className="flex flex-col h-svh overflow-hidden">
      <div className="px-6 pt-8">
        <PageHeader
          title="Goals & Projects"
          description="Track your long-term goals and active projects. Athena uses these to give you better, more relevant answers."
          actions={
            <div className="flex items-center gap-2">
              <Button variant="outline" size="sm" onClick={() => setProjectDialog({ open: true })}>
                <FolderOpen className="size-3.5 mr-1.5" /> New Project
              </Button>
              <Button size="sm" onClick={() => setGoalDialog({ open: true })}>
                <Plus className="size-3.5 mr-1.5" /> New Goal
              </Button>
            </div>
          }
        />
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-6 space-y-10">
        {/* ── Goals ── */}
        <section>
          <div className="flex items-center gap-2 mb-4">
            <Target className="size-4 text-primary" />
            <h2 className="text-sm font-semibold">Active Goals</h2>
            {activeGoals.length > 0 && (
              <span className="text-xs text-muted-foreground">({activeGoals.length})</span>
            )}
          </div>

          {goalsLoading ? (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {[0,1,2].map(i => <div key={i} className="h-32 bg-muted rounded-xl animate-pulse" />)}
            </div>
          ) : activeGoals.length === 0 ? (
            <EmptyState
              icon={Target}
              title="No active goals yet"
              description="Set a goal and Athena will help you track progress toward it."
              tone="success"
              action={
                <Button size="sm" variant="outline" onClick={() => setGoalDialog({ open: true })}>
                  <Plus className="size-3.5 mr-1.5" /> Add your first goal
                </Button>
              }
            />
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {activeGoals.map((g) => (
                <GoalCard
                  key={g.id}
                  goal={g}
                  onEdit={(g) => setGoalDialog({ open: true, item: g })}
                  onDelete={(id) => deleteGoal.mutate(id)}
                  onAsk={handleAskGoal}
                />
              ))}
            </div>
          )}

          {otherGoals.length > 0 && (
            <div className="mt-6">
              <p className="text-xs text-muted-foreground font-medium uppercase tracking-widest mb-3">Completed / Paused</p>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 opacity-60">
                {otherGoals.map((g) => (
                  <GoalCard
                    key={g.id}
                    goal={g}
                    onEdit={(g) => setGoalDialog({ open: true, item: g })}
                    onDelete={(id) => deleteGoal.mutate(id)}
                    onAsk={handleAskGoal}
                  />
                ))}
              </div>
            </div>
          )}
        </section>

        {/* ── Projects ── */}
        <section>
          <div className="flex items-center gap-2 mb-4">
            <FolderOpen className="size-4 text-primary" />
            <h2 className="text-sm font-semibold">Active Projects</h2>
            {activeProjects.length > 0 && (
              <span className="text-xs text-muted-foreground">({activeProjects.length})</span>
            )}
          </div>

          {projectsLoading ? (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {[0,1].map(i => <div key={i} className="h-24 bg-muted rounded-xl animate-pulse" />)}
            </div>
          ) : activeProjects.length === 0 ? (
            <EmptyState
              icon={FolderOpen}
              title="No projects yet"
              description="Create a project to group related goals, notes, and reminders."
              tone="info"
              action={
                <Button size="sm" variant="outline" onClick={() => setProjectDialog({ open: true })}>
                  <Plus className="size-3.5 mr-1.5" /> Create a project
                </Button>
              }
            />
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {activeProjects.map((p) => (
                <ProjectCard
                  key={p.id}
                  project={p}
                  onEdit={(p) => setProjectDialog({ open: true, item: p })}
                  onDelete={(id) => deleteProject.mutate(id)}
                  onAsk={handleAskProject}
                />
              ))}
            </div>
          )}

          {archivedProjects.length > 0 && (
            <div className="mt-6">
              <p className="text-xs text-muted-foreground font-medium uppercase tracking-widest mb-3">Archived</p>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 opacity-50">
                {archivedProjects.map((p) => (
                  <ProjectCard
                    key={p.id}
                    project={p}
                    onEdit={(p) => setProjectDialog({ open: true, item: p })}
                    onDelete={(id) => deleteProject.mutate(id)}
                    onAsk={handleAskProject}
                  />
                ))}
              </div>
            </div>
          )}
        </section>
      </div>

      <GoalDialog
        open={goalDialog.open}
        initial={goalDialog.item}
        onClose={() => setGoalDialog({ open: false })}
      />
      <ProjectDialog
        open={projectDialog.open}
        initial={projectDialog.item}
        onClose={() => setProjectDialog({ open: false })}
      />
    </div>
  );
}
