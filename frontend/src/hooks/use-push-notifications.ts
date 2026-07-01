/**
 * frontend/src/hooks/use-push-notifications.ts  —  Phase 21
 *
 * Owns the full Web Push subscription lifecycle on the client:
 *   1. Register public/sw.js (idempotent — no-op if already registered)
 *   2. Fetch the backend's VAPID public key
 *   3. Ask the browser for Notification permission (only when the user
 *      explicitly opts in via Settings — never auto-prompted on load,
 *      since an unsolicited permission prompt is exactly the kind of
 *      thing that gets a whole origin's notification permission
 *      permanently denied by an annoyed user)
 *   4. PushManager.subscribe() and POST the subscription to the backend
 *
 * Also silently re-syncs an *already-granted* subscription on mount
 * (no new prompt — permission was already granted in a previous
 * session) so a user who granted permission once stays subscribed
 * after logging in again on the same device, even if the backend's
 * copy of the subscription's user_id is stale.
 */
import { useCallback, useEffect, useState } from "react";
import { pushApi } from "@/lib/push-api";
import { isLive } from "@/lib/api";

export type PushPermissionState = "unsupported" | "default" | "granted" | "denied";

interface UsePushNotificationsResult {
  permission: PushPermissionState;
  subscribed: boolean;
  loading: boolean;
  error: string | null;
  subscribe: () => Promise<void>;
  unsubscribe: () => Promise<void>;
}

function urlBase64ToUint8Array(base64Url: string): Uint8Array {
  const padding = "=".repeat((4 - (base64Url.length % 4)) % 4);
  const base64 = (base64Url + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = atob(base64);
  const outputArray = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; i++) {
    outputArray[i] = rawData.charCodeAt(i);
  }
  return outputArray;
}

function isSupported(): boolean {
  return (
    typeof window !== "undefined" &&
    "serviceWorker" in navigator &&
    "PushManager" in window &&
    "Notification" in window
  );
}

async function registerServiceWorker(): Promise<ServiceWorkerRegistration | null> {
  if (!isSupported()) return null;
  try {
    return await navigator.serviceWorker.register("/sw.js");
  } catch {
    return null;
  }
}

export function usePushNotifications(): UsePushNotificationsResult {
  const [permission, setPermission] = useState<PushPermissionState>(
    isSupported() ? (Notification.permission as PushPermissionState) : "unsupported"
  );
  const [subscribed, setSubscribed] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Silent re-sync: if permission was already granted in a past session,
  // make sure the browser subscription and the backend row agree —
  // without prompting again.
  useEffect(() => {
    if (!isLive || !isSupported() || Notification.permission !== "granted") return;

    let cancelled = false;
    (async () => {
      const reg = await registerServiceWorker();
      if (!reg || cancelled) return;
      const existing = await reg.pushManager.getSubscription();
      if (existing && !cancelled) {
        try {
          await pushApi.subscribe(existing.toJSON() as PushSubscriptionJSON);
          if (!cancelled) setSubscribed(true);
        } catch {
          // Backend unreachable or not configured — leave subscribed
          // state as-is, next explicit action will surface the error.
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  const subscribe = useCallback(async () => {
    if (!isSupported()) {
      setError("This browser doesn't support push notifications.");
      return;
    }
    if (!isLive) {
      setError("Connect the backend to enable push notifications.");
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const reg = await registerServiceWorker();
      if (!reg) throw new Error("Service worker registration failed");

      const perm = await Notification.requestPermission();
      setPermission(perm as PushPermissionState);
      if (perm !== "granted") {
        throw new Error(perm === "denied" ? "Notification permission denied" : "Permission dismissed");
      }

      const { publicKey } = await pushApi.vapidPublicKey();

      let sub = await reg.pushManager.getSubscription();
      if (!sub) {
        sub = await reg.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: urlBase64ToUint8Array(publicKey),
        });
      }

      await pushApi.subscribe(sub.toJSON() as PushSubscriptionJSON);
      setSubscribed(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to enable push notifications");
    } finally {
      setLoading(false);
    }
  }, []);

  const unsubscribe = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const reg = await navigator.serviceWorker.getRegistration("/sw.js");
      const sub = await reg?.pushManager.getSubscription();
      if (sub) {
        await pushApi.unsubscribe(sub.endpoint).catch(() => {});
        await sub.unsubscribe();
      }
      setSubscribed(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to disable push notifications");
    } finally {
      setLoading(false);
    }
  }, []);

  return { permission, subscribed, loading, error, subscribe, unsubscribe };
}
