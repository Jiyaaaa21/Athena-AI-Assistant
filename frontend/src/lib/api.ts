/**
 * Athena API client — Phase 7: Knowledge Management additions
 *
 * All existing exports are preserved unchanged.
 * Phase 6 additions: memoryApi.update(), .timeline(), .topics(), .preferences()
 * Phase 7 additions: searchApi (global search + document chunks)
 */
import * as mock from "./mock";
import { getAccessToken } from "@/stores/auth";

export const API_BASE_URL =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "";

export const isLive = Boolean(API_BASE_URL);

async function extractErrorMessage(res: Response): Promise<string> {
  try {
    const data = await res.clone().json();
    if (typeof data?.detail === "string") return data.detail;
    if (typeof data?.message === "string") return data.message;
  } catch {
    // not JSON
  }
  return `${res.status} ${res.statusText}`;
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  if (!API_BASE_URL) throw new Error("API_BASE_URL not configured");

  // Phase 16 fix: wait for auth restoration to finish before firing any
  // authenticated request. Multiple components (BriefingWidget, voice
  // settings, reminder polling, memory page) were firing their first
  // fetch on mount, racing the auth store's localStorage restoration.
  // Whichever request won that race went out with no Authorization
  // header at all and got a guaranteed 401 — not a token-expiry case,
  // so the existing refresh-on-401 logic below couldn't help (there was
  // never a token to refresh). Centralizing the wait here fixes every
  // call site at once instead of patching each component individually.
  const isAuthRoute = path.startsWith("/auth/");
  if (!isAuthRoute) {
    try {
      const { useAuth } = await import("@/stores/auth");
      let waited = 0;
      while (useAuth.getState().initializing && waited < 5000) {
        await new Promise((r) => setTimeout(r, 50));
        waited += 50;
      }
    } catch {
      // auth store unavailable — proceed anyway, normal 401 handling below
    }
  }

  const token = getAccessToken();
  const authHeader: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {};
  const res = await fetch(`${API_BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json", ...authHeader, ...(init?.headers ?? {}) },
    ...init,
  });

  // Phase 15: Auto-refresh on 401 and retry once
  if (res.status === 401) {
    try {
      const { useAuth } = await import("@/stores/auth");
      const ok = await useAuth.getState().refreshTokens();
      if (ok) {
        const newToken = getAccessToken();
        const retryHeaders: Record<string, string> = newToken
          ? { Authorization: `Bearer ${newToken}` }
          : {};
        const retry = await fetch(`${API_BASE_URL}${path}`, {
          headers: { "Content-Type": "application/json", ...retryHeaders, ...(init?.headers ?? {}) },
          ...init,
        });
        if (!retry.ok) throw new Error(await extractErrorMessage(retry));
        return retry.json() as Promise<T>;
      }
    } catch {
      // Refresh failed — fall through to original error
    }
  }

  if (!res.ok) throw new Error(await extractErrorMessage(res));
  return res.json() as Promise<T>;
}

function uploadWithProgress<T>(
  url: string,
  formData: FormData,
  onProgress?: (pct: number) => void,
): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    const _tok = getAccessToken();
    if (_tok) xhr.setRequestHeader("Authorization", `Bearer ${_tok}`);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) {
        onProgress(Math.round((e.loaded / e.total) * 100));
      }
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try { resolve(JSON.parse(xhr.responseText) as T); } catch { resolve(null as T); }
      } else {
        let message = `${xhr.status} ${xhr.statusText}`;
        try {
          const data = JSON.parse(xhr.responseText);
          if (typeof data?.detail === "string") message = data.detail;
        } catch { /* ignore */ }
        reject(new Error(message || "Upload failed"));
      }
    };
    xhr.onerror = () => reject(new Error("Upload failed — network error"));
    xhr.send(formData);
  });
}

function delay<T>(value: T, ms = 350): Promise<T> {
  return new Promise((r) => setTimeout(() => r(value), ms));
}

/* ---------- Chat ---------- */
export const chatApi = {
  send: async (
    message: string,
    history: { role: string; content: string }[],
    convId?: number | null,
  ) => {
    if (isLive) {
      const params = new URLSearchParams({ message });
      if (convId) params.set("conv_id", String(convId));
      return request<{ reply: string; sources?: mock.Source[]; conversationId: number }>(
        `/chat?${params.toString()}`,
      );
    }
    return delay(
      { ...mock.fakeAssistantReply(message, history), conversationId: null as unknown as number },
      600,
    );
  },
  history: async (): Promise<mock.ChatMessage[]> => {
    if (!isLive) return [];
    const data = await request<{
      messages: { id: number; role: "user" | "assistant"; content: string; createdAt: string | null }[];
    }>("/memory");
    return data.messages.map((m) => ({
      id: String(m.id),
      role: m.role,
      content: m.content,
      createdAt: m.createdAt,
    }));
  },
};

/* ---------- Phase 10: Streaming Chat API ---------- */

export type StreamEvent =
  | { type: "status"; text: string; agent?: string | null }
  | { type: "token";  text: string }
  | { type: "done";   conversationId: number; sources: mock.Source[]; agentName?: string; steps?: string[] }
  | { type: "error";  text: string };

export type StreamCallbacks = {
  onStatus?: (text: string, agent?: string | null) => void;
  onToken:   (text: string) => void;
  onDone:    (conversationId: number, sources: mock.Source[], agentName?: string, steps?: string[]) => void;
  onError?:  (text: string) => void;
};

/**
 * Phase 10: SSE streaming send.
 *
 * Opens a POST /chat/stream SSE connection, calls the provided callbacks
 * for each event type, and returns an abort function the caller can invoke
 * to cancel mid-stream via POST /chat/cancel.
 *
 * Phase 15 fix: token throttling. Groq delivers all tokens in < 200ms
 * as a burst. Without throttling, the entire response renders instantly.
 * We queue tokens and release them at 18ms intervals (≈ 55 tokens/sec)
 * which matches Claude's perceived typing speed.
 *
 * Falls back gracefully to the non-streaming send() in mock/offline mode.
 */
export function chatStream(
  message: string,
  convId: number | null | undefined,
  callbacks: StreamCallbacks,
  imageDataUri?: string | null,
): () => void {
  if (!isLive) {
    // Offline / mock: simulate streaming with a timeout
    const t = setTimeout(async () => {
      const { reply, sources } = mock.fakeAssistantReply(message, []);
      callbacks.onStatus?.("Athena is thinking…");
      callbacks.onToken(reply);
      callbacks.onDone(0, sources ?? []);
    }, 600);
    return () => clearTimeout(t);
  }

  const streamId = crypto.randomUUID();
  const controller = new AbortController();
  let cancelled = false;

  // ── Token throttle queue ─────────────────────────────────────────────────
  // Tokens arrive in bursts from Groq. We release them at a natural pace
  // so the response feels like it's being typed, not dumped all at once.
  const TOKEN_INTERVAL_MS = 18;   // ~55 tokens/sec  ≈ Claude's feel
  const tokenQueue: string[] = [];
  let drainTimer: ReturnType<typeof setInterval> | null = null;
  let streamDonePayload: { conversationId: number; sources: mock.Source[]; agentName?: string; steps?: string[] } | null = null;

  function startDrain() {
    if (drainTimer !== null) return;
    drainTimer = setInterval(() => {
      if (cancelled) { stopDrain(); return; }
      const token = tokenQueue.shift();
      if (token !== undefined) {
        callbacks.onToken(token);
      } else if (streamDonePayload) {
        // All tokens flushed — fire done
        stopDrain();
        callbacks.onDone(
          streamDonePayload.conversationId,
          streamDonePayload.sources,
          streamDonePayload.agentName,
          streamDonePayload.steps,
        );
        streamDonePayload = null;
      }
    }, TOKEN_INTERVAL_MS);
  }

  function stopDrain() {
    if (drainTimer !== null) { clearInterval(drainTimer); drainTimer = null; }
  }

  (async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/chat/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Stream-Id": streamId,
          ...(getAccessToken() ? { Authorization: `Bearer ${getAccessToken()}` } : {}),
        },
        body: JSON.stringify({
          message,
          conv_id: convId ?? null,
          ...(imageDataUri ? { image_data_uri: imageDataUri } : {}),
        }),
        signal: controller.signal,
      });

      if (!res.ok) {
        const err = await res.text();
        callbacks.onError?.(err || "Stream request failed");
        return;
      }

      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        // SSE lines arrive as "data: {...}\n\n"
        const parts = buffer.split("\n\n");
        buffer = parts.pop() ?? "";

        for (const part of parts) {
          const line = part.replace(/^data:\s*/, "").trim();
          if (!line) continue;
          try {
            const event: StreamEvent = JSON.parse(line);
            if (event.type === "status") callbacks.onStatus?.(event.text, (event as any).agent);
            else if (event.type === "token") {
              // Split token into individual characters for smoother rendering
              // (Groq sends word-sized chunks; we want char-level flow)
              for (const char of event.text) {
                tokenQueue.push(char);
              }
              startDrain();
            }
            else if (event.type === "done") {
              // Don't fire done until queue is drained
              streamDonePayload = {
                conversationId: event.conversationId,
                sources: event.sources,
                agentName: event.agentName,
                steps: event.steps,
              };
              // If queue is already empty, startDrain interval will fire done on next tick
              startDrain();
            }
            else if (event.type === "error") { stopDrain(); callbacks.onError?.(event.text); }
          } catch {
            // malformed chunk — skip
          }
        }
      }
    } catch (err: unknown) {
      if ((err as Error)?.name !== "AbortError") {
        callbacks.onError?.((err as Error)?.message ?? "Stream failed");
      }
    }
  })();

  return () => {
    cancelled = true;
    stopDrain();
    controller.abort();
    // Fire-and-forget cancel signal to backend
    fetch(`${API_BASE_URL}/chat/cancel`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(getAccessToken() ? { Authorization: `Bearer ${getAccessToken()}` } : {}) },
      body: JSON.stringify({ stream_id: streamId }),
    }).catch(() => {});
  };
}


/* ---------- Documents ---------- */
export const documentsApi = {
  list: async () => {
    if (isLive) return request<mock.DocItem[]>("/documents");
    return delay(mock.documents());
  },
  upload: async (file: File, onProgress?: (pct: number) => void) => {
    if (isLive) {
      const fd = new FormData();
      fd.append("file", file);
      return uploadWithProgress<mock.DocItem>(`${API_BASE_URL}/upload-document`, fd, onProgress);
    }
    if (onProgress) {
      for (const pct of [20, 45, 70, 100]) { await delay(undefined, 120); onProgress(pct); }
    }
    return delay({
      id: crypto.randomUUID(), name: file.name, size: file.size,
      uploadedAt: new Date().toISOString(), status: "processed" as const,
      pages: Math.max(1, Math.round(file.size / 50_000)),
      chunkCount: Math.max(1, Math.round(file.size / 1_200)),
    });
  },
  remove: async (id: string) => {
    if (isLive) return request<{ ok: true }>(`/documents/${id}`, { method: "DELETE" });
    return delay({ ok: true as const });
  },
  // Phase 25 fix: an <iframe src="..."> is a plain browser navigation and
  // can't send an Authorization header, so the preview iframe can't load
  // /documents/{id}/file directly (that route requires a JWT). This mints
  // a short-lived, single-purpose token via an authenticated POST, which
  // the iframe can then use against the public /documents/file/{token}
  // route instead — the token itself is the auth for that request.
  fileToken: async (id: string) => {
    if (isLive) return request<{ token: string }>(`/documents/${id}/file-token`, { method: "POST" });
    return delay({ token: "mock" });
  },
};

/* ---------- Notes ---------- */
export const notesApi = {
  list: async () => isLive ? request<mock.Note[]>("/notes") : delay(mock.notes()),
  create: async (n: Omit<mock.Note, "id" | "createdAt">) =>
    isLive
      ? request<mock.Note>("/notes", { method: "POST", body: JSON.stringify(n) })
      : delay({ ...n, id: crypto.randomUUID(), createdAt: new Date().toISOString() }),
  update: async (n: mock.Note) =>
    isLive
      ? request<mock.Note>(`/notes/${n.id}`, { method: "PUT", body: JSON.stringify(n) })
      : delay(n),
  remove: async (id: string) =>
    isLive
      ? request<{ ok: true }>(`/notes/${id}`, { method: "DELETE" })
      : delay({ ok: true as const }),
};

/* ---------- Reminders ---------- */
export const remindersApi = {
  list: async () =>
    isLive ? request<mock.Reminder[]>("/reminders") : delay(mock.reminders()),
  create: async (r: Omit<mock.Reminder, "id">) =>
    isLive
      ? request<mock.Reminder>("/reminders", { method: "POST", body: JSON.stringify(r) })
      : delay({ ...r, id: crypto.randomUUID() }),
  toggle: async (id: string, done: boolean) =>
    isLive
      ? request<{ ok: true }>(`/reminders/${id}`, { method: "PATCH", body: JSON.stringify({ done }) })
      : delay({ ok: true as const }),
  update: async (r: mock.Reminder) =>
    isLive
      ? request<mock.Reminder>(`/reminders/${r.id}`, { method: "PUT", body: JSON.stringify(r) })
      : delay(r),
  remove: async (id: string) =>
    isLive
      ? request<{ ok: true }>(`/reminders/${id}`, { method: "DELETE" })
      : delay({ ok: true as const }),
};

/* ---------- News / Weather ---------- */
export const newsApi = {
  list: async (category?: string) =>
    isLive
      ? request<mock.NewsItem[]>(`/news${category ? `?category=${category}` : ""}`)
      : delay(mock.news(category)),
};

export const weatherApi = {
  get: async (city: string) =>
    isLive
      ? request<mock.Weather>(`/weather?city=${encodeURIComponent(city)}`)
      : delay(mock.weather(city)),
};

/* ---------- Memory ---------- */

export interface EnrichedMemory extends mock.Memory {
  importance: "low" | "medium" | "high" | "critical";
  importance_score: number;
  createdAt?: string | null;
}

export interface MemoryStats {
  total: number;
  by_category: Record<string, number>;
  by_importance: { low: number; medium: number; high: number; critical: number };
  by_role: { user: number; assistant: number };
  oldest: string | null;
  newest: string | null;
  most_active_category: string | null;
}

export interface MemoryTimelinePeriod {
  period: "Today" | "This Week" | "This Month" | "Older";
  entries: EnrichedMemory[];
  count: number;
}

export interface MemoryTopic {
  topic: string;
  count: number;
  type: "phrase" | "keyword";
}

export interface MemoryPreferences {
  top_categories: { category: string; count: number; pct: number }[];
  active_hours: { hour: number; count: number }[];
  peak_hour: number | null;
  most_active_days: { day: string; count: number }[];
  frequently_discussed_topics: MemoryTopic[];
  suggestions: { type: string; title: string; detail: string; icon: string }[];
  total_user_messages: number;
}

export const memoryApi = {
  list: async (): Promise<EnrichedMemory[]> => {
    if (isLive) {
      const data = await request<{
        messages: {
          id: number; role: "user" | "assistant"; content: string;
          category: string; importance: "low" | "medium" | "high" | "critical";
          importance_score: number; createdAt: string | null;
        }[];
      }>("/memory");
      return data.messages.slice().reverse().map((m) => ({
        id: String(m.id), label: m.content, role: m.role,
        category: m.category, importance: m.importance,
        importance_score: m.importance_score, createdAt: m.createdAt,
      }));
    }
    const base = await delay(mock.memories());
    return base.map((m) => ({
      ...m, importance: "medium" as const, importance_score: 5, createdAt: null,
    }));
  },

  stats: async (): Promise<MemoryStats> => {
    if (isLive) return request<MemoryStats>("/memory/stats");
    return delay({
      total: 0, by_category: {}, by_importance: { low: 0, medium: 0, high: 0, critical: 0 },
      by_role: { user: 0, assistant: 0 }, oldest: null, newest: null, most_active_category: null,
    });
  },

  search: async (params: {
    q?: string; category?: string; importance?: string;
    date_from?: string; date_to?: string; role?: string;
  }) => {
    if (isLive) {
      const qs = new URLSearchParams(
        Object.entries(params).filter(([, v]) => v != null) as [string, string][]
      ).toString();
      return request<{ messages: EnrichedMemory[]; total: number }>(
        `/memory/search${qs ? `?${qs}` : ""}`
      );
    }
    return delay({ messages: [] as EnrichedMemory[], total: 0 });
  },

  // Phase 6: full mock implementation preserved
  timeline: async (): Promise<{ timeline: MemoryTimelinePeriod[] }> => {
    if (isLive) return request<{ timeline: MemoryTimelinePeriod[] }>("/memory/timeline");
    const now = Date.now();
    return delay({
      timeline: [
        {
          period: "Today" as const,
          count: 1,
          entries: [{
            id: "mock-1", label: "Working on Athena Memory OS phase.", role: "user",
            category: "Projects", importance: "high" as const, importance_score: 7,
            createdAt: new Date(now - 3600000).toISOString(),
          }],
        },
        {
          period: "This Week" as const,
          count: 2,
          entries: mock.memories().slice(0, 2).map((m) => ({
            ...m, importance: "medium" as const, importance_score: 4,
            createdAt: new Date(now - 86400000 * 2).toISOString(),
          })),
        },
        {
          period: "Older" as const,
          count: 3,
          entries: mock.memories().slice(2).map((m) => ({
            ...m, importance: "low" as const, importance_score: 2,
            createdAt: new Date(now - 86400000 * 14).toISOString(),
          })),
        },
      ],
    });
  },

  // Phase 6: full mock implementation preserved
  topics: async (): Promise<{ topics: MemoryTopic[]; total_analyzed: number }> => {
    if (isLive) return request("/memory/topics");
    return delay({
      topics: [
        { topic: "athena roadmap", count: 8, type: "phrase" as const },
        { topic: "memory system", count: 6, type: "phrase" as const },
        { topic: "product", count: 5, type: "keyword" as const },
        { topic: "rag search", count: 4, type: "phrase" as const },
        { topic: "workflow", count: 4, type: "keyword" as const },
        { topic: "documents", count: 3, type: "keyword" as const },
      ],
      total_analyzed: 42,
    });
  },

  // Phase 6: full mock implementation preserved
  preferences: async (): Promise<MemoryPreferences> => {
    if (isLive) return request<MemoryPreferences>("/memory/preferences");
    const hourData = Array.from({ length: 24 }, (_, h) => ({
      hour: h,
      count: (h >= 9 && h <= 17) ? Math.round(2 + Math.random() * 6) : Math.round(Math.random() * 2),
    }));
    return delay({
      top_categories: [
        { category: "Projects", count: 18, pct: 42.9 },
        { category: "Work", count: 12, pct: 28.6 },
        { category: "Learning", count: 7, pct: 16.7 },
        { category: "Preferences", count: 5, pct: 11.9 },
      ],
      active_hours: hourData,
      peak_hour: 10,
      most_active_days: [
        { day: "Tuesday", count: 12 },
        { day: "Wednesday", count: 10 },
        { day: "Monday", count: 8 },
      ],
      frequently_discussed_topics: [
        { topic: "athena roadmap", count: 8, type: "phrase" as const },
        { topic: "memory system", count: 6, type: "phrase" as const },
        { topic: "product", count: 5, type: "keyword" as const },
      ],
      suggestions: [
        { type: "memory", title: "Review important memory", detail: "Working on Athena, a personal AI OS.", icon: "brain" },
        { type: "topic", title: "Frequently discussed: athena roadmap", detail: "Mentioned 8 times in your conversations.", icon: "trending-up" },
        { type: "pattern", title: "Peak activity window", detail: "You're most active around 10:00 AM.", icon: "clock" },
        { type: "pattern", title: "Top focus area: Projects", detail: "18 conversations tagged to this category (42.9%).", icon: "folder" },
      ],
      total_user_messages: 42,
    });
  },

  update: async (id: string, content: string): Promise<EnrichedMemory> => {
    if (isLive) {
      const m = await request<{
        id: number; role: "user" | "assistant"; content: string; category: string;
        importance: "low" | "medium" | "high" | "critical"; importance_score: number; createdAt: string | null;
      }>(`/memory/${id}`, { method: "PUT", body: JSON.stringify({ content }) });
      return {
        id: String(m.id), label: m.content, role: m.role,
        category: m.category, importance: m.importance,
        importance_score: m.importance_score, createdAt: m.createdAt,
      };
    }
    return delay({
      id, label: content, role: "user", category: "Conversations",
      importance: "medium" as const, importance_score: 5, createdAt: new Date().toISOString(),
    });
  },

  remove: async (id: string) =>
    isLive
      ? request<{ ok: true }>(`/memory/${id}`, { method: "DELETE" })
      : delay({ ok: true as const }),
};

/* ---------- Analytics ---------- */
export const analyticsApi = {
  get: async (): Promise<mock.Analytics> =>
    isLive ? request<mock.Analytics>("/analytics") : delay(mock.analytics()),
};

/* ---------- Preferences (Phase 4.5 + Phase 14) ---------- */

export interface UserPrefs {
  theme?: string;
  notifications?: boolean;
  default_search_behavior?: string;
  compact_view?: boolean;
  show_timestamps?: boolean;
  /** Phase 14: IANA timezone string e.g. "Asia/Kolkata", "America/New_York" */
  timezone?: string;
  feature_voice?: boolean;
  feature_memory?: boolean;
  feature_analytics?: boolean;
  feature_experimental?: boolean;
}

export const preferencesApi = {
  get: async (): Promise<UserPrefs> => {
    if (isLive) return request<UserPrefs>("/preferences");
    try { return JSON.parse(localStorage.getItem("athena-prefs") ?? "{}"); } catch { return {}; }
  },
  update: async (patch: Partial<UserPrefs>): Promise<UserPrefs> => {
    if (isLive) {
      return request<UserPrefs>("/preferences", { method: "PUT", body: JSON.stringify(patch) });
    }
    const current = JSON.parse(localStorage.getItem("athena-prefs") ?? "{}");
    const updated = { ...current, ...patch };
    localStorage.setItem("athena-prefs", JSON.stringify(updated));
    return delay(updated);
  },
};

/**
 * Phase 14: Auto-detect the browser's IANA timezone and sync it to the
 * backend so Athena resolves reminder times in the user's local timezone.
 *
 * Safe to call multiple times — de-duplicated by comparing to the last
 * synced value stored in localStorage. Fire-and-forget: never throws.
 */
export async function syncTimezoneToBackend(): Promise<void> {
  if (!isLive) return;
  try {
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;

    // Phase 16 fix: the previous version trusted a localStorage cache
    // ("athena-synced-tz") to decide whether a sync was needed, without
    // ever confirming the backend actually still has that value. If the
    // backend's UserPreference row was ever lost (DB reset during dev,
    // a fresh deploy, a different account on the same browser, etc.),
    // the frontend would see its cached value match the browser's
    // current timezone and skip syncing -- permanently, with no way to
    // recover short of manually clearing browser storage. This was the
    // root cause of "Due in about 6 hours" on a reminder set 1 minute
    // out: the backend silently had no timezone for the user and fell
    // back to its UTC default forever, even though the browser's
    // detected timezone was correct the whole time.
    //
    // Fix: always fetch the backend's current stored value and compare
    // against that directly -- the localStorage entry is now only used
    // as a fast-path skip when it's confirmed to still match, not as
    // the sole source of truth.
    let backendTz: string | undefined;
    try {
      const current = await preferencesApi.get();
      backendTz = (current as { timezone?: string }).timezone;
    } catch {
      backendTz = undefined; // couldn't fetch -- proceed to sync to be safe
    }

    const lastSynced = localStorage.getItem("athena-synced-tz");
    if (lastSynced === tz && backendTz === tz) {
      return; // local cache AND backend both confirmed up to date
    }

    await preferencesApi.update({ timezone: tz });
    localStorage.setItem("athena-synced-tz", tz);
  } catch {
    // Never block the app over a timezone sync failure
  }
}

/* ---------- Health Monitor (Phase 4.5) ---------- */

export interface ServiceHealth {
  status: "ok" | "degraded" | "error" | "unknown";
  response_ms?: number;
  detail?: string;
}

export const healthApi = {
  get: async (): Promise<Record<string, ServiceHealth>> => {
    if (isLive) return request<Record<string, ServiceHealth>>("/health");
    return delay({
      backend: { status: "ok" as const, response_ms: 1 },
      database: { status: "ok" as const, response_ms: 2 },
      memory_api: { status: "ok" as const },
      chat_api: { status: "ok" as const },
      upload_api: { status: "ok" as const },
    });
  },
};

/* ---------- Search (Phase 7) ---------- */

export interface SearchResult {
  source: "notes" | "reminders" | "memory" | "documents";
  id: string;
  title: string;
  excerpt: string;
  score: number;
  highlight: [number, number][];   // [start, end] char spans inside excerpt
  meta: Record<string, unknown>;
}

export interface SearchResponse {
  query: string;
  total: number;
  results: SearchResult[];
  sources_searched: string[];
  graph?: KnowledgeGraph;
}

export interface KnowledgeGraphNode {
  id: string;
  label: string;
  type: "query" | "note" | "reminder" | "document" | "memory";
}

export interface KnowledgeGraphEdge {
  from: string;
  to: string;
  label: string;
}

export interface KnowledgeGraph {
  nodes: KnowledgeGraphNode[];
  edges: KnowledgeGraphEdge[];
}

export interface DocumentChunk {
  index: number;
  text: string;
  score: number;
  highlight: [number, number][];
}

export interface DocumentChunksResponse {
  document: {
    id: string; filename: string; pages: number;
    chunkCount: number; uploadedAt: string | null; sizeBytes: number;
  } | null;
  query: string;
  chunks: DocumentChunk[];
}

export const searchApi = {
  global: async (params: {
    q: string;
    sources?: string[];
    limit?: number;
    includeGraph?: boolean;
  }): Promise<SearchResponse> => {
    if (isLive) {
      const sp = new URLSearchParams({ q: params.q });
      if (params.sources?.length) sp.set("sources", params.sources.join(","));
      if (params.limit) sp.set("limit", String(params.limit));
      if (params.includeGraph) sp.set("include_graph", "true");
      return request<SearchResponse>(`/search?${sp}`);
    }
    // Mock: search across mock data
    const q = params.q.toLowerCase();
    const results: SearchResult[] = [];

    mock.notes()
      .filter((n) => `${n.title} ${n.body}`.toLowerCase().includes(q))
      .forEach((n) => {
        const excerpt = `${n.title} — ${n.body.slice(0, 120)}`;
        results.push({
          source: "notes", id: n.id, title: n.title,
          excerpt, score: 1.0,
          highlight: [[excerpt.toLowerCase().indexOf(q), excerpt.toLowerCase().indexOf(q) + q.length]].filter(([s]) => s >= 0) as [number, number][],
          meta: { category: n.category, tags: n.tags, pinned: n.pinned },
        });
      });

    mock.reminders()
      .filter((r) => r.title.toLowerCase().includes(q))
      .forEach((r) => {
        results.push({
          source: "reminders", id: r.id, title: r.title,
          excerpt: r.title, score: 1.0,
          highlight: [[r.title.toLowerCase().indexOf(q), r.title.toLowerCase().indexOf(q) + q.length]].filter(([s]) => s >= 0) as [number, number][],
          meta: { dueAt: r.dueAt, done: r.done, priority: r.priority },
        });
      });

    mock.documents()
      .filter((d) => d.name.toLowerCase().includes(q))
      .forEach((d) => {
        results.push({
          source: "documents", id: d.id, title: d.name,
          excerpt: `${d.name} — ${d.pages} pages, ${d.chunkCount} chunks`,
          score: 0.85, highlight: [],
          meta: { filename: d.name, pages: d.pages, documentId: d.id },
        });
      });

    return delay({
      query: params.q, total: results.length, results,
      sources_searched: ["notes", "reminders", "memory", "documents"],
    });
  },

  documentChunks: async (docId: string, q: string, topK = 5): Promise<DocumentChunksResponse> => {
    if (isLive) {
      return request<DocumentChunksResponse>(
        `/search/document-chunks?doc_id=${encodeURIComponent(docId)}&q=${encodeURIComponent(q)}&top_k=${topK}`
      );
    }
    // Mock chunks
    const doc = mock.documents().find((d) => d.id === docId);
    return delay({
      document: doc
        ? { id: doc.id, filename: doc.name, pages: doc.pages, chunkCount: doc.chunkCount, uploadedAt: doc.uploadedAt, sizeBytes: doc.size }
        : null,
      query: q,
      chunks: doc
        ? [
            { index: 0, text: `This section of ${doc.name} discusses ${q} in the context of business strategy.`, score: 0.92, highlight: [[26 + doc.name.length, 26 + doc.name.length + q.length]] as [number, number][] },
            { index: 1, text: `Further analysis of ${q} reveals key patterns across the dataset provided.`, score: 0.78, highlight: [[20, 20 + q.length]] as [number, number][] },
          ]
        : [],
    });
  },
};
/* ---------- Conversations (Phase 8) ---------- */

export interface ConversationSummary {
  id: number;
  title: string;
  createdAt: string | null;
  updatedAt: string | null;
  messageCount: number;
  starred: boolean;
  pinned: boolean;
  folderId: number | null;
}

export interface ConversationDetail extends ConversationSummary {
  messages: { id: number; role: "user" | "assistant"; content: string; createdAt: string | null }[];
}

export interface ConvFolder {
  id: number;
  name: string;
  createdAt: string | null;
  conversationCount: number;
}

export const conversationsApi = {
  list: async (): Promise<ConversationSummary[]> => {
    if (isLive) return request<ConversationSummary[]>("/conversations");
    return [];
  },
  create: async (title = "New Conversation"): Promise<ConversationSummary> => {
    if (isLive) return request<ConversationSummary>("/conversations", {
      method: "POST", body: JSON.stringify({ title }),
    });
    return { id: Date.now(), title, createdAt: new Date().toISOString(), updatedAt: new Date().toISOString(), messageCount: 0, starred: false, pinned: false, folderId: null };
  },
  get: async (id: number): Promise<ConversationDetail> =>
    request<ConversationDetail>(`/conversations/${id}`),
  update: async (id: number, patch: Partial<Pick<ConversationSummary, "title" | "starred" | "pinned" | "folderId">>): Promise<ConversationSummary> => {
    if (isLive) return request<ConversationSummary>(`/conversations/${id}`, {
      method: "PUT", body: JSON.stringify(patch),
    });
    return { id, title: patch.title ?? "", createdAt: null, updatedAt: null, messageCount: 0, starred: patch.starred ?? false, pinned: patch.pinned ?? false, folderId: patch.folderId ?? null };
  },
  remove: async (id: number) => {
    if (isLive) return request<{ ok: true }>(`/conversations/${id}`, { method: "DELETE" });
    return { ok: true as const };
  },
  toggleStar: async (id: number): Promise<ConversationSummary> =>
    request<ConversationSummary>(`/conversations/${id}/star`, { method: "PATCH" }),
  togglePin: async (id: number): Promise<ConversationSummary> =>
    request<ConversationSummary>(`/conversations/${id}/pin`, { method: "PATCH" }),
  appendMessage: async (id: number, role: "user" | "assistant", content: string) =>
    request(`/conversations/${id}/messages`, { method: "POST", body: JSON.stringify({ role, content }) }),
  search: async (q: string): Promise<ConversationSummary[]> =>
    isLive ? request<ConversationSummary[]>(`/conversations/search?q=${encodeURIComponent(q)}`) : [],
  move: async (id: number, folderId: number | null): Promise<ConversationSummary> =>
    request<ConversationSummary>(`/conversations/${id}/move`, { method: "POST", body: JSON.stringify({ folder_id: folderId }) }),

  /** Phase 15: Seeds LLM memory with this conversation's history so follow-ups work */
  resume: async (id: number): Promise<void> => {
    if (isLive) {
      try {
        await request<{ ok: boolean }>(`/conversations/${id}/resume`, { method: "POST" });
      } catch {
        // Non-fatal — conversation still loads visually even if seed fails
      }
    }
  },

  /**
   * Phase 15 fix: PDF export auth.
   * window.open() can't send Authorization headers → 401.
   * Solution: request a short-lived download token (authenticated),
   * then navigate to the token URL (no auth header needed).
   */
  exportPdf: async (id: number): Promise<void> => {
    if (!isLive) {
      console.warn("PDF export requires a connected backend.");
      return;
    }
    try {
      const { token } = await request<{ token: string; expires_in: number }>(
        `/conversations/${id}/export/token`,
        { method: "POST" },
      );
      // Navigate to token URL — backend validates token, no JWT needed
      window.open(`${API_BASE_URL}/conversations/download/${token}`, "_blank");
    } catch (err) {
      console.error("Export failed:", err);
      // Fallback: try fetch-and-blob approach
      try {
        const tok = getAccessToken();
        const res = await fetch(`${API_BASE_URL}/conversations/${id}/export/pdf`, {
          headers: tok ? { Authorization: `Bearer ${tok}` } : {},
        });
        if (!res.ok) throw new Error("Export failed");
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `conversation-${id}.pdf`;
        a.click();
        setTimeout(() => URL.revokeObjectURL(url), 5000);
      } catch (e2) {
        console.error("Fallback export failed:", e2);
      }
    }
  },
};

export const foldersApi = {
  list: async (): Promise<ConvFolder[]> =>
    isLive ? request<ConvFolder[]>("/folders") : [],
  create: async (name: string): Promise<ConvFolder> =>
    request<ConvFolder>("/folders", { method: "POST", body: JSON.stringify({ name }) }),
  rename: async (id: number, name: string): Promise<ConvFolder> =>
    request<ConvFolder>(`/folders/${id}`, { method: "PUT", body: JSON.stringify({ name }) }),
  remove: async (id: number) =>
    request<{ ok: true }>(`/folders/${id}`, { method: "DELETE" }),
};

export const exportApi = {
  notes: async (fmt: "pdf" | "txt" | "md" = "pdf"): Promise<void> => {
    if (!API_BASE_URL) return;
    // Auth fix: fetch with header, create blob URL
    try {
      const tok = getAccessToken();
      const res = await fetch(`${API_BASE_URL}/notes/export?fmt=${fmt}`, {
        headers: tok ? { Authorization: `Bearer ${tok}` } : {},
      });
      if (res.ok) {
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a"); a.href = url; a.download = `athena-notes.${fmt}`; a.click();
        setTimeout(() => URL.revokeObjectURL(url), 5000);
      }
    } catch {}
  },
  memories: async (fmt: "pdf" | "txt" | "md" = "pdf"): Promise<void> => {
    if (!API_BASE_URL) return;
    try {
      const tok = getAccessToken();
      const res = await fetch(`${API_BASE_URL}/memories/export?fmt=${fmt}`, {
        headers: tok ? { Authorization: `Bearer ${tok}` } : {},
      });
      if (res.ok) {
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a"); a.href = url; a.download = `athena-memories.${fmt}`; a.click();
        setTimeout(() => URL.revokeObjectURL(url), 5000);
      }
    } catch {}
  },
  documentSummary: async (docId: string): Promise<void> => {
    if (!API_BASE_URL) return;
    try {
      const tok = getAccessToken();
      const res = await fetch(`${API_BASE_URL}/documents/${docId}/export/summary`, {
        headers: tok ? { Authorization: `Bearer ${tok}` } : {},
      });
      if (res.ok) {
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a"); a.href = url; a.download = `document-summary.pdf`; a.click();
        setTimeout(() => URL.revokeObjectURL(url), 5000);
      }
    } catch {}
  },
};
/* ---------- Goals API (Phase 14 backend, Phase 15 frontend wire-up) ---------- */

export interface Goal {
  id: number;
  title: string;
  description: string | null;
  timeframe: "short" | "medium" | "long";
  status: "active" | "completed" | "paused";
  progress: number;
  createdAt: string | null;
  updatedAt: string | null;
}

export const goalsApi = {
  list: async (): Promise<Goal[]> =>
    isLive ? request<Goal[]>("/goals") : [],
  create: async (data: { title: string; description?: string; timeframe?: string }): Promise<Goal> =>
    request<Goal>("/goals", { method: "POST", body: JSON.stringify(data) }),
  update: async (id: number, data: Partial<Goal>): Promise<Goal> =>
    request<Goal>(`/goals/${id}`, { method: "PUT", body: JSON.stringify(data) }),
  updateProgress: async (id: number, progress: number): Promise<Goal> =>
    request<Goal>(`/goals/${id}/progress`, { method: "PATCH", body: JSON.stringify({ progress }) }),
  remove: async (id: number): Promise<void> => {
    await request(`/goals/${id}`, { method: "DELETE" });
  },
};

/* ---------- Projects API (Phase 14 backend, Phase 15 frontend wire-up) ---------- */

export interface Project {
  id: number;
  name: string;
  description: string | null;
  status: "active" | "archived";
  createdAt: string | null;
  updatedAt: string | null;
}

export const projectsApi = {
  list: async (): Promise<Project[]> =>
    isLive ? request<Project[]>("/projects") : [],
  create: async (data: { name: string; description?: string }): Promise<Project> =>
    request<Project>("/projects", { method: "POST", body: JSON.stringify(data) }),
  update: async (id: number, data: Partial<Project>): Promise<Project> =>
    request<Project>(`/projects/${id}`, { method: "PUT", body: JSON.stringify(data) }),
  remove: async (id: number): Promise<void> => {
    await request(`/projects/${id}`, { method: "DELETE" });
  },
};

/* ---------- Briefing API (Phase 14 backend, Phase 15 frontend wire-up) ---------- */

export interface BriefingData {
  greeting: string;
  timestamp: string;
  overdue_reminders: Array<{ id: number; title: string; due: string | null }>;
  upcoming_reminders: Array<{ id: number; title: string; due: string | null }>;
  goals: Array<{ id: number; title: string; timeframe: string; progress: number }>;
  recent_conversations: Array<{ id: number; title: string; updatedAt: string | null }>;
  active_projects: Array<{ id: number; name: string }>;
  recent_notes: Array<{ id: number; title: string }>;
  suggestion: string;
  summary: {
    overdue_count: number;
    upcoming_count: number;
    goals_count: number;
    open_conversations: number;
  };
}

export const briefingApi = {
  get: async (): Promise<BriefingData> =>
    isLive ? request<BriefingData>("/briefing") : Promise.reject(new Error("offline")),
};

/* ---------- Assistant Action API (Phase 14) ---------- */

export interface AssistantActionResult {
  action: string;
  result: Record<string, unknown>;
  reply: string;
}

export const assistantApi = {
  action: async (message: string, context = ""): Promise<AssistantActionResult> =>
    request<AssistantActionResult>("/assistant/action", {
      method: "POST",
      body: JSON.stringify({ message, context }),
    }),
};