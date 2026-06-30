import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import { AppSidebar } from "./app-sidebar";
import { CommandPalette } from "./command-palette";
import { MobileTopbar } from "./mobile-topbar";
import { useReminderNotifications } from "@/hooks/use-reminder-notifications";
import { useWakeWord } from "@/hooks/use-wake-word";
import { useVoiceActivation } from "@/stores/voice-activation";
import { voiceApi, type VoiceSettings } from "@/lib/voice-api";
import { useAuth } from "@/stores/auth";
import { toast } from "sonner";
import { TimerProvider } from "./timer-provider";

function NotificationProvider() {
  // Phase 16: polls for due reminders and shows browser notifications
  useReminderNotifications();
  return null;
}

/**
 * Phase 18 fix — app-wide wake word.
 *
 * Previously wake word only ran INSIDE VoiceDialog, gated on the dialog
 * already being open — meaning it could never actually open the dialog
 * for you, defeating the entire point of a wake word. Real assistants
 * (Alexa, Siri) listen continuously regardless of what screen you're on.
 *
 * This component loads the user's voice settings once, and if
 * wake_word_enabled is true, runs useWakeWord continuously for the
 * entire app session (any route, not just while voice mode is open).
 * On detection, it calls useVoiceActivation.triggerWake() — the home
 * page's VoiceDialog watches that store and opens + starts listening
 * in response.
 */
function GlobalWakeWordProvider() {
  const { user, initializing } = useAuth();
  const [settings, setSettings] = useState<VoiceSettings | null>(null);
  const triggerWake = useVoiceActivation((s) => s.triggerWake);

  useEffect(() => {
    if (initializing || !user) return;
    voiceApi.getSettings().then(setSettings).catch(() => {});
  }, [initializing, user]);

  useWakeWord({
    phrase: settings?.wake_word || "Hey Athena",
    enabled: !!settings?.wake_word_enabled,
    paused: false, // app-wide listener is never "already in conversation" at this level
    onWakeWord: () => {
      toast.info(`Wake word detected: "${settings?.wake_word || "Hey Athena"}"`);
      triggerWake();
    },
  });

  return null;
}

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-svh w-full bg-background text-foreground">
      <NotificationProvider />
      <GlobalWakeWordProvider />
      <TimerProvider />
      <AppSidebar />
      <div className="flex-1 min-w-0 flex flex-col">
        <MobileTopbar />
        <main className="flex-1 min-w-0 relative">{children}</main>
      </div>
      <CommandPalette />
    </div>
  );
}
