import { useEffect, useState, useRef } from "react";
import { useNavigate } from "@tanstack/react-router";
import {
  CommandDialog, CommandEmpty, CommandGroup,
  CommandInput, CommandItem, CommandList, CommandSeparator,
} from "@/components/ui/command";
import {
  MessageSquare, FileText, StickyNote, Bell, Newspaper,
  CloudSun, BarChart3, Brain, Settings, Plus, Search,
  Loader2,
} from "lucide-react";
import { useChat } from "@/stores/chat";
import { searchApi, type SearchResult } from "@/lib/api";
import { Badge } from "@/components/ui/badge";

const SOURCE_ICONS: Record<string, typeof Search> = {
  notes: StickyNote, reminders: Bell, memory: Brain, documents: FileText,
};
const SOURCE_LABELS: Record<string, string> = {
  notes: "Note", reminders: "Reminder", memory: "Memory", documents: "Document",
};
const SOURCE_ROUTES: Record<string, string> = {
  notes: "/notes", reminders: "/reminders", memory: "/memory", documents: "/documents",
};

export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [inputValue, setInputValue] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const navigate = useNavigate();
  const resetChat = useChat((s) => s.reset);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault(); setOpen((o) => !o);
      }
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "n") {
        e.preventDefault(); resetChat(); navigate({ to: "/" });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [navigate, resetChat]);

  // Debounced live search
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    const q = inputValue.trim();
    if (q.length < 2) { setSearchResults([]); return; }

    debounceRef.current = setTimeout(async () => {
      setSearching(true);
      try {
        const res = await searchApi.global({ q, limit: 4 });
        setSearchResults(res.results);
      } catch {
        setSearchResults([]);
      } finally {
        setSearching(false);
      }
    }, 350);
  }, [inputValue]);

  const go = (to: string) => { setOpen(false); navigate({ to }); };

  const goResult = (r: SearchResult) => {
    setOpen(false);
    const route = SOURCE_ROUTES[r.source] ?? "/";
    navigate({ to: route });
  };

  return (
    <CommandDialog open={open} onOpenChange={setOpen}>
      <CommandInput
        placeholder="Navigate or search your workspace…"
        value={inputValue}
        onValueChange={setInputValue}
      />
      <CommandList>
        <CommandEmpty>
          {searching ? (
            <div className="flex items-center gap-2 justify-center py-2 text-muted-foreground text-sm">
              <Loader2 className="size-3.5 animate-spin" /> Searching…
            </div>
          ) : (
            "No results."
          )}
        </CommandEmpty>

        {/* Live search results */}
        {searchResults.length > 0 && (
          <>
            <CommandGroup heading="Search Results">
              {searchResults.map((r) => {
                const Icon = SOURCE_ICONS[r.source] ?? Search;
                return (
                  <CommandItem key={`${r.source}-${r.id}`} onSelect={() => goResult(r)} className="gap-2">
                    <Icon className="size-4 shrink-0 text-muted-foreground" />
                    <span className="flex-1 truncate">{r.title}</span>
                    <Badge variant="outline" className="text-[10px] px-1.5 py-0 shrink-0">
                      {SOURCE_LABELS[r.source]}
                    </Badge>
                  </CommandItem>
                );
              })}
              {inputValue.trim().length >= 2 && (
                <CommandItem
                  onSelect={() => { setOpen(false); navigate({ to: "/search", hash: encodeURIComponent(inputValue.trim()) }); }}
                  className="gap-2 text-primary"
                >
                  <Search className="size-4" />
                  See all results for "{inputValue.trim()}"
                </CommandItem>
              )}
            </CommandGroup>
            <CommandSeparator />
          </>
        )}

        <CommandGroup heading="Actions">
          <CommandItem onSelect={() => { resetChat(); go("/"); }}>
            <Plus className="size-4" /> New Chat
          </CommandItem>
          <CommandItem onSelect={() => go("/search")}>
            <Search className="size-4" /> Global Search
          </CommandItem>
        </CommandGroup>

        <CommandGroup heading="Navigate">
          <CommandItem onSelect={() => go("/")}><MessageSquare className="size-4" /> Chat</CommandItem>
          <CommandItem onSelect={() => go("/documents")}><FileText className="size-4" /> Documents</CommandItem>
          <CommandItem onSelect={() => go("/notes")}><StickyNote className="size-4" /> Notes</CommandItem>
          <CommandItem onSelect={() => go("/reminders")}><Bell className="size-4" /> Reminders</CommandItem>
          <CommandItem onSelect={() => go("/news")}><Newspaper className="size-4" /> News</CommandItem>
          <CommandItem onSelect={() => go("/weather")}><CloudSun className="size-4" /> Weather</CommandItem>
          <CommandItem onSelect={() => go("/analytics")}><BarChart3 className="size-4" /> Analytics</CommandItem>
          <CommandItem onSelect={() => go("/memory")}><Brain className="size-4" /> Memory</CommandItem>
          <CommandItem onSelect={() => go("/settings")}><Settings className="size-4" /> Settings</CommandItem>
        </CommandGroup>
      </CommandList>
    </CommandDialog>
  );
}
