/**
 * stores/chat.ts — Agent name now persisted on each assistant message
 * so it shows as a badge even after streaming ends.
 */

import { create } from "zustand";
import { toast } from "sonner";
import { chatApi, chatStream } from "@/lib/api";
import type { ChatMessage } from "@/lib/mock";

// Phase 24 fix: onToken below used to call `import("@/stores/voice")` on
// EVERY streamed token to feed the incremental TTS pipeline -- during a
// long response that's dozens of dynamic-import + promise-chain calls
// per second. The module itself is bundler-cached after the first call
// so this was never a real network/parse cost, but it was still
// needless promise/microtask churn stacked on top of the exact code path
// users were reporting as sluggish. Resolve it once and reuse the
// reference; any token that streams in before the first resolution just
// gets picked up by the next one a few ms later (streamingText already
// accumulates in this store regardless), so nothing is lost.
let _voiceModuleCache: typeof import("@/stores/voice") | null = null;
function _getVoiceModuleSync(): typeof import("@/stores/voice") | null {
  if (!_voiceModuleCache) {
    import("@/stores/voice").then((m) => { _voiceModuleCache = m; }).catch(() => {});
    return null;
  }
  return _voiceModuleCache;
}

type UploadedFile = {
  filename: string;
  content_type: string;
  text_context?: string;
  image_data_uri?: string;
  indexed?: boolean;
  page_count?: number;
};

type ChatState = {
  messages: ChatMessage[];
  pending: boolean;
  hydrated: boolean;
  hydrating: boolean;
  activeConversationId: number | null;

  streaming: boolean;
  streamingText: string;
  statusText: string;
  _cancelStream: (() => void) | null;

  activeAgentName: string | null;
  agentSteps: string[];

  send: (text: string) => Promise<void>;
  regenerate: () => Promise<void>;
  reset: () => void;
  hydrate: () => Promise<void>;
  loadConversation: (id: number, messages: ChatMessage[]) => void;
  sendStream: (text: string, uploadedContext?: UploadedFile | null, speakAloud?: boolean) => void;
  cancelStream: () => void;
};

function uid() {
  return Math.random().toString(36).slice(2, 10);
}

function buildMessageWithContext(text: string, file: UploadedFile | null | undefined): string {
  if (!file) return text;
  if (file.image_data_uri) {
    return text ? `${text}\n\n[Attached image: ${file.filename}]` : `Please analyze this image: ${file.filename}`;
  }
  if (file.text_context) {
    const header = `[Attached file: ${file.filename}]\n\n${file.text_context}\n\n---\n\n`;
    return text ? `${header}User question: ${text}` : `${header}Please analyze and summarize the above document.`;
  }
  return text || `Please analyze the attached file: ${file.filename}`;
}

export const useChat = create<ChatState>((set, get) => ({
  messages: [],
  pending: false,
  hydrated: false,
  hydrating: false,
  activeConversationId: null,

  streaming: false,
  streamingText: "",
  statusText: "",
  _cancelStream: null,

  activeAgentName: null,
  agentSteps: [],

  reset: () =>
    set({
      messages: [],
      pending: false,
      activeConversationId: null,
      streaming: false,
      streamingText: "",
      statusText: "",
      _cancelStream: null,
      activeAgentName: null,
      agentSteps: [],
    }),

  loadConversation: (id: number, messages: ChatMessage[]) => {
    set({ messages, activeConversationId: id, hydrated: true });
  },

  hydrate: async () => {
    if (get().hydrated || get().hydrating) return;
    set({ hydrating: true });
    try {
      const history = await chatApi.history();
      if (get().messages.length === 0) {
        set({ messages: history });
      }
    } catch (e) {
      toast.error((e as Error).message || "Couldn't load chat history");
    } finally {
      set({ hydrated: true, hydrating: false });
    }
  },

  send: async (text: string) => {
    const userMsg: ChatMessage = {
      id: uid(),
      role: "user",
      content: text,
      createdAt: new Date().toISOString(),
    };
    set({ messages: [...get().messages, userMsg], pending: true });

    try {
      const { reply, sources, conversationId } = await chatApi.send(
        text,
        get().messages.map((m) => ({ role: m.role, content: m.content })),
        get().activeConversationId,
      );

      if (conversationId) set({ activeConversationId: conversationId });

      const assistantMsg: ChatMessage = {
        id: uid(),
        role: "assistant",
        content: reply,
        createdAt: new Date().toISOString(),
        sources,
      };
      set({ messages: [...get().messages, assistantMsg], pending: false });

      try {
        const { useConversations } = await import("@/stores/conversations");
        useConversations.getState().load();
      } catch { /* non-fatal */ }
    } catch (e) {
      toast.error((e as Error).message || "Couldn't reach the Athena engine");
      set({
        messages: [
          ...get().messages,
          {
            id: uid(),
            role: "assistant",
            content: `Sorry, I couldn't reach the Athena engine. (${(e as Error).message})`,
            createdAt: new Date().toISOString(),
          },
        ],
        pending: false,
      });
    }
  },

  sendStream: (text: string, uploadedContext?: UploadedFile | null, speakAloud?: boolean) => {
    if (get().streaming || get().pending) return;

    const displayText = text || (uploadedContext ? `[Attached: ${uploadedContext.filename}]` : "");
    const backendMessage = buildMessageWithContext(text, uploadedContext);

    const userMsg: ChatMessage = {
      id: uid(),
      role: "user",
      content: displayText,
      createdAt: new Date().toISOString(),
      ...(uploadedContext?.image_data_uri
        ? { imagePreview: uploadedContext.image_data_uri, imageFilename: uploadedContext.filename }
        : {}),
    };

    const assistantId = uid();
    const assistantPlaceholder: ChatMessage = {
      id: assistantId,
      role: "assistant",
      content: "",
      createdAt: new Date().toISOString(),
    };

    set({
      messages: [...get().messages, userMsg, assistantPlaceholder],
      streaming: true,
      streamingText: "",
      statusText: "Athena is thinking…",
      pending: false,
    });

    const cancel = chatStream(
      backendMessage,
      get().activeConversationId,
      {
        onStatus: (statusText, agent) => {
          set({ statusText, activeAgentName: agent ?? null });
        },

        onToken: (chunk) => {
          const newText = get().streamingText + chunk;
          set((state) => ({
            streamingText: newText,
            messages: state.messages.map((m) =>
              m.id === assistantId ? { ...m, content: newText } : m
            ),
          }));

          // Phase 17 — voice mode: feed the LLM's growing text into the
          // incremental TTS pipeline so Athena starts speaking the first
          // sentence well before the full response has finished
          // generating, instead of waiting for onDone to fire speak().
          if (speakAloud) {
            _getVoiceModuleSync()?.useVoice.getState().speakIncremental(newText);
          }
        },

        onDone: (conversationId, sources, agentName, steps) => {
          if (conversationId) set({ activeConversationId: conversationId });

          if (speakAloud) {
            _getVoiceModuleSync()?.useVoice.getState().finishIncremental();
          }

          // ── Persist agentName ON the message itself so badge stays visible ──
          set((state) => ({
            streaming: false,
            streamingText: "",
            statusText: "",
            _cancelStream: null,
            activeAgentName: agentName ?? state.activeAgentName,
            agentSteps: steps ?? state.agentSteps,
            messages: state.messages.map((m) =>
              m.id === assistantId
                ? {
                    ...m,
                    sources: sources?.length ? sources : undefined,
                    agentName: agentName ?? undefined,  // ← stored on message
                  }
                : m
            ),
          }));

          import("@/stores/conversations")
            .then(({ useConversations }) => useConversations.getState().load())
            .catch(() => {});
        },

        onError: (errText) => {
          toast.error(errText || "Stream error");
          set((state) => ({
            streaming: false,
            streamingText: "",
            statusText: "",
            _cancelStream: null,
            messages: state.messages.map((m) =>
              m.id === assistantId
                ? { ...m, content: errText || "An error occurred." }
                : m
            ),
          }));
        },
      },
      uploadedContext?.image_data_uri,
    );

    set({ _cancelStream: cancel });
  },

  cancelStream: () => {
    const cancel = get()._cancelStream;
    if (cancel) cancel();
    set({
      streaming: false,
      streamingText: "",
      statusText: "",
      _cancelStream: null,
      messages: get().messages.map((m, i, arr) =>
        i === arr.length - 1 && m.role === "assistant" && !m.content
          ? { ...m, content: "*(generation stopped)*" }
          : m
      ),
    });
  },

  regenerate: async () => {
    const msgs = get().messages;
    const lastUser = [...msgs].reverse().find((m) => m.role === "user");
    if (!lastUser) return;

    const trimmed =
      msgs[msgs.length - 1]?.role === "assistant" ? msgs.slice(0, -1) : msgs;

    set({ messages: trimmed });

    // Phase 28 fix: if the message being regenerated had an image
    // attached, reconstruct that context and pass it through too --
    // previously this only re-sent the display text, so regenerating an
    // image-analysis answer would silently arrive with no image at all.
    const reconstructedFile: UploadedFile | undefined = lastUser.imagePreview
      ? {
          filename: lastUser.imageFilename || "image",
          content_type: "image/*",
          image_data_uri: lastUser.imagePreview,
        }
      : undefined;

    // The auto-generated "[Attached: filename]" placeholder (used when the
    // original message was just an image with no typed text) shouldn't be
    // re-sent as if it were real typed text -- buildMessageWithContext()
    // already produces a sensible default prompt when given an empty
    // string plus an image, so strip the placeholder back out here.
    const textToResend = lastUser.content.startsWith("[Attached: ")
      ? ""
      : lastUser.content;

    get().sendStream(textToResend, reconstructedFile);
  },
}));