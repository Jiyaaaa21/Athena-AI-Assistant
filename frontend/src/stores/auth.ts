/**
 * stores/auth.ts  —  Phase 11/12: Authentication state
 *
 * Responsibilities:
 *   - Persist access_token + refresh_token in localStorage
 *   - Expose login(), signup(), logout(), refreshTokens()
 *   - Expose the authenticated user object
 *   - Schedule a proactive token refresh before expiry
 */

import { create } from "zustand";
import { syncTimezoneToBackend } from "@/lib/api";

// ── Types (mirrors backend auth/schemas.py) ───────────────────────────────────

export interface AuthUser {
  id: number;
  name: string;
  email: string;
  bio?: string | null;
  avatar_url?: string | null;
  is_active: boolean;
  is_verified: boolean;
  created_at: string;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number; // seconds
}

export interface AuthResponse {
  user: AuthUser;
  tokens: TokenPair;
}

// ── Storage keys ──────────────────────────────────────────────────────────────

const ACCESS_KEY  = "athena_access_token";
const REFRESH_KEY = "athena_refresh_token";

export function getAccessToken(): string | null {
  return localStorage.getItem(ACCESS_KEY);
}

function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_KEY);
}

function saveTokens(tokens: TokenPair): void {
  localStorage.setItem(ACCESS_KEY, tokens.access_token);
  localStorage.setItem(REFRESH_KEY, tokens.refresh_token);
}

function clearTokens(): void {
  localStorage.removeItem(ACCESS_KEY);
  localStorage.removeItem(REFRESH_KEY);
}

// ── API base ──────────────────────────────────────────────────────────────────

const API_BASE =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "";

async function authFetch<T>(
  path: string,
  body: Record<string, unknown>,
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const data = await res.json();
      if (typeof data?.detail === "string") detail = data.detail;
    } catch { /* ignore */ }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

// ── Zustand store ─────────────────────────────────────────────────────────────

interface AuthState {
  user: AuthUser | null;
  accessToken: string | null;
  /** true while an initial token-check / refresh is in flight at app boot */
  initializing: boolean;

  // Actions
  login:         (email: string, password: string) => Promise<void>;
  signup:        (name: string, email: string, password: string) => Promise<void>;
  logout:        () => Promise<void>;
  refreshTokens: () => Promise<boolean>;
  /** Called once at app boot to restore session from localStorage */
  initialize:    () => Promise<void>;
}

let _refreshTimer: ReturnType<typeof setTimeout> | null = null;

function scheduleRefresh(expiresIn: number, refresh: () => Promise<boolean>) {
  if (_refreshTimer) clearTimeout(_refreshTimer);
  // Refresh 60 s before expiry (but at least 5 s from now)
  const delay = Math.max((expiresIn - 60) * 1000, 5_000);
  _refreshTimer = setTimeout(() => { refresh(); }, delay);
}

export const useAuth = create<AuthState>((set, get) => ({
  user: null,
  accessToken: null,
  initializing: true,

  // ── initialize ─────────────────────────────────────────────────────────────
  initialize: async () => {
    const rt = getRefreshToken();
    if (!rt) {
      set({ initializing: false });
      return;
    }
    try {
      const ok = await get().refreshTokens();
      if (!ok) clearTokens();
      else syncTimezoneToBackend(); // Phase 14: sync tz on session restore
    } catch {
      clearTokens();
    }
    set({ initializing: false });
  },

  // ── login ──────────────────────────────────────────────────────────────────
  login: async (email, password) => {
    const data = await authFetch<AuthResponse>("/auth/login", { email, password });
    saveTokens(data.tokens);
    set({ user: data.user, accessToken: data.tokens.access_token });
    scheduleRefresh(data.tokens.expires_in, get().refreshTokens);
    syncTimezoneToBackend(); // Phase 14: sync user's local timezone
  },

  // ── signup ─────────────────────────────────────────────────────────────────
  signup: async (name, email, password) => {
    const data = await authFetch<AuthResponse>("/auth/signup", { name, email, password });
    saveTokens(data.tokens);
    set({ user: data.user, accessToken: data.tokens.access_token });
    scheduleRefresh(data.tokens.expires_in, get().refreshTokens);
    syncTimezoneToBackend(); // Phase 14: sync user's local timezone
  },

  // ── logout ─────────────────────────────────────────────────────────────────
  logout: async () => {
    const rt = getRefreshToken();
    if (rt && API_BASE) {
      try {
        await authFetch("/auth/logout", { refresh_token: rt });
      } catch { /* ignore server errors on logout */ }
    }
    if (_refreshTimer) clearTimeout(_refreshTimer);
    clearTokens();
    set({ user: null, accessToken: null });
  },

  // ── refreshTokens ──────────────────────────────────────────────────────────
  refreshTokens: async (): Promise<boolean> => {
    const rt = getRefreshToken();
    if (!rt || !API_BASE) return false;
    try {
      const data = await authFetch<TokenPair>("/auth/refresh", {
        refresh_token: rt,
      });
      saveTokens(data);
      set({ accessToken: data.access_token });
      scheduleRefresh(data.expires_in, get().refreshTokens);
      return true;
    } catch {
      clearTokens();
      set({ user: null, accessToken: null });
      return false;
    }
  },
}));
