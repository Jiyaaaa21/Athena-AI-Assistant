/**
 * useReminderNotifications  —  Phase 16
 *
 * Polls GET /reminders/due every 30 seconds and shows browser push
 * notifications for any reminders that have fired on the backend.
 *
 * Requests notification permission on first use.
 * Falls back to an in-app toast if permission is denied.
 */

import { useEffect, useRef, useCallback } from "react";
import { toast } from "sonner";
import { API_BASE_URL, isLive } from "@/lib/api";
import { getAccessToken } from "@/stores/auth";
import { useAuth } from "@/stores/auth";

const POLL_INTERVAL_MS = 30_000;

interface DueReminder {
  id: number;
  title: string;
  due_time: string;
  priority: string;
}

async function fetchDueReminders(): Promise<DueReminder[]> {
  const tok = getAccessToken();
  const res = await fetch(`${API_BASE_URL}/reminders/due`, {
    headers: tok ? { Authorization: `Bearer ${tok}` } : {},
  });
  if (!res.ok) return [];
  const data = await res.json() as { due: DueReminder[] };
  return data.due ?? [];
}

function showNotification(reminder: DueReminder) {
  const title = `⏰ Reminder: ${reminder.title}`;
  const body = reminder.due_time
    ? `Due: ${reminder.due_time}`
    : "Your reminder is due now.";

  // Try browser notification first
  if ("Notification" in window && Notification.permission === "granted") {
    try {
      const n = new Notification(title, {
        body,
        icon: "/favicon.ico",
        tag: `athena-reminder-${reminder.id}`,
        requireInteraction: true,
      });
      n.onclick = () => {
        window.focus();
        n.close();
      };
      return;
    } catch {
      // Fall through to toast
    }
  }

  // In-app toast fallback
  toast(title, {
    description: body,
    duration: 10_000,
    action: {
      label: "Dismiss",
      onClick: () => {},
    },
  });
}

async function requestNotificationPermission(): Promise<boolean> {
  if (!("Notification" in window)) return false;
  if (Notification.permission === "granted") return true;
  if (Notification.permission === "denied") return false;
  const result = await Notification.requestPermission();
  return result === "granted";
}

export function useReminderNotifications() {
  const { user } = useAuth();
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const permissionRequestedRef = useRef(false);

  const poll = useCallback(async () => {
    if (!isLive || !user) return;
    try {
      const due = await fetchDueReminders();
      for (const reminder of due) {
        showNotification(reminder);
      }
    } catch {
      // Silent fail — don't disrupt the UI for polling errors
    }
  }, [user]);

  useEffect(() => {
    if (!user || !isLive) return;

    // Request permission once
    if (!permissionRequestedRef.current) {
      permissionRequestedRef.current = true;
      requestNotificationPermission();
    }

    // Initial poll
    poll();

    // Set up interval
    intervalRef.current = setInterval(poll, POLL_INTERVAL_MS);

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [user, poll]);
}
