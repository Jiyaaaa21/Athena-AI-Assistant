import type { LucideIcon } from "lucide-react";

// dotClass was previously used to attach an arbitrary, meaningless
// colored dot to each chip (a different hardcoded color per chip with
// no shared logic behind it). Removed: these are actions, not statuses,
// so they no longer carry decorative color. Status color now lives only
// where it means something — see the overdue/upcoming/goal indicators
// in BriefingWidget.

export function QuickChip({
  icon: Icon,
  label,
  onClick,
}: {
  icon?: LucideIcon;
  label: string;
  onClick?: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex items-center gap-2 px-4 py-2 rounded-full border border-border bg-card shadow-sm hover:shadow-md hover:-translate-y-px transition-all text-sm font-medium"
    >
      {Icon && <Icon className="size-3.5 text-muted-foreground" />}
      {label}
    </button>
  );
}