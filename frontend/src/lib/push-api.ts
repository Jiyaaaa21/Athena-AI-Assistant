/**
 * Phase 21 — Push notifications API client
 *
 * Extends the existing api.ts pattern with push-subscription endpoints.
 * Import from here; api.ts is left unmodified.
 */
import { request, isLive } from "./api";

export interface PushStatus {
  configured: boolean;
  deviceCount: number;
}

export const pushApi = {
  vapidPublicKey: async (): Promise<{ publicKey: string }> =>
    request<{ publicKey: string }>("/push/vapid-public-key"),

  subscribe: async (subscription: PushSubscriptionJSON): Promise<{ subscribed: true }> =>
    request<{ subscribed: true }>("/push/subscribe", {
      method: "POST",
      body: JSON.stringify({
        endpoint: subscription.endpoint,
        keys: subscription.keys,
        user_agent: navigator.userAgent,
      }),
    }),

  unsubscribe: async (endpoint: string): Promise<{ unsubscribed: boolean }> =>
    request<{ unsubscribed: boolean }>(`/push/unsubscribe?endpoint=${encodeURIComponent(endpoint)}`, {
      method: "DELETE",
    }),

  status: async (): Promise<PushStatus> =>
    isLive ? request<PushStatus>("/push/status") : { configured: false, deviceCount: 0 },

  test: async (): Promise<{ sent: number }> =>
    request<{ sent: number }>("/push/test", { method: "POST" }),
};
