/**
 * Phase 8: Conversation Management Store
 *
 * Manages the active conversation list, search, folder assignment,
 * star/pin state, and the currently-open conversation ID.
 */
import { create } from "zustand";
import { toast } from "sonner";
import {
  conversationsApi,
  foldersApi,
  type ConversationSummary,
  type ConvFolder,
} from "@/lib/api";

type ConvsState = {
  conversations: ConversationSummary[];
  folders: ConvFolder[];
  activeId: number | null;
  searchQuery: string;
  loading: boolean;

  // Actions
  load: () => Promise<void>;
  loadFolders: () => Promise<void>;
  setActive: (id: number | null) => void;
  setSearchQuery: (q: string) => void;

  createConversation: (title?: string) => Promise<ConversationSummary>;
  renameConversation: (id: number, title: string) => Promise<void>;
  deleteConversation: (id: number) => Promise<void>;
  toggleStar: (id: number) => Promise<void>;
  togglePin: (id: number) => Promise<void>;
  moveToFolder: (convId: number, folderId: number | null) => Promise<void>;

  createFolder: (name: string) => Promise<void>;
  renameFolder: (id: number, name: string) => Promise<void>;
  deleteFolder: (id: number) => Promise<void>;

  // Derived helpers (call in component)
  filteredConversations: (q?: string) => ConversationSummary[];
};

export const useConversations = create<ConvsState>((set, get) => ({
  conversations: [],
  folders: [],
  activeId: null,
  searchQuery: "",
  loading: false,

  load: async () => {
    set({ loading: true });
    try {
      const conversations = await conversationsApi.list();
      set({ conversations });
    } catch (e) {
      toast.error((e as Error).message || "Could not load conversations");
    } finally {
      set({ loading: false });
    }
  },

  loadFolders: async () => {
    try {
      const folders = await foldersApi.list();
      set({ folders });
    } catch {
      // non-fatal
    }
  },

  setActive: (id) => set({ activeId: id }),
  setSearchQuery: (q) => set({ searchQuery: q }),

  createConversation: async (title = "New Conversation") => {
    const conv = await conversationsApi.create(title);
    set((s) => ({ conversations: [conv, ...s.conversations] }));
    return conv;
  },

  renameConversation: async (id, title) => {
    try {
      const updated = await conversationsApi.update(id, { title });
      set((s) => ({
        conversations: s.conversations.map((c) => (c.id === id ? updated : c)),
      }));
    } catch (e) {
      toast.error((e as Error).message || "Rename failed");
    }
  },

  deleteConversation: async (id) => {
    try {
      await conversationsApi.remove(id);
      set((s) => ({
        conversations: s.conversations.filter((c) => c.id !== id),
        activeId: s.activeId === id ? null : s.activeId,
      }));
    } catch (e) {
      toast.error((e as Error).message || "Delete failed");
    }
  },

  toggleStar: async (id) => {
    try {
      const updated = await conversationsApi.toggleStar(id);
      set((s) => ({
        conversations: s.conversations.map((c) => (c.id === id ? updated : c)),
      }));
    } catch (e) {
      toast.error((e as Error).message || "Failed");
    }
  },

  togglePin: async (id) => {
    try {
      const updated = await conversationsApi.togglePin(id);
      set((s) => ({
        conversations: s.conversations.map((c) => (c.id === id ? updated : c)),
      }));
    } catch (e) {
      toast.error((e as Error).message || "Failed");
    }
  },

  moveToFolder: async (convId, folderId) => {
    try {
      const updated = await conversationsApi.move(convId, folderId);
      set((s) => ({
        conversations: s.conversations.map((c) => (c.id === convId ? updated : c)),
      }));
    } catch (e) {
      toast.error((e as Error).message || "Failed to move");
    }
  },

  createFolder: async (name) => {
    try {
      const folder = await foldersApi.create(name);
      set((s) => ({ folders: [...s.folders, folder] }));
    } catch (e) {
      toast.error((e as Error).message || "Create folder failed");
    }
  },

  renameFolder: async (id, name) => {
    try {
      const updated = await foldersApi.rename(id, name);
      set((s) => ({
        folders: s.folders.map((f) => (f.id === id ? updated : f)),
      }));
    } catch (e) {
      toast.error((e as Error).message || "Rename failed");
    }
  },

  deleteFolder: async (id) => {
    try {
      await foldersApi.remove(id);
      set((s) => ({
        folders: s.folders.filter((f) => f.id !== id),
        conversations: s.conversations.map((c) =>
          c.folderId === id ? { ...c, folderId: null } : c
        ),
      }));
    } catch (e) {
      toast.error((e as Error).message || "Delete failed");
    }
  },

  filteredConversations: (q) => {
    const query = (q ?? get().searchQuery).toLowerCase().trim();
    if (!query) return get().conversations;
    return get().conversations.filter((c) =>
      c.title.toLowerCase().includes(query)
    );
  },
}));