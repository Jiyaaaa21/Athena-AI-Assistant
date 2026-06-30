/* Mock data + helpers for Athena front-end before backend is wired. */

export type Source = {
  id: string;
  title: string;
  page?: number;
  type: "pdf" | "url";
  confidence?: number | null;
  documentId?: string | null;
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  createdAt: string | null;
  sources?: Source[];
  streaming?: boolean;
  // In-chat image upload preview fields
  imagePreview?: string;
  imageFilename?: string;
  // Agent that handled this message
  agentName?: string;
};

export type DocItem = {
  id: string;
  name: string;
  size: number;
  uploadedAt: string | null;
  status: "processed" | "processing" | "failed";
  pages: number;
  chunkCount: number;
};

export type NoteItem = {
  id: string;
  title: string;
  body: string;
  category: string;
  tags: string[];
  pinned: boolean;
  createdAt: string | null;
  updatedAt: string | null;
};

export type ReminderItem = {
  id: string;
  title: string;
  dueAt: string | null;
  done: boolean;
  priority: "low" | "medium" | "high";
  createdAt: string | null;
};

// ── Mock helpers ──────────────────────────────────────────────────────────────

export function fakeAssistantReply(
  message: string,
  _history: { role: string; content: string }[],
): { reply: string; sources?: Source[] } {
  const lower = message.toLowerCase();
  if (lower.includes("document") || lower.includes("pdf") || lower.includes("upload")) {
    return {
      reply: "I can search through your uploaded documents. Try uploading a PDF from the Documents page first!",
      sources: [],
    };
  }
  if (lower.includes("remind") || lower.includes("reminder")) {
    return { reply: "I've noted that reminder for you. You can view and manage all reminders on the Reminders page." };
  }
  if (lower.includes("note") || lower.includes("notes")) {
    return { reply: "Got it! That note has been saved. Head to the Notes page to view all your notes." };
  }
  if (lower.includes("weather")) {
    return { reply: "Check the Weather page for live conditions and forecasts for your location." };
  }
  if (lower.includes("news")) {
    return { reply: "Head to the News page to see the latest headlines across technology, business, and more." };
  }
  return {
    reply: `I'm Athena, your AI assistant. You said: "${message}". Connect the backend to get real responses from the multi-agent system.`,
  };
}

// ── Static mock collections ───────────────────────────────────────────────────

export function documents(): DocItem[] {
  return [
    { id: "1", name: "Q3_Report.pdf", size: 204800, uploadedAt: "2024-10-01T10:00:00Z", status: "processed", pages: 12, chunkCount: 48 },
    { id: "2", name: "Research_Paper.pdf", size: 512000, uploadedAt: "2024-10-05T14:30:00Z", status: "processed", pages: 24, chunkCount: 96 },
  ];
}

export function notes(): NoteItem[] {
  return [
    { id: "1", title: "Project Ideas", body: "Build an AI-powered notes app with semantic search and auto-categorisation.", category: "Work", tags: ["ai", "product"], pinned: true, createdAt: "2024-10-01T09:00:00Z", updatedAt: "2024-10-02T10:00:00Z" },
    { id: "2", title: "Book Recommendations", body: "Thinking Fast and Slow, The Pragmatic Programmer, Clean Code.", category: "Personal", tags: ["books", "learning"], pinned: false, createdAt: "2024-09-28T15:00:00Z", updatedAt: "2024-09-28T15:00:00Z" },
  ];
}

export function reminders(): ReminderItem[] {
  return [
    { id: "1", title: "Review Q3 Report", dueAt: "2024-10-15T09:00:00Z", done: false, priority: "high", createdAt: "2024-10-01T08:00:00Z" },
    { id: "2", title: "Team standup", dueAt: "2024-10-10T10:00:00Z", done: true, priority: "medium", createdAt: "2024-09-30T12:00:00Z" },
  ];
}

// ── Missing types that api.ts references ──────────────────────────────────────
// These were referenced in api.ts but never defined in mock.ts, causing
// 25 TypeScript errors. Added here as pure additions — nothing changed above.

/** Alias for NoteItem — api.ts uses mock.Note */
export type Note = NoteItem & { body: string };

/** Alias for ReminderItem — api.ts uses mock.Reminder */
export type Reminder = {
  id: string;
  title: string;
  dueAt: string;
  done: boolean;
  priority: "low" | "med" | "high" | null;
  category: string | null;
  overdue?: boolean;
};

export type NewsItem = {
  id: string;
  title: string;
  summary: string;
  url: string;
  source: string;
  category: string;
  publishedAt: string | null;
  imageUrl?: string | null;
};

export type Weather = {
  city: string;
  temperature: number;
  feels_like: number;
  humidity: number;
  description: string;
  icon: string;
  wind_speed: number;
  country: string;
};

export type Memory = {
  id: string;
  label: string;
  role: "user" | "assistant";
  category: string;
};

export type Analytics = {
  conversations: { total: number; thisWeek: number };
  documents: { total: number; thisWeek: number };
  notes: { total: number; thisWeek: number };
  reminders: { total: number; dueSoon: number };
  activity: { date: string; conversations: number; documents: number; notes: number }[];
  messages_sent?: { total: number; thisWeek: number };
  tool_usage?: { tool: string; count: number }[];
  top_features?: { feature: string; count: number; pct: number }[];
  weekly_trend?: { week: string; label: string; conversations: number; documents: number; notes: number; reminders: number }[];
  monthly_trend?: { month: string; label: string; conversations: number; documents: number; notes: number }[];
  heatmap?: { day: number; dayLabel: string; hours: number[] }[];
  hourly_distribution?: { hour: number; count: number }[];
  streak?: number;
  avg_messages_per_day?: number;
  reminders_active?: number;
};

// ── Missing mock data functions ───────────────────────────────────────────────

export function news(category?: string): NewsItem[] {
  const items: NewsItem[] = [
    {
      id: "1", title: "AI Breakthroughs Reshape Tech Industry",
      summary: "Large language models continue to advance at an unprecedented pace.",
      url: "#", source: "TechCrunch", category: "technology",
      publishedAt: new Date(Date.now() - 3600000).toISOString(), imageUrl: null,
    },
    {
      id: "2", title: "Global Markets Rally on Strong Earnings",
      summary: "Stocks rise as major companies report better-than-expected results.",
      url: "#", source: "Reuters", category: "business",
      publishedAt: new Date(Date.now() - 7200000).toISOString(), imageUrl: null,
    },
    {
      id: "3", title: "New Climate Agreement Signed",
      summary: "World leaders commit to ambitious carbon reduction targets.",
      url: "#", source: "BBC", category: "world",
      publishedAt: new Date(Date.now() - 10800000).toISOString(), imageUrl: null,
    },
  ];
  if (category && category !== "all") {
    return items.filter((i) => i.category === category);
  }
  return items;
}

export function weather(city: string): Weather {
  return {
    city: city || "Delhi",
    temperature: 28,
    feels_like: 31,
    humidity: 65,
    description: "Partly cloudy",
    icon: "02d",
    wind_speed: 12,
    country: "IN",
  };
}

export function memories(): Memory[] {
  return [
    { id: "1", label: "Working on Athena, a personal AI OS.", role: "user", category: "Projects" },
    { id: "2", label: "Prefers concise, action-oriented responses.", role: "user", category: "Preferences" },
    { id: "3", label: "Interested in machine learning and AI research.", role: "user", category: "Learning" },
    { id: "4", label: "Target: secure an AI internship.", role: "user", category: "Goals" },
  ];
}

export function analytics(): Analytics {
  const days = Array.from({ length: 14 }, (_, i) => {
    const d = new Date(Date.now() - (13 - i) * 86400000);
    return {
      date: d.toISOString().split("T")[0],
      conversations: Math.floor(Math.random() * 8),
      documents: Math.floor(Math.random() * 2),
      notes: Math.floor(Math.random() * 3),
    };
  });
  return {
    conversations: { total: 42, thisWeek: 8 },
    documents: { total: 5, thisWeek: 1 },
    notes: { total: 12, thisWeek: 3 },
    reminders: { total: 6, dueSoon: 2 },
    activity: days,
    messages_sent: { total: 84, thisWeek: 16 },
    streak: 4,
    avg_messages_per_day: 2.8,
    reminders_active: 4,
  };
}