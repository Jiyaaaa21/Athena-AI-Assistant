import { cn } from "@/lib/utils";

export function AthenaLogo({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "size-6 rounded-md bg-gradient-to-br from-primary to-accent shadow-sm ring-1 ring-black/5",
        className,
      )}
      aria-hidden
    />
  );
}

export function AthenaWordmark({ className }: { className?: string }) {
  return (
    <div className={cn("flex items-center gap-2.5", className)}>
      <AthenaLogo />
      <span className="font-semibold tracking-tight text-lg">Athena</span>
    </div>
  );
}