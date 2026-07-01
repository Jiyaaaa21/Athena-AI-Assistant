/**
 * AppSidebar — Sidebar with collapsible nav sections + ChatGPT-style conversation list.
 * Changes (Issue #1):
 *  - Knowledge and Live nav sections are now collapsible (toggle open/closed).
 *  - ConversationManager is given flex-1 so it fills available vertical space.
 *  - Agent Panel moved into collapsible section to save space.
 */
import { Link, useRouterState, useNavigate } from "@tanstack/react-router";
import { ConversationManager } from "./conversation-manager";
import { AgentPanel } from "./agent-panel";
import {
  MessageSquare, FileText, StickyNote, Bell, Newspaper, CloudSun,
  BarChart3, Brain, Settings, Plus, PanelLeftClose, PanelLeft, Search, LogOut,
  ChevronDown, ChevronRight, Cpu, Target, Zap,
} from "lucide-react";
import { useState } from "react";
import { useSidebar } from "@/stores/sidebar";
import { useChat } from "@/stores/chat";
import { useAuth } from "@/stores/auth";
import { AthenaWordmark, AthenaLogo } from "./logo";
import { cn } from "@/lib/utils";
import { Input } from "@/components/ui/input";

const NAV_PRIMARY = [
  { to: "/",          label: "Chat",      icon: MessageSquare },
  { to: "/search",    label: "Search",    icon: Search },
] as const;

const NAV_KNOWLEDGE = [
  { to: "/documents", label: "Documents", icon: FileText },
  { to: "/notes",     label: "Notes",     icon: StickyNote },
  { to: "/reminders", label: "Reminders", icon: Bell },
  { to: "/goals",     label: "Goals & Projects", icon: Target },
  { to: "/routines",  label: "Routines",  icon: Zap },
  { to: "/memory",    label: "Memory",    icon: Brain },
] as const;

const NAV_LIVE = [
  { to: "/news",      label: "News",      icon: Newspaper },
  { to: "/weather",   label: "Weather",   icon: CloudSun },
  { to: "/analytics", label: "Analytics", icon: BarChart3 },
] as const;

export function AppSidebar() {
  const { collapsed, toggle } = useSidebar();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const resetChat = useChat((s) => s.reset);
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const [q, setQ] = useState("");

  // Collapsible section state
  const [knowledgeOpen, setKnowledgeOpen] = useState(true);
  const [liveOpen, setLiveOpen] = useState(false);
  const [agentOpen, setAgentOpen] = useState(false);

  const handleLogout = async () => {
    await logout();
    navigate({ to: "/login" });
  };

  const handleSearchKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && q.trim()) {
      navigate({ to: "/search", hash: encodeURIComponent(q.trim()) });
      setQ("");
    }
  };

  return (
    <aside
      className={cn(
        "hidden md:flex h-svh sticky top-0 bg-sidebar border-r border-border flex-col shrink-0 transition-[width] duration-300 ease-out",
        collapsed ? "w-[68px]" : "w-60",
      )}
    >
      {/* ── Header ── */}
      <div className="flex items-center justify-between px-4 pt-4 pb-2 shrink-0">
        {collapsed ? <AthenaLogo /> : <AthenaWordmark />}
        <button
          onClick={toggle}
          className="text-muted-foreground hover:text-foreground p-1 rounded-md hover:bg-muted"
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? <PanelLeft className="size-4" /> : <PanelLeftClose className="size-4" />}
        </button>
      </div>

      {/* ── New Chat + Search ── */}
      <div className="px-3 mt-1 space-y-2 shrink-0">
        <Link
          to="/"
          onClick={() => resetChat()}
          className="w-full flex items-center justify-between bg-card border border-border px-3 py-2 rounded-lg text-sm font-medium shadow-xs hover:border-primary/30 transition-colors"
        >
          <span className="flex items-center gap-2">
            <Plus className="size-4 text-primary" />
            {!collapsed && "New Chat"}
          </span>
          {!collapsed && (
            <span className="text-muted-foreground font-mono text-[10px]">⌘N</span>
          )}
        </Link>

        {!collapsed && (
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 size-3.5 text-muted-foreground" />
            <Input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={handleSearchKey}
              placeholder="Search… (Enter)"
              className="h-8 pl-8 text-xs bg-card"
            />
          </div>
        )}
      </div>

      {/* ── Static nav (Main) ── */}
      <nav className="px-3 mt-3 shrink-0 space-y-0.5">
        {NAV_PRIMARY.filter((i) =>
          q ? i.label.toLowerCase().includes(q.toLowerCase()) : true
        ).map((item) => {
          const Icon = item.icon;
          const active = pathname === item.to;
          return (
            <Link
              key={item.to}
              to={item.to}
              className={cn(
                "flex items-center gap-3 px-3 py-1.5 rounded-md text-sm transition-colors",
                active
                  ? "athena-nav-active"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground",
                collapsed && "justify-center",
              )}
              title={collapsed ? item.label : undefined}
            >
              <Icon className="size-4 shrink-0" />
              {!collapsed && item.label}
            </Link>
          );
        })}
      </nav>

      {/* ── Collapsible: Knowledge ── */}
      {!collapsed && (
        <div className="px-3 mt-2 shrink-0">
          <button
            onClick={() => setKnowledgeOpen((o) => !o)}
            className="flex items-center justify-between w-full px-3 py-1 text-[10px] uppercase tracking-widest text-muted-foreground/70 font-semibold hover:text-muted-foreground transition-colors rounded-md hover:bg-muted"
          >
            <span>Knowledge</span>
            {knowledgeOpen
              ? <ChevronDown className="size-3" />
              : <ChevronRight className="size-3" />}
          </button>
          {knowledgeOpen && (
            <div className="mt-0.5 space-y-0.5">
              {NAV_KNOWLEDGE.filter((i) =>
                q ? i.label.toLowerCase().includes(q.toLowerCase()) : true
              ).map((item) => {
                const Icon = item.icon;
                const active = pathname === item.to;
                return (
                  <Link
                    key={item.to}
                    to={item.to}
                    className={cn(
                      "flex items-center gap-3 px-3 py-1.5 rounded-md text-sm transition-colors",
                      active
                        ? "athena-nav-active"
                        : "text-muted-foreground hover:bg-muted hover:text-foreground",
                    )}
                  >
                    <Icon className="size-4 shrink-0" />
                    {item.label}
                  </Link>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* Collapsed: Knowledge icons with divider */}
      {collapsed && (
        <div className="px-3 mt-2 space-y-0.5 shrink-0">
          <div className="my-1 border-t border-border/40" />
          {NAV_KNOWLEDGE.map((item) => {
            const Icon = item.icon;
            const active = pathname === item.to;
            return (
              <Link
                key={item.to}
                to={item.to}
                className={cn(
                  "flex items-center justify-center px-3 py-1.5 rounded-md text-sm transition-colors",
                  active
                    ? "athena-nav-active"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground",
                )}
                title={item.label}
              >
                <Icon className="size-4 shrink-0" />
              </Link>
            );
          })}
        </div>
      )}

      {/* ── Collapsible: Live ── */}
      {!collapsed && (
        <div className="px-3 mt-2 shrink-0">
          <button
            onClick={() => setLiveOpen((o) => !o)}
            className="flex items-center justify-between w-full px-3 py-1 text-[10px] uppercase tracking-widest text-muted-foreground/70 font-semibold hover:text-muted-foreground transition-colors rounded-md hover:bg-muted"
          >
            <span>Live</span>
            {liveOpen
              ? <ChevronDown className="size-3" />
              : <ChevronRight className="size-3" />}
          </button>
          {liveOpen && (
            <div className="mt-0.5 space-y-0.5">
              {NAV_LIVE.filter((i) =>
                q ? i.label.toLowerCase().includes(q.toLowerCase()) : true
              ).map((item) => {
                const Icon = item.icon;
                const active = pathname === item.to;
                return (
                  <Link
                    key={item.to}
                    to={item.to}
                    className={cn(
                      "flex items-center gap-3 px-3 py-1.5 rounded-md text-sm transition-colors",
                      active
                        ? "athena-nav-active"
                        : "text-muted-foreground hover:bg-muted hover:text-foreground",
                    )}
                  >
                    <Icon className="size-4 shrink-0" />
                    {item.label}
                  </Link>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* Collapsed: Live icons */}
      {collapsed && (
        <div className="px-3 mt-1 space-y-0.5 shrink-0">
          <div className="my-1 border-t border-border/40" />
          {NAV_LIVE.map((item) => {
            const Icon = item.icon;
            const active = pathname === item.to;
            return (
              <Link
                key={item.to}
                to={item.to}
                className={cn(
                  "flex items-center justify-center px-3 py-1.5 rounded-md text-sm transition-colors",
                  active
                    ? "athena-nav-active"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground",
                )}
                title={item.label}
              >
                <Icon className="size-4 shrink-0" />
              </Link>
            );
          })}
        </div>
      )}

      {/* ── Collapsible: Agent Ecosystem ── */}
      {!collapsed && (
        <div className="px-3 mt-2 shrink-0">
          <button
            onClick={() => setAgentOpen((o) => !o)}
            className="flex items-center justify-between w-full px-3 py-1 text-[10px] uppercase tracking-widest text-muted-foreground/70 font-semibold hover:text-muted-foreground transition-colors rounded-md hover:bg-muted"
          >
            <span className="flex items-center gap-1.5">
              <Cpu className="size-3 text-primary/60" />
              Agent Ecosystem
            </span>
            {agentOpen
              ? <ChevronDown className="size-3" />
              : <ChevronRight className="size-3" />}
          </button>
          {agentOpen && (
            <div className="mt-1 pb-1">
              <AgentPanel />
            </div>
          )}
        </div>
      )}

      {/* ── Conversation list — takes remaining space ── */}
      <div className="flex-1 min-h-0 overflow-hidden">
        <ConversationManager collapsed={collapsed} />
      </div>

      {/* ── Footer: Settings + User ── */}
      <div className="px-3 pb-4 pt-2 border-t border-border/60 shrink-0">
        <Link
          to="/settings"
          className={cn(
            "flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors",
            pathname === "/settings"
              ? "athena-nav-active"
              : "text-muted-foreground hover:bg-muted hover:text-foreground",
            collapsed && "justify-center",
          )}
          title={collapsed ? "Settings" : undefined}
        >
          <Settings className="size-4 shrink-0" />
          {!collapsed && "Settings"}
        </Link>
        {!collapsed && (
          <div className="mt-2 p-2 bg-card/60 rounded-lg border border-border/60 flex items-center gap-2">
            <div className="size-7 rounded-full bg-gradient-to-br from-primary/30 to-accent/30 ring-1 ring-black/5 shrink-0" />
            <div className="flex flex-col min-w-0 flex-1">
              <span className="text-xs font-medium truncate">{user?.name ?? "Athena User"}</span>
              <span className="text-[10px] text-muted-foreground truncate">{user?.email ?? ""}</span>
            </div>
            <button
              onClick={handleLogout}
              title="Sign out"
              className="shrink-0 p-1 rounded text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
            >
              <LogOut className="size-3.5" />
            </button>
          </div>
        )}
      </div>
    </aside>
  );
}
