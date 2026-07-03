import { createFileRoute } from "@tanstack/react-router";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import {
  ShieldAlert, Users, FileText, Bell, Target, FolderKanban,
  CheckCircle2, XCircle, RotateCcw, LogOut, ScrollText, Loader2,
} from "lucide-react";
import { PageHeader } from "@/components/athena/page-header";
import { EmptyState } from "@/components/athena/empty-state";
import { adminApi, type AdminUserSummary } from "@/lib/api";
import { useAuth } from "@/stores/auth";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Table, TableHeader, TableBody, TableHead, TableRow, TableCell,
} from "@/components/ui/table";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader,
  AlertDialogTitle, AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { formatDistanceToNow } from "date-fns";

export const Route = createFileRoute("/admin")({
  head: () => ({
    meta: [{ title: "Athena — Admin" }],
  }),
  component: AdminPage,
});

function StatCard({ icon: Icon, label, value }: { icon: any; label: string; value: number | string }) {
  return (
    <div className="rounded-xl border border-border bg-card p-4 flex items-center gap-3">
      <div className="size-9 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
        <Icon className="size-4 text-primary" />
      </div>
      <div>
        <div className="text-lg font-semibold leading-tight">{value}</div>
        <div className="text-xs text-muted-foreground">{label}</div>
      </div>
    </div>
  );
}

function UserRow({ user, isSelf }: { user: AdminUserSummary; isSelf: boolean }) {
  const qc = useQueryClient();

  const deactivateMutation = useMutation({
    mutationFn: () => adminApi.deactivate(user.id),
    onSuccess: (data) => {
      toast.success(data.message);
      qc.invalidateQueries({ queryKey: ["admin-users"] });
      qc.invalidateQueries({ queryKey: ["admin-audit-log"] });
    },
    onError: (e: Error) => toast.error(e.message || "Failed to deactivate"),
  });

  const reactivateMutation = useMutation({
    mutationFn: () => adminApi.reactivate(user.id),
    onSuccess: (data) => {
      toast.success(data.message);
      qc.invalidateQueries({ queryKey: ["admin-users"] });
      qc.invalidateQueries({ queryKey: ["admin-audit-log"] });
    },
    onError: (e: Error) => toast.error(e.message || "Failed to reactivate"),
  });

  const revokeMutation = useMutation({
    mutationFn: () => adminApi.revokeSessions(user.id),
    onSuccess: (data) => {
      toast.success(data.message);
      qc.invalidateQueries({ queryKey: ["admin-audit-log"] });
    },
    onError: (e: Error) => toast.error(e.message || "Failed to revoke sessions"),
  });

  const busy = deactivateMutation.isPending || reactivateMutation.isPending || revokeMutation.isPending;

  return (
    <TableRow>
      <TableCell>
        <div className="font-medium">{user.name}</div>
        <div className="text-xs text-muted-foreground">{user.email}</div>
      </TableCell>
      <TableCell>
        <div className="flex flex-wrap gap-1">
          {user.is_admin && <Badge variant="secondary" className="text-[10px]">Admin</Badge>}
          {user.is_active ? (
            <Badge variant="outline" className="text-[10px] text-emerald-600 border-emerald-300">Active</Badge>
          ) : (
            <Badge variant="outline" className="text-[10px] text-destructive border-destructive/40">Deactivated</Badge>
          )}
        </div>
      </TableCell>
      <TableCell className="text-xs text-muted-foreground">
        {user.counts.notes} notes · {user.counts.reminders} reminders · {user.counts.goals} goals ·{" "}
        {user.counts.documents} docs · {user.counts.conversations} chats
        {user.google_calendar_connected && <span className="ml-1">· 📅 connected</span>}
      </TableCell>
      <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
        {user.created_at ? formatDistanceToNow(new Date(user.created_at), { addSuffix: true }) : "—"}
      </TableCell>
      <TableCell>
        <div className="flex items-center justify-end gap-1.5">
          {busy && <Loader2 className="size-3.5 animate-spin text-muted-foreground" />}

          <Button
            variant="ghost" size="sm" className="h-7 px-2 text-xs"
            onClick={() => revokeMutation.mutate()}
            disabled={busy}
            title="Force sign-out on every device"
          >
            <LogOut className="size-3 mr-1" />
            Sign out
          </Button>

          {user.is_active ? (
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button variant="ghost" size="sm" className="h-7 px-2 text-xs text-destructive" disabled={busy || isSelf}>
                  <XCircle className="size-3 mr-1" />
                  Deactivate
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Deactivate {user.email}?</AlertDialogTitle>
                  <AlertDialogDescription>
                    They'll be signed out everywhere immediately and won't be able to log back in until reactivated.
                    Their data is not deleted.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Cancel</AlertDialogCancel>
                  <AlertDialogAction
                    onClick={() => deactivateMutation.mutate()}
                    className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                  >
                    Deactivate
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          ) : (
            <Button
              variant="ghost" size="sm" className="h-7 px-2 text-xs text-emerald-600"
              onClick={() => reactivateMutation.mutate()}
              disabled={busy}
            >
              <RotateCcw className="size-3 mr-1" />
              Reactivate
            </Button>
          )}
        </div>
      </TableCell>
    </TableRow>
  );
}

function AuditLogSection() {
  const { data, isLoading } = useQuery({
    queryKey: ["admin-audit-log"],
    queryFn: () => adminApi.auditLog(50),
  });

  if (isLoading) {
    return <div className="h-32 rounded-lg bg-muted animate-pulse" />;
  }

  const entries = data?.entries ?? [];

  if (entries.length === 0) {
    return <p className="text-sm text-muted-foreground">No admin actions yet.</p>;
  }

  return (
    <div className="space-y-1.5">
      {entries.map((e) => (
        <div key={e.id} className="flex items-center justify-between text-xs py-1.5 border-b border-border/60 last:border-0">
          <span>
            <span className="font-medium">{e.admin_email}</span>
            <span className="text-muted-foreground"> {e.action.replace(/_/g, " ")} </span>
            {e.target_email && <span className="font-medium">{e.target_email}</span>}
          </span>
          <span className="text-muted-foreground whitespace-nowrap ml-2">
            {e.created_at ? formatDistanceToNow(new Date(e.created_at), { addSuffix: true }) : ""}
          </span>
        </div>
      ))}
    </div>
  );
}

function AdminPage() {
  const currentUser = useAuth((s) => s.user);
  const [showAuditLog, setShowAuditLog] = useState(false);

  const overviewQuery = useQuery({
    queryKey: ["admin-overview"],
    queryFn: () => adminApi.overview(),
    enabled: !!currentUser?.is_admin,
  });

  const usersQuery = useQuery({
    queryKey: ["admin-users"],
    queryFn: () => adminApi.listUsers(),
    enabled: !!currentUser?.is_admin,
  });

  if (!currentUser?.is_admin) {
    return (
      <div className="max-w-3xl mx-auto w-full px-4 sm:px-6 py-10">
        <EmptyState
          icon={ShieldAlert}
          title="Admin access required"
          description="This area is only visible to admin accounts. The backend enforces this independently of what's shown here."
        />
      </div>
    );
  }

  const overview = overviewQuery.data;

  return (
    <div className="max-w-6xl mx-auto w-full px-4 sm:px-6 py-10 space-y-6">
      <PageHeader
        title="Admin"
        description="Users, usage, and account actions across this deployment."
      />

      {overviewQuery.isLoading ? (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-16 rounded-xl bg-muted animate-pulse" />
          ))}
        </div>
      ) : overview ? (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
          <StatCard icon={Users} label="Total users" value={overview.total_users} />
          <StatCard icon={CheckCircle2} label="Active" value={overview.active_users} />
          <StatCard icon={XCircle} label="Deactivated" value={overview.deactivated_users} />
          <StatCard icon={FileText} label="Documents" value={overview.totals.documents} />
          <StatCard icon={Bell} label="Reminders" value={overview.totals.reminders} />
          <StatCard icon={Target} label="Goals" value={overview.totals.goals} />
        </div>
      ) : null}

      <div className="rounded-xl border border-border bg-card overflow-hidden">
        <div className="px-4 py-3 border-b border-border">
          <h2 className="text-sm font-semibold">Users</h2>
        </div>
        {usersQuery.isLoading ? (
          <div className="p-4 space-y-2">
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="h-10 rounded-lg bg-muted animate-pulse" />
            ))}
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>User</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Data</TableHead>
                <TableHead>Joined</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {usersQuery.data?.users.map((u) => (
                <UserRow key={u.id} user={u} isSelf={u.id === currentUser.id} />
              ))}
            </TableBody>
          </Table>
        )}
      </div>

      <div className="rounded-xl border border-border bg-card p-4">
        <button
          className="flex items-center gap-2 text-sm font-semibold w-full"
          onClick={() => setShowAuditLog((v) => !v)}
        >
          <ScrollText className="size-4 text-primary" />
          Recent admin activity
        </button>
        {showAuditLog && (
          <div className="mt-3">
            <AuditLogSection />
          </div>
        )}
      </div>
    </div>
  );
}
