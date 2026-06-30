/**
 * Phase 8 — Conversation Manager
 * Redesigned (Issue #1): ChatGPT/Claude-style conversation list.
 *  - Fills remaining sidebar height (flex-1 + overflow-y-auto)
 *  - Conversations grouped by time: Today / Yesterday / Previous 7 Days / Older
 *  - Clean minimal rows — no borders, no boxes, no search bar in the panel
 *    (global search already lives in the sidebar header)
 *  - Hover reveals a "…" menu for rename / star / pin / move / export / delete
 *  - Header "Conversations" label + new-folder button stay at top of section
 */

import { useEffect, useState, useRef } from "react";
import {
  Star, Pin, Trash2, Pencil, Check, X, FolderOpen,
  Folder as FolderIcon, FolderPlus, MessageSquare, Search,
  ChevronDown, ChevronRight, MoreHorizontal, Download,
} from "lucide-react";
import { useConversations } from "@/stores/conversations";
import { useChat } from "@/stores/chat";
import { conversationsApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useNavigate } from "@tanstack/react-router";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem,
  DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel,
  AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import type { ConversationSummary, ConvFolder } from "@/lib/api";
import { toast } from "sonner";

// ─── Time grouping helper ──────────────────────────────────────────────────────

function getTimeGroup(dateStr?: string | null): string {
  if (!dateStr) return "Older";
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

  if (diffDays === 0) return "Today";
  if (diffDays === 1) return "Yesterday";
  if (diffDays <= 7) return "Previous 7 Days";
  if (diffDays <= 30) return "Previous 30 Days";
  return "Older";
}

const GROUP_ORDER = ["Today", "Yesterday", "Previous 7 Days", "Previous 30 Days", "Older"];

// ─── Single conversation row ───────────────────────────────────────────────────

function ConvRow({
  conv, active, folders, onSelect, onRename, onDelete, onStar, onPin, onMove, onExport,
}: {
  conv: ConversationSummary;
  active: boolean;
  folders: ConvFolder[];
  onSelect: () => void;
  onRename: (title: string) => void;
  onDelete: () => void;
  onStar: () => void;
  onPin: () => void;
  onMove: (folderId: number | null) => void;
  onExport: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(conv.title);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [moveOpen, setMoveOpen] = useState(false);
  const [targetFolder, setTargetFolder] = useState<string>(
    conv.folderId ? String(conv.folderId) : "none"
  );
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => { if (editing) inputRef.current?.focus(); }, [editing]);

  const commitRename = () => {
    const trimmed = draft.trim();
    if (trimmed && trimmed !== conv.title) onRename(trimmed);
    setEditing(false);
  };

  return (
    <>
      <div
        className={cn(
          "group relative flex items-center gap-2 px-3 py-2 rounded-lg cursor-pointer transition-colors",
          active
            ? "bg-primary/10 text-primary"
            : "text-foreground/70 hover:bg-black/5 hover:text-foreground",
        )}
        onClick={onSelect}
      >
        {/* Leading icon / indicator */}
        <div className="shrink-0 mt-px">
          {conv.pinned
            ? <Pin className="size-3 text-blue-500 rotate-45" />
            : conv.starred
            ? <Star className="size-3 text-amber-400 fill-amber-400" />
            : <MessageSquare className="size-3 opacity-30" />}
        </div>

        {/* Title */}
        <div className="flex-1 min-w-0">
          {editing ? (
            <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
              <Input
                ref={inputRef}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") commitRename();
                  if (e.key === "Escape") setEditing(false);
                }}
                className="h-5 text-xs px-1 py-0"
              />
              <button onClick={commitRename} className="text-green-600 shrink-0">
                <Check className="size-3" />
              </button>
              <button onClick={() => setEditing(false)} className="text-muted-foreground shrink-0">
                <X className="size-3" />
              </button>
            </div>
          ) : (
            <span className="truncate block text-sm leading-snug">{conv.title}</span>
          )}
        </div>

        {/* Actions — visible on hover */}
        {!editing && (
          <div
            className="opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
            onClick={(e) => e.stopPropagation()}
          >
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button className="p-0.5 rounded hover:bg-black/10 text-muted-foreground">
                  <MoreHorizontal className="size-3.5" />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="text-xs w-44">
                <DropdownMenuItem onClick={() => { setDraft(conv.title); setEditing(true); }}>
                  <Pencil className="size-3 mr-2" /> Rename
                </DropdownMenuItem>
                <DropdownMenuItem onClick={onStar}>
                  <Star className="size-3 mr-2" />
                  {conv.starred ? "Unstar" : "Star"}
                </DropdownMenuItem>
                <DropdownMenuItem onClick={onPin}>
                  <Pin className="size-3 mr-2" />
                  {conv.pinned ? "Unpin" : "Pin"}
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => {
                  setTargetFolder(conv.folderId ? String(conv.folderId) : "none");
                  setMoveOpen(true);
                }}>
                  <FolderOpen className="size-3 mr-2" /> Move to folder
                </DropdownMenuItem>
                <DropdownMenuItem onClick={onExport}>
                  <Download className="size-3 mr-2" /> Export PDF
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  onClick={() => setDeleteOpen(true)}
                  className="text-destructive focus:text-destructive"
                >
                  <Trash2 className="size-3 mr-2" /> Delete
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        )}
      </div>

      {/* Delete confirmation */}
      <AlertDialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete conversation?</AlertDialogTitle>
            <AlertDialogDescription>
              &ldquo;{conv.title}&rdquo; and all its messages will be permanently deleted.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={onDelete}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Move to folder */}
      <Dialog open={moveOpen} onOpenChange={setMoveOpen}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader><DialogTitle>Move to folder</DialogTitle></DialogHeader>
          <Select value={targetFolder} onValueChange={setTargetFolder}>
            <SelectTrigger><SelectValue placeholder="Select folder" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="none">No folder</SelectItem>
              {folders.map((f) => (
                <SelectItem key={f.id} value={String(f.id)}>{f.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <DialogFooter>
            <Button variant="outline" onClick={() => setMoveOpen(false)}>Cancel</Button>
            <Button onClick={() => {
              onMove(targetFolder === "none" ? null : Number(targetFolder));
              setMoveOpen(false);
            }}>
              Move
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

// ─── Folder section ────────────────────────────────────────────────────────────

function FolderSection({
  folder, conversations, activeId, folders,
  onSelect, onRename, onDelete, onStar, onPin, onMove, onExport,
  onFolderRename, onFolderDelete,
}: {
  folder: ConvFolder;
  conversations: ConversationSummary[];
  activeId: number | null;
  folders: ConvFolder[];
  onSelect: (id: number) => void;
  onRename: (id: number, title: string) => void;
  onDelete: (id: number) => void;
  onStar: (id: number) => void;
  onPin: (id: number) => void;
  onMove: (convId: number, folderId: number | null) => void;
  onExport: (id: number) => void;
  onFolderRename: (id: number, name: string) => void;
  onFolderDelete: (id: number) => void;
}) {
  const [open, setOpen] = useState(true);
  const [editingName, setEditingName] = useState(false);
  const [draft, setDraft] = useState(folder.name);
  const [deleteOpen, setDeleteOpen] = useState(false);

  return (
    <div className="mb-1">
      <div className="flex items-center gap-1 px-2 py-1 group">
        <button
          onClick={() => setOpen((o) => !o)}
          className="flex items-center gap-1.5 flex-1 text-[10px] uppercase tracking-widest text-muted-foreground/80 font-semibold"
        >
          {open ? <ChevronDown className="size-3 shrink-0" /> : <ChevronRight className="size-3 shrink-0" />}
          <FolderIcon className="size-3 shrink-0" />
          {editingName ? (
            <Input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") { onFolderRename(folder.id, draft.trim() || folder.name); setEditingName(false); }
                if (e.key === "Escape") setEditingName(false);
              }}
              className="h-4 text-[10px] px-1 py-0 w-24"
              onClick={(e) => e.stopPropagation()}
            />
          ) : (
            <span className="truncate">{folder.name}</span>
          )}
          <span className="ml-1 text-[9px] opacity-50">({conversations.length})</span>
        </button>
        <div className="opacity-0 group-hover:opacity-100 flex gap-0.5">
          <button onClick={() => { setDraft(folder.name); setEditingName(true); }} className="p-0.5 rounded hover:bg-black/10 text-muted-foreground">
            <Pencil className="size-2.5" />
          </button>
          <button onClick={() => setDeleteOpen(true)} className="p-0.5 rounded hover:bg-black/10 text-muted-foreground">
            <Trash2 className="size-2.5" />
          </button>
        </div>
      </div>

      {open && (
        <div className="ml-3 space-y-0.5">
          {conversations.map((c) => (
            <ConvRow
              key={c.id} conv={c} active={activeId === c.id} folders={folders}
              onSelect={() => onSelect(c.id)}
              onRename={(t) => onRename(c.id, t)}
              onDelete={() => onDelete(c.id)}
              onStar={() => onStar(c.id)}
              onPin={() => onPin(c.id)}
              onMove={(fid) => onMove(c.id, fid)}
              onExport={() => onExport(c.id)}
            />
          ))}
          {conversations.length === 0 && (
            <div className="text-[10px] text-muted-foreground/60 px-2 py-1 italic">Empty folder</div>
          )}
        </div>
      )}

      <AlertDialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete folder &ldquo;{folder.name}&rdquo;?</AlertDialogTitle>
            <AlertDialogDescription>Conversations inside will be unassigned (not deleted).</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() => onFolderDelete(folder.id)}
            >
              Delete folder
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

// ─── Main component ────────────────────────────────────────────────────────────

export function ConversationManager({ collapsed }: { collapsed: boolean }) {
  const {
    conversations, folders, activeId, searchQuery, loading,
    load, loadFolders, setActive, setSearchQuery,
    renameConversation, deleteConversation, toggleStar, togglePin,
    moveToFolder, createFolder, renameFolder, deleteFolder, filteredConversations,
  } = useConversations();

  const [newFolderOpen, setNewFolderOpen] = useState(false);
  const [newFolderName, setNewFolderName] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const loadConversation = useChat((s) => s.loadConversation);
  const navigate = useNavigate();

  const handleSelect = async (id: number) => {
    setActive(id);
    try {
      const detail = await conversationsApi.get(id);
      const msgs = detail.messages.map((m) => ({
        id: String(m.id),
        role: m.role as "user" | "assistant",
        content: m.content,
        createdAt: m.createdAt,
      }));
      loadConversation(id, msgs);
      // Phase 15: Seed LLM memory so follow-up questions have full context
      conversationsApi.resume(id);
      navigate({ to: "/" });
    } catch {
      navigate({ to: "/" });
    }
  };

  useEffect(() => { load(); loadFolders(); }, [load, loadFolders]);

  if (collapsed) return null;

  const filtered = filteredConversations(searchQuery);
  const pinned = filtered.filter((c) => c.pinned);
  const starred = filtered.filter((c) => c.starred && !c.pinned);
  const folderConvs = (fid: number) => filtered.filter((c) => !c.pinned && !c.starred && c.folderId === fid);
  const unorganised = filtered.filter((c) => !c.pinned && !c.starred && !c.folderId);

  // Group unorganised by time
  const timeGroups: Record<string, ConversationSummary[]> = {};
  for (const conv of unorganised) {
    const group = getTimeGroup(conv.updatedAt);
    if (!timeGroups[group]) timeGroups[group] = [];
    timeGroups[group].push(conv);
  }

  const handleExport = (id: number) => { conversationsApi.exportPdf(id); };

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* ── Section header ── */}
      <div className="flex items-center justify-between px-3 pt-3 pb-1 shrink-0">
        <span className="text-[10px] uppercase tracking-widest text-muted-foreground/70 font-semibold select-none">
          Conversations
        </span>
        <div className="flex items-center gap-1">
          <button
            onClick={() => setSearchOpen((o) => !o)}
            className="p-1 rounded text-muted-foreground hover:text-foreground hover:bg-black/5 transition-colors"
            title="Search chats"
          >
            <Search className="size-3" />
          </button>
          <button
            onClick={() => setNewFolderOpen(true)}
            className="p-1 rounded text-muted-foreground hover:text-foreground hover:bg-black/5 transition-colors"
            title="New folder"
          >
            <FolderPlus className="size-3" />
          </button>
        </div>
      </div>

      {/* ── Optional search bar ── */}
      {searchOpen && (
        <div className="px-3 pb-1.5 shrink-0">
          <div className="relative">
            <Search className="absolute left-2 top-1/2 -translate-y-1/2 size-3 text-muted-foreground" />
            <Input
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search chats…"
              autoFocus
              className="h-7 pl-6 text-xs bg-white/70"
            />
            {searchQuery && (
              <button
                onClick={() => setSearchQuery("")}
                className="absolute right-1.5 top-1/2 -translate-y-1/2 text-muted-foreground"
              >
                <X className="size-3" />
              </button>
            )}
          </div>
        </div>
      )}

      {/* ── Scrollable conversation list ── */}
      <div className="flex-1 min-h-0 overflow-y-auto px-2 pb-3 space-y-0.5">
        {loading && (
          <div className="text-[11px] text-muted-foreground px-3 py-4 text-center">Loading…</div>
        )}

        {/* Pinned */}
        {pinned.length > 0 && (
          <div className="mb-1">
            <div className="text-[10px] uppercase tracking-widest text-muted-foreground/60 font-semibold px-3 pt-2 pb-0.5 flex items-center gap-1">
              <Pin className="size-2.5 rotate-45 text-blue-400" /> Pinned
            </div>
            {pinned.map((c) => (
              <ConvRow key={c.id} conv={c} active={activeId === c.id} folders={folders}
                onSelect={() => handleSelect(c.id)} onRename={(t) => renameConversation(c.id, t)}
                onDelete={() => deleteConversation(c.id)} onStar={() => toggleStar(c.id)}
                onPin={() => togglePin(c.id)} onMove={(fid) => moveToFolder(c.id, fid)}
                onExport={() => handleExport(c.id)} />
            ))}
          </div>
        )}

        {/* Starred */}
        {starred.length > 0 && (
          <div className="mb-1">
            <div className="text-[10px] uppercase tracking-widest text-muted-foreground/60 font-semibold px-3 pt-2 pb-0.5 flex items-center gap-1">
              <Star className="size-2.5 text-amber-400 fill-amber-400" /> Starred
            </div>
            {starred.map((c) => (
              <ConvRow key={c.id} conv={c} active={activeId === c.id} folders={folders}
                onSelect={() => handleSelect(c.id)} onRename={(t) => renameConversation(c.id, t)}
                onDelete={() => deleteConversation(c.id)} onStar={() => toggleStar(c.id)}
                onPin={() => togglePin(c.id)} onMove={(fid) => moveToFolder(c.id, fid)}
                onExport={() => handleExport(c.id)} />
            ))}
          </div>
        )}

        {/* Folders */}
        {folders.map((f) => {
          const fConvs = folderConvs(f.id);
          if (searchQuery && fConvs.length === 0) return null;
          return (
            <FolderSection key={f.id} folder={f} conversations={fConvs} activeId={activeId}
              folders={folders} onSelect={handleSelect} onRename={renameConversation}
              onDelete={deleteConversation} onStar={toggleStar} onPin={togglePin}
              onMove={moveToFolder} onExport={handleExport}
              onFolderRename={renameFolder} onFolderDelete={deleteFolder} />
          );
        })}

        {/* Time-grouped unorganised conversations */}
        {GROUP_ORDER.map((group) => {
          const convs = timeGroups[group];
          if (!convs || convs.length === 0) return null;
          return (
            <div key={group} className="mb-1">
              <div className="text-[10px] uppercase tracking-widest text-muted-foreground/60 font-semibold px-3 pt-2 pb-0.5">
                {group}
              </div>
              {convs.map((c) => (
                <ConvRow key={c.id} conv={c} active={activeId === c.id} folders={folders}
                  onSelect={() => handleSelect(c.id)} onRename={(t) => renameConversation(c.id, t)}
                  onDelete={() => deleteConversation(c.id)} onStar={() => toggleStar(c.id)}
                  onPin={() => togglePin(c.id)} onMove={(fid) => moveToFolder(c.id, fid)}
                  onExport={() => handleExport(c.id)} />
              ))}
            </div>
          );
        })}

        {!loading && conversations.length === 0 && (
          <div className="text-[11px] text-muted-foreground/60 px-3 py-6 text-center">
            No conversations yet.<br />Start chatting!
          </div>
        )}
      </div>

      {/* ── New folder dialog ── */}
      <Dialog open={newFolderOpen} onOpenChange={setNewFolderOpen}>
        <DialogContent className="sm:max-w-xs">
          <DialogHeader><DialogTitle>New Folder</DialogTitle></DialogHeader>
          <Input
            value={newFolderName}
            onChange={(e) => setNewFolderName(e.target.value)}
            placeholder="Folder name…"
            onKeyDown={(e) => {
              if (e.key === "Enter" && newFolderName.trim()) {
                createFolder(newFolderName.trim());
                setNewFolderName(""); setNewFolderOpen(false);
              }
            }}
            autoFocus
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setNewFolderOpen(false)}>Cancel</Button>
            <Button onClick={() => {
              if (!newFolderName.trim()) return;
              createFolder(newFolderName.trim());
              setNewFolderName(""); setNewFolderOpen(false);
            }}>Create</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
