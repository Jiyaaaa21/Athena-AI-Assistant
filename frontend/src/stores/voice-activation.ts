/**
 * Phase 18 — Global voice activation signal.
 *
 * Wake word detection runs at the AppShell level (so it works from any
 * page, not just while Voice Mode is already open — that was the actual
 * bug: the old wake word listener only ran INSIDE VoiceDialog, gated on
 * `open: true`, which is backwards. A real wake word needs to listen
 * continuously app-wide and trigger the dialog to open, not the other
 * way around.
 *
 * Since AppShell wraps every route but VoiceDialog currently only lives
 * on the home page, this tiny store is the signal between them: AppShell
 * sets `triggered: true` when the wake word fires, the home page watches
 * this store and opens VoiceDialog + starts listening when it changes.
 */
import { create } from "zustand";

interface VoiceActivationState {
  /** Incrementing counter — changes every time the wake word fires, so
   *  watchers can detect "a new wake event happened" even if they missed
   *  the boolean flip (e.g. component not mounted yet). */
  wakeEventId: number;
  triggerWake: () => void;
}

export const useVoiceActivation = create<VoiceActivationState>((set, get) => ({
  wakeEventId: 0,
  triggerWake: () => set({ wakeEventId: get().wakeEventId + 1 }),
}));
