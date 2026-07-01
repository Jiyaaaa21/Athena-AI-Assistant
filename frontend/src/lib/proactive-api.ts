/**
 * Phase 23 — Proactive intelligence API client
 *
 * Follows the same pattern as lib/push-api.ts: a thin wrapper around the
 * shared request() helper, kept in its own file rather than touching
 * api.ts directly.
 */
import { request, isLive } from "./api";

export interface ProactiveInsight {
  id: number;
  kind: "calendar_soon" | "reminder_upcoming" | "goal_stale" | "pattern" | "general";
  message: string;
  delivered: boolean;
  dismissed: boolean;
  createdAt: string;
}

export interface TriggerResult {
  generated: boolean;
  insight?: ProactiveInsight;
  reason?: string;
}

export const proactiveApi = {
  list: async (): Promise<ProactiveInsight[]> =>
    isLive ? request<ProactiveInsight[]>("/proactive/insights") : [],

  dismiss: async (id: number): Promise<{ dismissed: boolean }> =>
    request<{ dismissed: boolean }>(`/proactive/insights/${id}/dismiss`, {
      method: "POST",
    }),

  trigger: async (): Promise<TriggerResult> =>
    request<TriggerResult>("/proactive/trigger", { method: "POST" }),
};