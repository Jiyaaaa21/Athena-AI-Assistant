/**
 * Routines page — Phase 18
 *
 * Lets users create named multi-step voice macros: "Good Morning" →
 * ["what's the weather", "what are my reminders for today", "any goals
 * I should focus on"], triggered by saying the trigger phrase to Athena
 * in chat or voice mode.
 */
import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { PageHeader } from "@/components/athena/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import { Plus, Trash2, Edit2, Play, Zap, X } from "lucide-react";
import { request, isLive } from "@/lib/api";
import { toast } from "sonner";
import { EmptyState } from "@/components/athena/empty-state";

export const Route = createFileRoute("/routines")({
  head: () => ({ meta: [{ title: "Athena — Routines" }] }),
  component: RoutinesPage,
});

interface RoutineData {
  id: number;
  name: string;
  triggerPhrase: string;
  steps: string[];
  enabled: boolean;
}

function RoutineDialog({ open, onClose, initial }: { open: boolean; onClose: () => void; initial?: RoutineData | null }) {
  const qc = useQueryClient();
  const [name, setName] = useState(initial?.name ?? "");
  const [trigger, setTrigger] = useState(initial?.triggerPhrase ?? "");
  const [steps, setSteps] = useState<string[]>(initial?.steps ?? [""]);

  const save = useMutation({
    mutationFn: () => {
      const cleanSteps = steps.map(s => s.trim()).filter(Boolean);
      const body = { name, trigger_phrase: trigger, steps: cleanSteps, enabled: true };
      return initial
        ? request(`/routines/${initial.id}`, { method: "PUT", body: JSON.stringify(body) })
        : request("/routines", { method: "POST", body: JSON.stringify(body) });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["routines"] });
      onClose();
      toast.success(initial ? "Routine updated" : "Routine created");
    },
    onError: () => toast.error("Failed to save routine"),
  });

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader><DialogTitle>{initial ? "Edit Routine" : "New Routine"}</DialogTitle></DialogHeader>
        <div className="space-y-4 py-2">
          <div>
            <label className="text-sm font-medium mb-1 block">Name</label>
            <Input value={name} onChange={e => setName(e.target.value)} placeholder="Good Morning" />
          </div>
          <div>
            <label className="text-sm font-medium mb-1 block">Trigger phrase</label>
            <Input value={trigger} onChange={e => setTrigger(e.target.value)} placeholder="good morning" />
            <p className="text-xs text-muted-foreground mt-1">Say this to Athena (in chat or voice) to run the routine.</p>
          </div>
          <div>
            <label className="text-sm font-medium mb-1 block">Steps (run in order)</label>
            <div className="space-y-2">
              {steps.map((s, i) => (
                <div key={i} className="flex items-center gap-2">
                  <Input
                    value={s}
                    onChange={e => setSteps(prev => prev.map((v, idx) => idx === i ? e.target.value : v))}
                    placeholder="What's the weather today?"
                  />
                  {steps.length > 1 && (
                    <button onClick={() => setSteps(prev => prev.filter((_, idx) => idx !== i))}
                      className="p-1.5 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive">
                      <X className="size-3.5" />
                    </button>
                  )}
                </div>
              ))}
            </div>
            <Button variant="outline" size="sm" className="mt-2" onClick={() => setSteps(prev => [...prev, ""])}>
              <Plus className="size-3.5 mr-1.5" /> Add step
            </Button>
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button onClick={() => save.mutate()} disabled={!name.trim() || !trigger.trim() || save.isPending}>
            {save.isPending ? "Saving…" : "Save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function RoutinesPage() {
  const qc = useQueryClient();
  const [dialog, setDialog] = useState<{ open: boolean; item?: RoutineData | null }>({ open: false });

  const { data, isLoading } = useQuery({
    queryKey: ["routines"],
    queryFn: () => isLive ? request<{ routines: RoutineData[] }>("/routines") : Promise.resolve({ routines: [] }),
  });

  const deleteRoutine = useMutation({
    mutationFn: (id: number) => request(`/routines/${id}`, { method: "DELETE" }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["routines"] }); toast.success("Routine deleted"); },
  });

  const toggleEnabled = useMutation({
    mutationFn: (r: RoutineData) => request(`/routines/${r.id}`, {
      method: "PUT",
      body: JSON.stringify({ name: r.name, trigger_phrase: r.triggerPhrase, steps: r.steps, enabled: !r.enabled }),
    }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["routines"] }),
  });

  const runRoutine = useMutation({
    mutationFn: (id: number) => request(`/routines/${id}/run`, { method: "POST" }),
    onSuccess: (data: any) => toast.success(`"${data.routineName}" ran — check chat for full results`),
    onError: () => toast.error("Routine failed to run"),
  });

  const routines = data?.routines ?? [];

  return (
    <div className="flex flex-col h-svh overflow-hidden">
      <div className="px-6 pt-8">
        <PageHeader
          title="Routines"
          description="Named multi-step voice macros — say the trigger phrase to run several actions at once."
          actions={<Button size="sm" onClick={() => setDialog({ open: true })}><Plus className="size-3.5 mr-1.5" /> New Routine</Button>}
        />
      </div>
      <div className="flex-1 overflow-y-auto px-6 py-6">
        {isLoading ? (
          <div className="space-y-3">{[0,1].map(i => <div key={i} className="h-24 bg-muted rounded-xl animate-pulse" />)}</div>
        ) : routines.length === 0 ? (
          <EmptyState
            icon={Zap}
            title="No routines yet"
            description='Create one for "good morning" that checks weather, reminders, and goals all at once.'
            tone="warning"
            action={
              <Button size="sm" variant="outline" onClick={() => setDialog({ open: true })}>
                <Plus className="size-3.5 mr-1.5" /> Create your first routine
              </Button>
            }
          />
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {routines.map(r => (
              <Card key={r.id} className={!r.enabled ? "opacity-50" : ""}>
                <CardHeader className="pb-2">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <CardTitle className="text-sm">{r.name}</CardTitle>
                      <p className="text-xs text-muted-foreground mt-0.5">Trigger: "{r.triggerPhrase}"</p>
                    </div>
                    <Switch checked={r.enabled} onCheckedChange={() => toggleEnabled.mutate(r)} />
                  </div>
                </CardHeader>
                <CardContent className="pt-0">
                  <ol className="text-xs text-muted-foreground space-y-1 mb-3 list-decimal list-inside">
                    {r.steps.map((s, i) => <li key={i} className="truncate">{s}</li>)}
                  </ol>
                  <div className="flex items-center gap-1.5">
                    <Button size="sm" variant="outline" onClick={() => runRoutine.mutate(r.id)} disabled={runRoutine.isPending}>
                      <Play className="size-3 mr-1" /> Run now
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setDialog({ open: true, item: r })}>
                      <Edit2 className="size-3" />
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => deleteRoutine.mutate(r.id)}>
                      <Trash2 className="size-3" />
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>
      <RoutineDialog open={dialog.open} initial={dialog.item} onClose={() => setDialog({ open: false })} />
    </div>
  );
}
