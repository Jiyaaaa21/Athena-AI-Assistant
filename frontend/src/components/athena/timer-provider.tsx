/**
 * TimerProvider  —  Phase 18
 *
 * The one piece every "set a timer" voice command was missing: an actual
 * audible alarm. Reminders fire silently as a browser Notification;
 * Timers need to RING — the classic Alexa/Siri "your timer is up" sound.
 *
 * Mounted once in AppShell so it works regardless of which page is open.
 * Polls GET /timers every 5s for the active list, runs local countdowns
 * between polls (no need to hit the network every second), and the
 * moment any timer's remaining time hits zero, plays a looping alarm
 * tone via the Web Audio API (no external sound file needed) and shows
 * a dismiss-able full-attention toast. Calls POST /timers/{id}/finish
 * once acknowledged.
 */
import { useEffect, useRef, useState, useCallback } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { API_BASE_URL, isLive } from "@/lib/api";
import { getAccessToken } from "@/stores/auth";
import { useAuth } from "@/stores/auth";

interface TimerData {
  id: number;
  label: string | null;
  durationSeconds: number;
  endsAt: string | null;
  status: "running" | "paused" | "finished" | "cancelled";
  remainingSecondsAtPause: number | null;
}

const POLL_INTERVAL_MS = 5_000;

// ── Alarm tone via Web Audio API — no audio file dependency ──────────────────

let _alarmCtx: AudioContext | null = null;
let _alarmOscillators: OscillatorNode[] = [];
let _alarmInterval: ReturnType<typeof setInterval> | null = null;

function startAlarmTone() {
  stopAlarmTone();
  try {
    _alarmCtx = new AudioContext();
    const playBeep = () => {
      if (!_alarmCtx) return;
      const osc = _alarmCtx.createOscillator();
      const gain = _alarmCtx.createGain();
      osc.type = "sine";
      osc.frequency.value = 880; // A5 — clear, attention-getting, not harsh
      gain.gain.setValueAtTime(0, _alarmCtx.currentTime);
      gain.gain.linearRampToValueAtTime(0.25, _alarmCtx.currentTime + 0.02);
      gain.gain.linearRampToValueAtTime(0, _alarmCtx.currentTime + 0.35);
      osc.connect(gain);
      gain.connect(_alarmCtx.destination);
      osc.start();
      osc.stop(_alarmCtx.currentTime + 0.4);
      _alarmOscillators.push(osc);
    };
    playBeep();
    _alarmInterval = setInterval(playBeep, 700); // repeating beep pattern
  } catch {
    // Web Audio unavailable — non-fatal, the visual toast still shows
  }
}

function stopAlarmTone() {
  if (_alarmInterval) { clearInterval(_alarmInterval); _alarmInterval = null; }
  _alarmOscillators = [];
  if (_alarmCtx) { _alarmCtx.close().catch(() => {}); _alarmCtx = null; }
}

async function fetchActiveTimers(): Promise<TimerData[]> {
  const tok = getAccessToken();
  const res = await fetch(`${API_BASE_URL}/timers`, {
    headers: tok ? { Authorization: `Bearer ${tok}` } : {},
  });
  if (!res.ok) return [];
  const data = await res.json() as { timers: TimerData[] };
  return data.timers ?? [];
}

async function markTimerFinished(id: number) {
  const tok = getAccessToken();
  await fetch(`${API_BASE_URL}/timers/${id}/finish`, {
    method: "POST",
    headers: tok ? { Authorization: `Bearer ${tok}` } : {},
  }).catch(() => {});
}

export function TimerProvider() {
  const { user, initializing } = useAuth();
  const [timers, setTimers] = useState<TimerData[]>([]);
  const ringingRef = useRef<Set<number>>(new Set());
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const poll = useCallback(async () => {
    if (!isLive || !user) return;
    try {
      const active = await fetchActiveTimers();
      setTimers(active);
    } catch {
      // silent — non-critical background poll
    }
  }, [user]);

  const handleRing = useCallback((timer: TimerData) => {
    if (ringingRef.current.has(timer.id)) return;
    ringingRef.current.add(timer.id);

    startAlarmTone();

    const label = timer.label ? `"${timer.label}"` : "Your timer";

    toast(`⏰ ${label} is up!`, {
      duration: Infinity, // stays until dismissed — an alarm shouldn't auto-hide
      action: {
        label: "Dismiss",
        onClick: () => {
          stopAlarmTone();
          ringingRef.current.delete(timer.id);
          markTimerFinished(timer.id);
          setTimers((prev) => prev.filter((t) => t.id !== timer.id));
        },
      },
    });

    // Browser notification too, in case the tab isn't focused
    if ("Notification" in window && Notification.permission === "granted") {
      try {
        const n = new Notification(`⏰ ${label} is up!`, {
          body: "Your timer has finished.",
          requireInteraction: true,
          tag: `athena-timer-${timer.id}`,
        });
        n.onclick = () => { window.focus(); n.close(); };
      } catch { /* non-fatal */ }
    }
  }, []);

  // Poll for active timers
  useEffect(() => {
    if (initializing || !user) return;
    poll();
    pollRef.current = setInterval(poll, POLL_INTERVAL_MS);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [initializing, user, poll]);

  // Local 1s tick — checks each running timer's endsAt against now,
  // independent of the 5s network poll, so the alarm fires within ~1s
  // of actually hitting zero rather than waiting for the next poll.
  useEffect(() => {
    tickRef.current = setInterval(() => {
      const now = Date.now();
      for (const t of timers) {
        if (t.status !== "running" || !t.endsAt) continue;
        const endsAtMs = new Date(t.endsAt).getTime();
        if (endsAtMs <= now) {
          handleRing(t);
        }
      }
    }, 1000);
    return () => { if (tickRef.current) clearInterval(tickRef.current); };
  }, [timers, handleRing]);

  // Cleanup alarm if component unmounts mid-ring (shouldn't normally
  // happen since this lives in AppShell, but guards against it)
  useEffect(() => () => stopAlarmTone(), []);

  return null;
}
