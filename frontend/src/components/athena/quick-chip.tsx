import type { LucideIcon } from "lucide-react";

export function QuickChip({
  icon: Icon,
  label,
  onClick,
  dotClass,
}: {
  icon?: LucideIcon;
  label: string;
  onClick?: () => void;
  dotClass?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex items-center gap-2 px-4 py-2 rounded-full border border-border bg-white shadow-sm hover:shadow-md hover:-translate-y-px transition-all text-sm font-medium"
    >
      {dotClass ? <span className={`size-2 rounded-full ${dotClass}`} /> : null}
      {Icon && <Icon className="size-3.5 text-muted-foreground" />}
      {label}
    </button>
  );
}