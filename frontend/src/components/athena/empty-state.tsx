import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

const TONE_CLASSES = {
  // Default — same gradient tile as before, used where no page-specific
  // meaning applies (e.g. a generic "no results" state).
  neutral: "from-primary/10 to-accent/10 text-primary",
  // Page-relevant accents so empty states have a little more life without
  // becoming decoration — same shared layout, a different accent color.
  info: "from-blue-500/10 to-blue-500/5 text-blue-600 dark:text-blue-400",
  warning: "from-amber-500/10 to-amber-500/5 text-amber-600 dark:text-amber-400",
  success: "from-emerald-500/10 to-emerald-500/5 text-emerald-600 dark:text-emerald-400",
  danger: "from-red-500/10 to-red-500/5 text-red-600 dark:text-red-400",
  accent: "from-accent/15 to-accent/5 text-accent",
} as const;

// The dashed, tinted card wrapper — matches the tile's tone so the whole
// empty state reads as one cohesive, page-relevant surface instead of a
// bare icon floating on the page background.
const WRAPPER_CLASSES = {
  neutral: "border-border bg-gradient-to-b from-primary/[0.03] to-transparent",
  info: "border-blue-200 dark:border-blue-900/50 bg-gradient-to-b from-blue-500/[0.04] to-transparent",
  warning: "border-amber-200 dark:border-amber-900/50 bg-gradient-to-b from-amber-500/[0.04] to-transparent",
  success: "border-emerald-200 dark:border-emerald-900/50 bg-gradient-to-b from-emerald-500/[0.04] to-transparent",
  danger: "border-red-200 dark:border-red-900/50 bg-gradient-to-b from-red-500/[0.04] to-transparent",
  accent: "border-accent/30 bg-gradient-to-b from-accent/[0.04] to-transparent",
} as const;

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  tone = "neutral",
}: {
  icon: LucideIcon;
  title: string;
  description?: string;
  action?: ReactNode;
  tone?: keyof typeof TONE_CLASSES;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center text-center py-14 px-6 rounded-2xl border border-dashed max-w-lg mx-auto",
        WRAPPER_CLASSES[tone],
      )}
    >
      <div
        className={cn(
          "size-12 rounded-2xl bg-gradient-to-br grid place-items-center mb-4 ring-1 ring-border",
          TONE_CLASSES[tone],
        )}
      >
        <Icon className="size-5" />
      </div>
      <h3 className="text-base font-semibold tracking-tight">{title}</h3>
      {description && (
        <p className="text-sm text-muted-foreground mt-1 max-w-sm">{description}</p>
      )}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}