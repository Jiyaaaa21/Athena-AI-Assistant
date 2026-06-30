/**
 * Composer — Phase 15 voice redesign
 *
 * Voice now works exactly like Claude:
 *  1. Click mic → recording starts, textarea shows live transcript italic
 *  2. VAD auto-stops after silence (or click mic again to stop manually)
 *  3. On stop → transcript appears in textarea, user can edit or press Send
 *  4. Shift+Enter or Send submits normally
 *
 * The separate VoiceDialog modal is still available via onVoiceToggle for
 * continuous/TTS mode, but the default mic in the composer is now inline.
 */

import { useRef, useState, useCallback, useEffect } from "react";
import {
  Mic, MicOff, Send, Paperclip, Square, Loader2,
  X, FileText, Image, AudioLines,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { toast } from "sonner";
import { useVoice } from "@/stores/voice";
import { API_BASE_URL, isLive } from "@/lib/api";
import { getAccessToken } from "@/stores/auth";

type UploadedFile = {
  filename: string;
  content_type: string;
  text_context?: string;
  image_data_uri?: string;
  indexed?: boolean;
  page_count?: number;
};

type Props = {
  onSend: (text: string, uploadedContext?: UploadedFile | null) => void;
  pending?: boolean;
  onVoiceToggle?: () => void;   // opens the full VoiceDialog (continuous mode)
  listening?: boolean;
  streaming?: boolean;
  onStop?: () => void;
};

// ── Inline VAD recorder (self-contained, no store) ───────────────────────────

const VAD_THRESHOLD     = 8;
// Phase 19 fix: was 2200ms — see voice.ts for full explanation. 700ms
// matches real assistant response latency without cutting off natural
// mid-sentence pauses for most speakers.
const VAD_SILENCE_MS    = 700;
const VAD_POLL_MS       = 100;
const STARTUP_GRACE_MS  = 600;  // ignore VAD for this long after starting

type RecorderState = "idle" | "recording" | "processing";

function useInlineVoice(onTranscript: (t: string) => void) {
  const [state, setState]           = useState<RecorderState>("idle");
  const [interim, setInterim]       = useState("");        // shown while recording

  const mediaRecRef = useRef<MediaRecorder | null>(null);
  const chunksRef   = useRef<Blob[]>([]);
  const streamRef   = useRef<MediaStream | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const vadRef      = useRef(false);
  const startedAtRef = useRef(0);

  const cleanup = useCallback(() => {
    vadRef.current = false;
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
    if (audioCtxRef.current) {
      audioCtxRef.current.close().catch(() => {});
      audioCtxRef.current = null;
      analyserRef.current = null;
    }
  }, []);

  const stop = useCallback(() => {
    vadRef.current = false;
    if (mediaRecRef.current && mediaRecRef.current.state === "recording") {
      mediaRecRef.current.stop();
    } else {
      cleanup();
      setState("idle");
      setInterim("");
    }
  }, [cleanup]);

  const start = useCallback(async () => {
    if (state !== "idle") { stop(); return; }

    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true },
      });
    } catch {
      toast.error("Microphone access denied.");
      return;
    }

    streamRef.current = stream;
    setState("recording");
    setInterim("Listening…");
    startedAtRef.current = Date.now();

    // Analyser for VAD
    try {
      audioCtxRef.current = new AudioContext();
      analyserRef.current = audioCtxRef.current.createAnalyser();
      analyserRef.current.fftSize = 256;
      audioCtxRef.current.createMediaStreamSource(stream)
        .connect(analyserRef.current);
    } catch { /* non-fatal */ }

    const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
      ? "audio/webm;codecs=opus"
      : "audio/webm";

    chunksRef.current = [];
    const rec = new MediaRecorder(stream, { mimeType });
    mediaRecRef.current = rec;

    rec.ondataavailable = (e) => { if (e.data.size > 0) chunksRef.current.push(e.data); };

    rec.onstop = async () => {
      cleanup();
      if (chunksRef.current.length === 0) {
        setState("idle");
        setInterim("");
        return;
      }

      setState("processing");
      setInterim("Transcribing…");

      const blob = new Blob(chunksRef.current, { type: mimeType });
      chunksRef.current = [];

      try {
        if (!isLive) {
          setState("idle");
          setInterim("");
          toast.info("Voice transcription requires a connected backend.");
          return;
        }
        const token = getAccessToken();
        const form = new FormData();
        form.append("audio", blob, `recording.webm`);
        form.append("mime_type", mimeType);

        const res = await fetch(`${API_BASE_URL}/voice/transcribe`, {
          method: "POST",
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          body: form,
        });

        if (!res.ok) throw new Error(await res.text());
        const { text } = await res.json() as { text: string };
        const trimmed = text.trim();
        setState("idle");
        setInterim("");
        if (trimmed) onTranscript(trimmed);
      } catch (err) {
        toast.error("Transcription failed: " + (err as Error).message);
        setState("idle");
        setInterim("");
      }
    };

    rec.start(250);

    // VAD
    vadRef.current = true;
    let silentTicks = 0;

    const poll = () => {
      if (!vadRef.current || !analyserRef.current) return;

      const elapsed = Date.now() - startedAtRef.current;
      if (elapsed < STARTUP_GRACE_MS) {
        setTimeout(poll, VAD_POLL_MS);
        return;
      }

      const data = new Uint8Array(analyserRef.current.frequencyBinCount);
      analyserRef.current.getByteTimeDomainData(data);
      let energy = 0;
      for (let i = 0; i < data.length; i++) energy += Math.abs(data[i] - 128);
      energy /= data.length;

      if (energy < VAD_THRESHOLD) {
        silentTicks++;
        if (silentTicks * VAD_POLL_MS >= VAD_SILENCE_MS) {
          vadRef.current = false;
          stop();
          return;
        }
      } else {
        silentTicks = 0;
      }
      setTimeout(poll, VAD_POLL_MS);
    };
    setTimeout(poll, VAD_POLL_MS);

  }, [state, stop, cleanup, onTranscript]);

  // Cleanup on unmount
  useEffect(() => () => { vadRef.current = false; cleanup(); }, [cleanup]);

  return { state, interim, start, stop };
}

// ── Main Composer ─────────────────────────────────────────────────────────────

export function Composer({ onSend, pending, onVoiceToggle, streaming, onStop }: Props) {
  const [value, setValue]           = useState("");
  const [uploadedFile, setUploadedFile] = useState<UploadedFile | null>(null);
  const [uploading, setUploading]   = useState(false);
  const textRef    = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Inline voice — inserts transcript into textarea
  const handleTranscript = useCallback((text: string) => {
    setValue(text);
    // Focus so the user can immediately edit or press Enter
    requestAnimationFrame(() => {
      textRef.current?.focus();
      // Move cursor to end
      const len = text.length;
      textRef.current?.setSelectionRange(len, len);
    });
  }, []);

  const { state: recState, interim, start: startRec, stop: stopRec } =
    useInlineVoice(handleTranscript);

  const isRecording   = recState === "recording";
  const isTranscribing = recState === "processing";
  const isDisabled    = pending || streaming || uploading;

  // ── Text auto-grow ────────────────────────────────────────────────────────
  const adjustHeight = useCallback(() => {
    const el = textRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, []);

  useEffect(() => { adjustHeight(); }, [value, adjustHeight]);

  // ── Submit ────────────────────────────────────────────────────────────────
  const submit = useCallback(() => {
    if (isRecording) { stopRec(); return; }
    const v = value.trim();
    if ((!v && !uploadedFile) || isDisabled) return;
    let messageText = v;
    if (uploadedFile?.text_context && !v) {
      messageText = `Please analyze and summarize this document: "${uploadedFile.filename}"`;
    }
    onSend(messageText, uploadedFile);
    setValue("");
    setUploadedFile(null);
    requestAnimationFrame(() => {
      if (textRef.current) textRef.current.style.height = "auto";
      textRef.current?.focus();
    });
  }, [value, uploadedFile, isDisabled, isRecording, stopRec, onSend]);

  // ── File upload ───────────────────────────────────────────────────────────
  const handleFileSelect = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = "";
    if (!isLive) { toast.info("File uploads require a connected backend."); return; }
    if (file.size > 10 * 1024 * 1024) { toast.error("File too large. Max 10 MB."); return; }
    setUploading(true);
    try {
      const form = new FormData();
      form.append("file", file);
      const token = getAccessToken();
      const res = await fetch(`${API_BASE_URL}/chat/upload-context`, {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: form,
      });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Upload failed");
      const data: UploadedFile = await res.json();
      setUploadedFile(data);
      toast.success(`"${data.filename}" ${data.indexed ? "indexed for search" : "attached"}.`);
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setUploading(false);
    }
  }, []);

  const isImage = uploadedFile?.content_type?.startsWith("image/");

  // ── Placeholder ───────────────────────────────────────────────────────────
  const placeholder = isTranscribing
    ? "Transcribing…"
    : isRecording
    ? interim || "Listening…"
    : uploading
    ? "Uploading file…"
    : streaming
    ? "Athena is generating…"
    : uploadedFile
    ? "Ask about this file, or press Send to analyze it…"
    : "Message Athena…";

  return (
    <div className="w-full max-w-3xl mx-auto">
      <div className={cn(
        "athena-glass rounded-2xl shadow-[0_8px_32px_rgba(0,0,0,0.06)] transition-all",
        isRecording && "ring-2 ring-primary/40",
      )}>

        {/* Attached file preview */}
        {uploadedFile && (
          <div className="mx-3 mt-2 flex items-start gap-2 p-2 rounded-lg border border-border bg-muted/50">
            {isImage && uploadedFile.image_data_uri ? (
              <img src={uploadedFile.image_data_uri} alt={uploadedFile.filename}
                className="size-12 rounded object-cover shrink-0" />
            ) : (
              <div className="size-10 rounded flex items-center justify-center bg-primary/10 shrink-0">
                {isImage ? <Image className="size-5 text-primary" /> : <FileText className="size-5 text-primary" />}
              </div>
            )}
            <div className="flex-1 min-w-0">
              <p className="text-xs font-medium truncate">{uploadedFile.filename}</p>
              <p className="text-[10px] text-muted-foreground">
                {uploadedFile.page_count
                  ? `${uploadedFile.page_count} pages${uploadedFile.indexed ? " · indexed" : ""}`
                  : uploadedFile.content_type}
              </p>
            </div>
            <button onClick={() => setUploadedFile(null)}
              className="shrink-0 p-0.5 rounded text-muted-foreground hover:text-foreground">
              <X className="size-3.5" />
            </button>
          </div>
        )}

        {/* Recording indicator bar */}
        {isRecording && (
          <div className="flex items-center gap-2 px-4 pt-3 pb-1">
            <span className="relative flex size-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-75" />
              <span className="relative inline-flex rounded-full size-2 bg-primary" />
            </span>
            <span className="text-xs text-primary font-medium">Recording — speak now</span>
            <div className="flex-1 flex items-center gap-[2px] h-4 overflow-hidden">
              {Array.from({ length: 24 }).map((_, i) => (
                <div key={i}
                  className="w-[2px] rounded-full bg-primary/60 animate-[voice-bar_0.8s_ease-in-out_infinite]"
                  style={{
                    height: `${30 + Math.random() * 70}%`,
                    animationDelay: `${i * 0.04}s`,
                  }}
                />
              ))}
            </div>
          </div>
        )}

        {/* Textarea */}
        <textarea
          ref={textRef}
          value={value}
          onChange={(e) => { setValue(e.target.value); adjustHeight(); }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); }
          }}
          rows={1}
          placeholder={placeholder}
          disabled={isDisabled || isTranscribing}
          className={cn(
            "w-full bg-transparent resize-none focus:outline-none px-4 py-3 text-sm",
            "placeholder:text-muted-foreground max-h-52 disabled:opacity-60",
            isRecording && "placeholder:text-primary/60",
          )}
          style={{ minHeight: 44 }}
        />

        {/* Bottom toolbar */}
        <div className="flex items-center justify-between px-2 pb-2 pt-0">
          {/* Left: attach */}
          <div className="flex items-center gap-0.5">
            <input ref={fileInputRef} type="file"
              accept=".pdf,.jpg,.jpeg,.png,.gif,.webp,.txt,.md"
              onChange={handleFileSelect} className="sr-only" />
            <button type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={isDisabled || !!uploadedFile}
              className={cn(
                "size-9 grid place-items-center rounded-full transition-colors",
                "text-muted-foreground hover:bg-black/5 hover:text-foreground",
                (isDisabled || !!uploadedFile) && "opacity-40 cursor-not-allowed",
              )}
              title="Attach file">
              {uploading
                ? <Loader2 className="size-4 animate-spin" />
                : <Paperclip className="size-4" />}
            </button>

            {/* Full voice mode button (opens VoiceDialog for TTS continuous) */}
            {onVoiceToggle && (
              <button type="button" onClick={onVoiceToggle}
                className="size-9 grid place-items-center rounded-full text-muted-foreground hover:bg-black/5 hover:text-foreground transition-colors"
                title="Full voice mode (with speaker)">
                <AudioLines className="size-4" />
              </button>
            )}
          </div>

          {/* Right: mic + send/stop */}
          <div className="flex items-center gap-1.5">

            {/* Inline mic — Claude-style */}
            <button type="button"
              onClick={isRecording ? stopRec : startRec}
              disabled={isDisabled || isTranscribing}
              className={cn(
                "size-9 grid place-items-center rounded-full transition-all",
                isRecording
                  ? "bg-primary text-primary-foreground ring-4 ring-primary/20"
                  : isTranscribing
                  ? "bg-muted text-muted-foreground cursor-wait"
                  : "text-muted-foreground hover:bg-black/5 hover:text-foreground",
              )}
              title={isRecording ? "Stop recording" : "Voice input"}>
              {isTranscribing
                ? <Loader2 className="size-4 animate-spin" />
                : isRecording
                ? <MicOff className="size-4" />
                : <Mic className="size-4" />}
            </button>

            {/* Send / Stop streaming */}
            {streaming ? (
              <button type="button" onClick={onStop}
                className="h-9 px-3 rounded-full text-sm font-medium flex items-center gap-1.5 bg-destructive text-destructive-foreground hover:brightness-110 shadow-sm transition-all">
                <Square className="size-3.5" />
                Stop
              </button>
            ) : (
              <button type="button" onClick={submit}
                disabled={(!value.trim() && !uploadedFile) || isDisabled}
                className={cn(
                  "size-9 grid place-items-center rounded-full transition-all shadow-sm",
                  (value.trim() || uploadedFile) && !isDisabled
                    ? "bg-primary text-primary-foreground hover:brightness-110"
                    : "bg-muted text-muted-foreground cursor-not-allowed opacity-50",
                )}
                title="Send (Enter)">
                <Send className="size-4" />
              </button>
            )}
          </div>
        </div>
      </div>

      <p className="text-center text-[10px] text-muted-foreground mt-3 tracking-wide">
        Press{" "}
        <kbd className="px-1.5 py-0.5 border border-border rounded bg-secondary font-mono text-[10px]">⌘K</kbd>
        {" "}for command palette · {" "}
        <kbd className="px-1.5 py-0.5 border border-border rounded bg-secondary font-mono text-[10px]">Enter</kbd>
        {" "}to send
      </p>
    </div>
  );
}
