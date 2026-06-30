import type { LucideIcon } from "lucide-react";

export function KpiCard({
  icon: Icon,
  label,
  value,
  delta,
}: {
  icon: LucideIcon;
  label: string;
  value: string | number;
  delta?: string;
}) {
  return (
    <div className="rounded-2xl border border-border bg-card p-5 ring-1 ring-black/5 hover:shadow-md transition-shadow">
      <div className="flex items-center justify-between">
        <div className="text-xs text-muted-foreground font-medium uppercase tracking-wider">{label}</div>
        <div className="size-8 rounded-lg bg-gradient-to-br from-primary/10 to-accent/10 grid place-items-center">
          <Icon className="size-4 text-primary" />
        </div>
      </div>
      <div className="mt-4 text-3xl font-semibold tracking-tight">{value}</div>
      {delta && <div className="mt-1 text-xs text-emerald-600 font-medium">{delta}</div>}
    </div>
  );
}