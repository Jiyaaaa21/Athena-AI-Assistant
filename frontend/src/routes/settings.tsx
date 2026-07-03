/**
 * Settings page — ISSUE 9: Simplified settings, ISSUE 10: Theme switching, ISSUE 11: Wake word
 * Cleaned up redundant options while preserving all existing functionality.
 */
import { createFileRoute } from "@tanstack/react-router";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, useCallback } from "react";
import { PageHeader } from "@/components/athena/page-header";
import {
  Card, CardContent, CardHeader, CardTitle, CardDescription,
} from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Slider } from "@/components/ui/slider";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { isLive, API_BASE_URL, preferencesApi, healthApi } from "@/lib/api";
import { voiceApi } from "@/lib/voice-api";
import { useVoice } from "@/stores/voice";
import {
  CheckCircle2, AlertCircle, RefreshCw, Sun, Moon, Monitor,
  Activity, Zap, Volume2, Mic, Play, Globe, CalendarDays, ExternalLink, X,
  Bell, BellOff, BellRing, Send, Info, Sparkles, Download, Trash2, ShieldAlert,
} from "lucide-react";
import { toast } from "sonner";
import { getAccessToken } from "@/stores/auth";
import { useAuth } from "@/stores/auth";
import { useNavigate } from "@tanstack/react-router";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader,
  AlertDialogTitle, AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { usePushNotifications } from "@/hooks/use-push-notifications";
import { pushApi } from "@/lib/push-api";
import { proactiveApi } from "@/lib/proactive-api";

export const Route = createFileRoute("/settings")({
  head: () => ({
    meta: [
      { title: "Athena — Settings" },
      { name: "description", content: "Configure Athena: appearance, voice, and preferences." },
    ],
  }),
  component: SettingsPage,
});

// ── ISSUE 10: Theme helpers ────────────────────────────────────────────────────
type Theme = "light" | "dark" | "system";

function applyTheme(theme: Theme) {
  const root = document.documentElement;
  if (theme === "system") {
    const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    root.classList.toggle("dark", prefersDark);
  } else {
    root.classList.toggle("dark", theme === "dark");
  }
  localStorage.setItem("athena-theme", theme);
}

function getStoredTheme(): Theme {
  return (localStorage.getItem("athena-theme") as Theme) ?? "system";
}

function HealthBadge({ status }: { status: string }) {
  if (status === "ok")
    return (
      <Badge className="bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400 border-emerald-200 dark:border-emerald-800 gap-1">
        <CheckCircle2 className="size-3" /> OK
      </Badge>
    );
  if (status === "degraded")
    return (
      <Badge className="bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400 border-amber-200 dark:border-amber-800 gap-1">
        <AlertCircle className="size-3" /> Degraded
      </Badge>
    );
  return (
    <Badge variant="secondary" className="gap-1">
      <AlertCircle className="size-3" /> {status}
    </Badge>
  );
}

function Row({ label, description, children }: { label: string; description?: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div>
        <Label className="text-sm font-normal">{label}</Label>
        {description && <p className="text-xs text-muted-foreground mt-0.5">{description}</p>}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}

// ── Phase 20: Google Calendar connection card ─────────────────────────────────
//
// Real OAuth connection status — separate from preferences since it has
// its own request/response shape and its own connect/disconnect actions
// that hit dedicated /calendar/* endpoints, not /preferences.

interface CalendarStatus {
  configured: boolean;
  connected: boolean;
  email?: string;
  connectedAt?: string;
}

function CalendarSettingsSection() {
  const qc = useQueryClient();

  const statusQuery = useQuery({
    queryKey: ["calendar-status"],
    queryFn: async (): Promise<CalendarStatus> => {
      if (!isLive) return { configured: false, connected: false };
      const tok = getAccessToken();
      const res = await fetch(`${API_BASE_URL}/calendar/status`, {
        headers: tok ? { Authorization: `Bearer ${tok}` } : {},
      });
      if (!res.ok) return { configured: false, connected: false };
      return res.json();
    },
    enabled: isLive,
  });

  const connectMutation = useMutation({
    mutationFn: async (): Promise<{ authUrl: string }> => {
      const tok = getAccessToken();
      const res = await fetch(`${API_BASE_URL}/calendar/connect`, {
        method: "POST",
        headers: tok ? { Authorization: `Bearer ${tok}` } : {},
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Failed to start connection");
      }
      return res.json();
    },
    onSuccess: (data) => {
      // Full-page redirect to Google's consent screen — this isn't an
      // in-app navigation, it leaves the SPA entirely and comes back via
      // the backend's /calendar/oauth/callback redirect.
      window.location.href = data.authUrl;
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const disconnectMutation = useMutation({
    mutationFn: async () => {
      const tok = getAccessToken();
      const res = await fetch(`${API_BASE_URL}/calendar/disconnect`, {
        method: "DELETE",
        headers: tok ? { Authorization: `Bearer ${tok}` } : {},
      });
      if (!res.ok) throw new Error("Failed to disconnect");
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["calendar-status"] });
      toast.success("Google Calendar disconnected");
    },
    onError: () => toast.error("Failed to disconnect"),
  });

  // Surface the redirect result from /calendar/oauth/callback (it comes
  // back as a query param on this page since FRONTEND_BASE_URL points here)
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("calendar_connected")) {
      toast.success("Google Calendar connected!");
      qc.invalidateQueries({ queryKey: ["calendar-status"] });
      window.history.replaceState({}, "", window.location.pathname);
    }
    const err = params.get("calendar_error");
    if (err) {
      toast.error(`Calendar connection failed: ${err.replace(/_/g, " ")}`);
      window.history.replaceState({}, "", window.location.pathname);
    }
  }, [qc]);

  const status = statusQuery.data;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <CalendarDays className="size-4 text-primary" />
          Calendar
        </CardTitle>
        <CardDescription>
          Connect your real Google Calendar so Athena can see and create actual events — not just internal reminders.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {!isLive ? (
          <p className="text-sm text-muted-foreground">Connect the backend to manage calendar integration.</p>
        ) : statusQuery.isLoading ? (
          <div className="h-12 bg-muted rounded-lg animate-pulse" />
        ) : !status?.configured ? (
          <div className="rounded-lg border border-amber-300/40 bg-amber-50 dark:bg-amber-950/20 p-3 text-sm text-amber-800 dark:text-amber-200">
            <p className="font-medium mb-1">Calendar isn't set up on this server yet.</p>
            <p className="text-xs opacity-90">
              Set <code className="px-1 py-0.5 rounded bg-muted">GOOGLE_CLIENT_ID</code> and{" "}
              <code className="px-1 py-0.5 rounded bg-muted">GOOGLE_CLIENT_SECRET</code> in your backend's
              .env file — see the comments in <code className="px-1 py-0.5 rounded bg-muted">backend/core/config.py</code> for
              the 5-minute Google Cloud Console setup steps.
            </p>
          </div>
        ) : status.connected ? (
          <div className="flex items-center justify-between rounded-lg border border-border bg-muted/30 px-4 py-3">
            <div className="flex items-center gap-3">
              <div className="size-9 rounded-full bg-emerald-100 dark:bg-emerald-900/30 grid place-items-center">
                <CheckCircle2 className="size-4 text-emerald-600 dark:text-emerald-400" />
              </div>
              <div>
                <p className="text-sm font-medium">Connected</p>
                {status.email && <p className="text-xs text-muted-foreground">{status.email}</p>}
              </div>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => disconnectMutation.mutate()}
              disabled={disconnectMutation.isPending}
            >
              <X className="size-3.5 mr-1.5" />
              Disconnect
            </Button>
          </div>
        ) : (
          <Button onClick={() => connectMutation.mutate()} disabled={connectMutation.isPending}>
            <ExternalLink className="size-3.5 mr-1.5" />
            {connectMutation.isPending ? "Redirecting…" : "Connect Google Calendar"}
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

function PushSettingsSection() {
  const qc = useQueryClient();
  const { permission, loading, error, subscribe, unsubscribe } = usePushNotifications();

  const statusQuery = useQuery({
    queryKey: ["push-status"],
    queryFn: () => pushApi.status(),
    enabled: isLive,
    refetchInterval: false,
  });

  const testMutation = useMutation({
    mutationFn: () => pushApi.test(),
    onSuccess: () => toast.success("Test notification sent — check your device."),
    onError: (e: Error) => toast.error(e.message || "Failed to send test notification"),
  });

  const supported =
    typeof window !== "undefined" && "serviceWorker" in navigator && "PushManager" in window;

  const status = statusQuery.data;
  // Bug fix: this used to be `subscribed || permission === "granted"`,
  // which showed "Notifications on" purely because the BROWSER granted
  // permission — even if the POST to /push/subscribe never actually
  // succeeded (backend unreachable, VAPID not ready, network blip).
  // That let the UI claim "on" with zero real subscriptions underneath
  // it. The backend's device count is the only source of truth for
  // whether a subscription is actually saved server-side.
  const isOn = (status?.deviceCount ?? 0) > 0;

  // Whatever subscribe()/unsubscribe() actually did to the backend, make
  // sure the displayed count reflects it immediately instead of waiting
  // on a stale cached query result.
  const handleSubscribe = async () => {
    await subscribe();
    qc.invalidateQueries({ queryKey: ["push-status"] });
  };
  const handleUnsubscribe = async () => {
    await unsubscribe();
    qc.invalidateQueries({ queryKey: ["push-status"] });
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Bell className="size-4 text-primary" />
          Push Notifications
        </CardTitle>
        <CardDescription>
          Get reminders and alerts as real notifications on this device — even when Athena isn't open in a tab.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {!isLive ? (
          <p className="text-sm text-muted-foreground">Connect the backend to manage push notifications.</p>
        ) : !supported ? (
          <div className="rounded-lg border border-amber-300/40 bg-amber-50 dark:bg-amber-950/20 p-3 text-sm text-amber-800 dark:text-amber-200">
            This browser doesn't support push notifications.
          </div>
        ) : statusQuery.isLoading ? (
          <div className="h-12 bg-muted rounded-lg animate-pulse" />
        ) : !status?.configured ? (
          <div className="rounded-lg border border-amber-300/40 bg-amber-50 dark:bg-amber-950/20 p-3 text-sm text-amber-800 dark:text-amber-200">
            <p className="font-medium mb-1">Push isn't set up on this server yet.</p>
            <p className="text-xs opacity-90">
              The backend generates its VAPID keypair automatically on first run — restart the backend
              once, then refresh this page.
            </p>
          </div>
        ) : permission === "denied" ? (
          <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
            Notifications are blocked for this site. Enable them in your browser's site settings, then
            refresh this page.
          </div>
        ) : (
          <div className="space-y-3">
            <div className="flex items-center justify-between rounded-lg border border-border bg-muted/30 px-4 py-3">
              <div className="flex items-center gap-3">
                <div className={`size-9 rounded-full grid place-items-center ${isOn ? "bg-emerald-100 dark:bg-emerald-900/30" : "bg-muted"}`}>
                  {isOn ? (
                    <BellRing className="size-4 text-emerald-600 dark:text-emerald-400" />
                  ) : (
                    <BellOff className="size-4 text-muted-foreground" />
                  )}
                </div>
                <div>
                  <p className="text-sm font-medium">{isOn ? "Notifications on" : "Notifications off"}</p>
                  {isOn && (
                    <p className="text-xs text-muted-foreground">
                      {status?.deviceCount ?? 0} device{status?.deviceCount === 1 ? "" : "s"} subscribed
                    </p>
                  )}
                </div>
              </div>
              {isOn ? (
                <Button variant="outline" size="sm" onClick={handleUnsubscribe} disabled={loading}>
                  <BellOff className="size-3.5 mr-1.5" />
                  Turn off
                </Button>
              ) : (
                <Button size="sm" onClick={handleSubscribe} disabled={loading}>
                  <Bell className="size-3.5 mr-1.5" />
                  {loading ? "Enabling…" : "Enable"}
                </Button>
              )}
            </div>

            {isOn && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => testMutation.mutate()}
                disabled={testMutation.isPending}
              >
                <Send className="size-3.5 mr-1.5" />
                {testMutation.isPending ? "Sending…" : "Send test notification"}
              </Button>
            )}

            {isOn && (
              <div className="flex items-start gap-2 rounded-lg border border-border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
                <Info className="size-3.5 mt-0.5 shrink-0" />
                <p>
                  Chrome only delivers notifications while it's running in the background. For
                  reminders to arrive even after closing every Chrome window, enable{" "}
                  <span className="font-medium text-foreground">
                    "Continue running background apps when Google Chrome is closed"
                  </span>{" "}
                  under <span className="font-medium text-foreground">chrome://settings/system</span>.
                </p>
              </div>
            )}

            {error && <p className="text-xs text-destructive">{error}</p>}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function ProactiveSettingsSection() {
  const [status, setStatus] = useState<"idle" | "loading" | "done">("idle");
  const [result, setResult] = useState<string | null>(null);

  const handleTrigger = async () => {
    setStatus("loading");
    setResult(null);
    try {
      const res = await proactiveApi.trigger();
      if (res.generated && res.insight) {
        setResult(res.insight.message);
        toast.success("Athena found something worth mentioning — check the home screen.");
      } else {
        setResult(res.reason ?? "Nothing worth surfacing right now.");
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to run the proactive check");
    } finally {
      setStatus("done");
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Sparkles className="size-4 text-primary" />
          Proactive Intelligence
        </CardTitle>
        <CardDescription>
          Athena periodically looks at your goals, reminders, and calendar and surfaces something
          unprompted when it's genuinely worth mentioning — shown on your home screen and, if push
          notifications are on, delivered as a real notification too.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {!isLive ? (
          <p className="text-sm text-muted-foreground">Connect the backend to test this.</p>
        ) : (
          <>
            <Button variant="outline" size="sm" onClick={handleTrigger} disabled={status === "loading"}>
              <Sparkles className="size-3.5 mr-1.5" />
              {status === "loading" ? "Checking…" : "Run a check now"}
            </Button>
            {result && (
              <p className="text-xs text-muted-foreground rounded-lg border border-border bg-muted/30 px-3 py-2">
                {result}
              </p>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}

// ── Phase 29: Account — data export + deletion ────────────────────────────────

function AccountSettingsSection() {
  const navigate = useNavigate();
  const logout = useAuth((s) => s.logout);

  const [exporting, setExporting] = useState(false);
  const [deletePassword, setDeletePassword] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);

  const handleExport = async () => {
    if (!isLive) return;
    setExporting(true);
    try {
      const res = await fetch(`${API_BASE_URL}/profile/export`, {
        headers: { Authorization: `Bearer ${getAccessToken()}` },
      });
      if (!res.ok) throw new Error(`Export failed (${res.status})`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "athena_export.zip";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      toast.success("Your data export has started downloading.");
    } catch (e) {
      toast.error((e as Error).message || "Couldn't export your data");
    } finally {
      setExporting(false);
    }
  };

  const handleDelete = async () => {
    if (!isLive || !deletePassword) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      const res = await fetch(`${API_BASE_URL}/profile/me`, {
        method: "DELETE",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${getAccessToken()}`,
        },
        body: JSON.stringify({ password: deletePassword }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setDeleteError(data?.detail || "Couldn't delete your account. Please try again.");
        setDeleting(false);
        return;
      }
      toast.success("Your account has been permanently deleted.");
      await logout();
      navigate({ to: "/login" });
    } catch (e) {
      setDeleteError((e as Error).message || "Couldn't delete your account. Please try again.");
      setDeleting(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ShieldAlert className="size-4 text-primary" />
          Your Data & Account
        </CardTitle>
        <CardDescription>
          Export everything Athena has stored for you, or permanently delete your account.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {!isLive ? (
          <p className="text-sm text-muted-foreground">Connect the backend to manage your account.</p>
        ) : (
          <>
            <Row
              label="Export your data"
              description="Download every note, reminder, goal, conversation, document, and more as a zip file."
            >
              <Button variant="outline" size="sm" onClick={handleExport} disabled={exporting}>
                <Download className="size-3.5 mr-1.5" />
                {exporting ? "Preparing…" : "Export"}
              </Button>
            </Row>

            <div className="pt-2 border-t border-border">
              <Row
                label="Delete your account"
                description="Permanently deletes your account and every piece of data associated with it. This cannot be undone."
              >
                <AlertDialog open={dialogOpen} onOpenChange={(open) => {
                  setDialogOpen(open);
                  if (!open) { setDeletePassword(""); setDeleteError(null); }
                }}>
                  <AlertDialogTrigger asChild>
                    <Button variant="destructive" size="sm">
                      <Trash2 className="size-3.5 mr-1.5" />
                      Delete account
                    </Button>
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>Delete your account permanently?</AlertDialogTitle>
                      <AlertDialogDescription>
                        This deletes your account and every note, reminder, goal, project, conversation,
                        document, and setting associated with it — immediately and irreversibly, on every
                        device you're signed in on. Consider exporting your data first if you might want it later.
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <div className="py-2">
                      <Label htmlFor="delete-password" className="text-sm">Confirm your password</Label>
                      <Input
                        id="delete-password"
                        type="password"
                        value={deletePassword}
                        onChange={(e) => { setDeletePassword(e.target.value); setDeleteError(null); }}
                        placeholder="Your current password"
                        className="mt-1.5"
                        autoFocus
                      />
                      {deleteError && (
                        <p className="text-xs text-destructive mt-1.5">{deleteError}</p>
                      )}
                    </div>
                    <AlertDialogFooter>
                      <AlertDialogCancel disabled={deleting}>Cancel</AlertDialogCancel>
                      <AlertDialogAction
                        onClick={(e) => { e.preventDefault(); handleDelete(); }}
                        disabled={!deletePassword || deleting}
                        className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                      >
                        {deleting ? "Deleting…" : "Permanently delete my account"}
                      </AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              </Row>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

function SettingsPage() {
  const qc = useQueryClient();

  // ── ISSUE 10: Theme ────────────────────────────────────────────────────────
  const [theme, setTheme] = useState<Theme>(getStoredTheme);
  const handleTheme = useCallback((t: Theme) => {
    setTheme(t);
    applyTheme(t);
    if (isLive) preferencesApi.update({ theme: t }).catch(() => {});
  }, []);
  useEffect(() => { applyTheme(theme); }, []); // eslint-disable-line

  // Listen for system theme changes when "system" is active
  useEffect(() => {
    if (theme !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = (e: MediaQueryListEvent) => {
      document.documentElement.classList.toggle("dark", e.matches);
    };
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, [theme]);

  // ── Preferences ───────────────────────────────────────────────────────────
  const prefsQuery = useQuery({
    queryKey: ["preferences"],
    queryFn: preferencesApi.get,
    enabled: isLive,
    staleTime: 60_000,
  });
  const prefsMutation = useMutation({
    mutationFn: preferencesApi.update,
    onSuccess: (data) => { qc.setQueryData(["preferences"], data); toast.success("Preferences saved"); },
    onError: () => toast.error("Failed to save preferences"),
  });
  const prefs = prefsQuery.data ?? {};
  function setPref(key: string, value: boolean | string) {
    if (isLive) prefsMutation.mutate({ [key]: value } as Record<string, boolean | string>);
    else toast.info("Connect the backend to persist preferences");
  }

  // ── Phase 14: Timezone ────────────────────────────────────────────────────
  // Detected automatically from the browser. Shown read-only so users know
  // which timezone Athena is using for reminder times.
  const detectedTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const storedTimezone = (prefs as { timezone?: string }).timezone ?? detectedTimezone;
  function handleResyncTimezone() {
    if (!isLive) { toast.info("Connect the backend to sync timezone"); return; }
    prefsMutation.mutate({ timezone: detectedTimezone } as Record<string, string>, {
      onSuccess: () => {
        localStorage.setItem("athena-synced-tz", detectedTimezone);
        toast.success(`Timezone synced: ${detectedTimezone}`);
      },
    });
  }

  // ── Voice ──────────────────────────────────────────────────────────────────
  const { settings: voiceSettings, settingsLoaded, loadSettings, updateSettings, speak } = useVoice();
  const voicesQuery = useQuery({
    queryKey: ["voice-voices"],
    queryFn: voiceApi.voices,
    staleTime: Infinity,
  });
  const voices = voicesQuery.data ?? [];
  useEffect(() => { if (!settingsLoaded) loadSettings(); }, [settingsLoaded, loadSettings]);

  const handleVoiceUpdate = async (patch: Parameters<typeof updateSettings>[0]) => {
    await updateSettings(patch);
    toast.success("Voice settings saved");
  };

  const handlePreviewVoice = async () => {
    try {
      await speak("Hello, I'm Athena. Your voice preferences sound great!");
    } catch {
      toast.error("Voice preview failed — check backend connection");
    }
  };

  // ── Health ─────────────────────────────────────────────────────────────────
  const healthQuery = useQuery({
    queryKey: ["health"],
    queryFn: healthApi.get,
    enabled: isLive,
    refetchInterval: 30_000,
    staleTime: 10_000,
  });
  const health = healthQuery.data as Record<string, { status: string; response_ms?: number }> | undefined;

  const HEALTH_SERVICES = [
    { key: "backend",    label: "Backend API" },
    { key: "database",   label: "Database" },
    { key: "memory_api", label: "Memory API" },
    { key: "chat_api",   label: "Chat API" },
    { key: "upload_api", label: "Upload API" },
  ];

  return (
    <div className="max-w-5xl mx-auto w-full px-4 sm:px-6 py-10">
      <PageHeader title="Settings" description="Tune Athena to your workflow." />

      <div className="mt-6 grid md:grid-cols-2 gap-6 items-start">
        {/* ── ISSUE 10: Appearance ─────────────────────────────────────────── */}
        <Card>
          <CardHeader>
            <CardTitle>Appearance</CardTitle>
            <CardDescription>Theme is saved locally and persists across sessions.</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-3 gap-3">
            {(
              [
                { value: "light", label: "Light", Icon: Sun },
                { value: "dark",  label: "Dark",  Icon: Moon },
                { value: "system",label: "System",Icon: Monitor },
              ] as { value: Theme; label: string; Icon: React.ElementType }[]
            ).map(({ value, label, Icon }) => (
              <button
                key={value}
                onClick={() => handleTheme(value)}
                className={`flex flex-col items-center gap-2 rounded-xl border p-4 text-sm transition-all ${
                  theme === value
                    ? "border-primary bg-primary/5 text-primary font-medium"
                    : "border-border hover:border-primary/40 text-muted-foreground hover:text-foreground"
                }`}
              >
                <Icon className="size-5" />
                {label}
              </button>
            ))}
            </div>
          </CardContent>
        </Card>

        {/* ── Phase 20: Google Calendar ──────────────────────────────────── */}
        <CalendarSettingsSection />

        <PushSettingsSection />

        <ProactiveSettingsSection />

        <AccountSettingsSection />
      </div>

      {/* ── ISSUE 9 + 11: Voice OS Settings (cleaned up + wake word) ─────── */}
      <div className="mt-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Mic className="size-4 text-primary" />
            Voice
          </CardTitle>
          <CardDescription>Speech recognition and text-to-speech preferences.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          {/* Voice selection */}
          <div>
            <Label className="text-sm font-medium mb-2 block">Voice</Label>
            <div className="flex gap-2">
              <Select
                value={voiceSettings.voice_id}
                onValueChange={(v) => handleVoiceUpdate({ voice_id: v })}
              >
                <SelectTrigger className="flex-1">
                  <SelectValue placeholder="Select a voice…" />
                </SelectTrigger>
                <SelectContent>
                  {voices.length === 0 && (
                    <SelectItem value="en-US-AriaNeural">Aria (US, Female)</SelectItem>
                  )}
                  {voices.map((v) => (
                    <SelectItem key={v.id} value={v.id}>{v.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button variant="outline" size="icon" onClick={handlePreviewVoice} title="Preview voice">
                <Play className="size-4" />
              </Button>
            </div>
          </div>

          {/* Speed */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <Label className="text-sm font-normal">Speaking speed</Label>
              <span className="text-xs text-muted-foreground tabular-nums">{voiceSettings.speed.toFixed(1)}×</span>
            </div>
            <Slider
              min={50} max={200} step={10}
              value={[Math.round(voiceSettings.speed * 100)]}
              onValueChange={([v]) => handleVoiceUpdate({ speed: v / 100 })}
            />
            <div className="flex justify-between text-[10px] text-muted-foreground mt-1">
              <span>0.5×</span><span>1.0×</span><span>2.0×</span>
            </div>
          </div>

          {/* Volume */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <Label className="text-sm font-normal flex items-center gap-1.5">
                <Volume2 className="size-3.5" /> Volume
              </Label>
              <span className="text-xs text-muted-foreground tabular-nums">{Math.round(voiceSettings.volume * 100)}%</span>
            </div>
            <Slider
              min={10} max={100} step={5}
              value={[Math.round(voiceSettings.volume * 100)]}
              onValueChange={([v]) => handleVoiceUpdate({ volume: v / 100 })}
            />
          </div>

          <div className="border-t border-border pt-4 space-y-4">
            <Row label="Auto-play replies" description="Speak Athena's responses aloud.">
              <Switch checked={voiceSettings.auto_play} onCheckedChange={(v) => handleVoiceUpdate({ auto_play: v })} />
            </Row>
            <Row label="Voice Activity Detection" description="Auto-stop when you pause speaking.">
              <Switch checked={voiceSettings.vad_enabled} onCheckedChange={(v) => handleVoiceUpdate({ vad_enabled: v })} />
            </Row>
            <Row label="Continuous mode" description="Keep listening after each reply for hands-free chat.">
              <Switch checked={voiceSettings.continuous_mode} onCheckedChange={(v) => handleVoiceUpdate({ continuous_mode: v })} />
            </Row>

            {/* ISSUE 11: Wake word */}
            <Row label='Wake word' description='Say the phrase to activate voice without pressing a button.'>
              <Switch
                checked={voiceSettings.wake_word_enabled}
                onCheckedChange={(v) => handleVoiceUpdate({ wake_word_enabled: v })}
              />
            </Row>
            {voiceSettings.wake_word_enabled && (
              <div>
                <Label className="text-xs text-muted-foreground mb-1 block">Wake phrase</Label>
                <Input
                  value={voiceSettings.wake_word}
                  onChange={(e) => handleVoiceUpdate({ wake_word: e.target.value })}
                  placeholder="Hey Athena"
                  className="max-w-xs text-sm"
                />
                <p className="text-xs text-muted-foreground mt-1">
                  Works in Chat when Voice Mode is open. Uses browser's Web Speech API.
                </p>
              </div>
            )}
          </div>
        </CardContent>
      </Card>
      </div>

      <div className="mt-6 grid md:grid-cols-2 gap-6 items-start">
        {/* ── ISSUE 9: Simplified notifications ────────────────────────────── */}
        <Card>
          <CardHeader><CardTitle>Notifications</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <Row label="Reminder alerts" description="Get notified when a reminder is due.">
              <Switch
                checked={prefs.notifications ?? true}
                onCheckedChange={(v) => setPref("notifications", v)}
              />
            </Row>
          </CardContent>
        </Card>

        {/* ── Phase 14: Timezone ───────────────────────────────────────────── */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Globe className="size-4 text-primary" />
            Timezone
          </CardTitle>
          <CardDescription>
            Athena uses your timezone to schedule reminders at the correct local time.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between gap-4 p-3 rounded-lg border border-border bg-muted/40">
            <div className="min-w-0">
              <div className="text-sm font-medium">Current timezone</div>
              <div className="text-xs text-muted-foreground mt-0.5 font-mono">
                {storedTimezone}
              </div>
              {storedTimezone !== detectedTimezone && (
                <div className="text-xs text-amber-600 mt-1">
                  ⚠ Browser detected: {detectedTimezone} — click Sync to update
                </div>
              )}
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={handleResyncTimezone}
              disabled={prefsMutation.isPending}
            >
              <RefreshCw className={`size-3.5 mr-1.5 ${prefsMutation.isPending ? "animate-spin" : ""}`} />
              Sync
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            Auto-detected from your browser on login. Click Sync if you've changed location or timezone.
          </p>
        </CardContent>
      </Card>

      {/* ── ISSUE 9: Simplified display preferences ───────────────────────── */}
      <Card>
        <CardHeader>
          <CardTitle>Display</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <Row label="Show timestamps" description="Display times on messages and notes.">
            <Switch
              checked={prefs.show_timestamps ?? true}
              onCheckedChange={(v) => setPref("show_timestamps", v)}
            />
          </Row>
          <Row label="Compact view" description="Reduce padding in list views.">
            <Switch
              checked={prefs.compact_view ?? false}
              onCheckedChange={(v) => setPref("compact_view", v)}
            />
          </Row>
        </CardContent>
      </Card>

      {/* ── Feature Toggles ───────────────────────────────────────────────── */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Zap className="size-4 text-amber-500" />
            Features
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <Row label="Memory" description="Long-term personalisation and conversation history.">
            <Switch
              checked={prefs.feature_memory ?? true}
              onCheckedChange={(v) => setPref("feature_memory", v)}
            />
          </Row>
          <Row label="Analytics" description="Usage charts and statistics.">
            <Switch
              checked={prefs.feature_analytics ?? true}
              onCheckedChange={(v) => setPref("feature_analytics", v)}
            />
          </Row>
        </CardContent>
      </Card>
      </div>

      {/* ── API Health ────────────────────────────────────────────────────── */}
      <div className="mt-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Activity className="size-4 text-primary" />
            API Health
          </CardTitle>
          <CardDescription>Live status of backend services.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-center justify-between gap-4 p-3 rounded-lg border border-border bg-muted/40">
            <div className="min-w-0">
              <div className="text-sm font-medium">Backend</div>
              <div className="text-xs text-muted-foreground truncate">
                {API_BASE_URL || "Not configured — using mock data"}
              </div>
            </div>
            {isLive ? (
              <Badge className="bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400 border-emerald-200 dark:border-emerald-800 gap-1">
                <CheckCircle2 className="size-3" /> Live
              </Badge>
            ) : (
              <Badge variant="secondary" className="gap-1">
                <AlertCircle className="size-3" /> Mock
              </Badge>
            )}
          </div>

          {isLive && (
            <>
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs text-muted-foreground">Services</span>
                <Button
                  variant="ghost" size="sm" className="h-6 px-2 text-xs"
                  onClick={() => healthQuery.refetch()}
                  disabled={healthQuery.isFetching}
                >
                  <RefreshCw className={`size-3 mr-1 ${healthQuery.isFetching ? "animate-spin" : ""}`} />
                  Refresh
                </Button>
              </div>
              <div className="space-y-2">
                {healthQuery.isLoading
                  ? Array.from({ length: 4 }).map((_, i) => (
                      <div key={i} className="h-10 rounded-lg bg-muted animate-pulse" />
                    ))
                  : healthQuery.isError
                  ? <p className="text-xs text-muted-foreground">Health check unavailable.</p>
                  : HEALTH_SERVICES.map(({ key, label }) => {
                      const svc = health?.[key];
                      return (
                        <div key={key} className="flex items-center justify-between p-2.5 rounded-lg border border-border bg-card">
                          <span className="text-sm">{label}</span>
                          <div className="flex items-center gap-2">
                            {svc?.response_ms != null && (
                              <span className="text-xs text-muted-foreground">{svc.response_ms} ms</span>
                            )}
                            <HealthBadge status={svc?.status ?? "unknown"} />
                          </div>
                        </div>
                      );
                    })}
              </div>
            </>
          )}
        </CardContent>
      </Card>
      </div>
    </div>
  );
}