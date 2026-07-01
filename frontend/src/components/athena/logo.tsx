import { cn } from "@/lib/utils";

// The gradient mark + halo glow are the one signature visual Athena is
// meant to be recognized by (originally only present on the login page).
// AthenaLogo/AthenaWordmark are now the single source of truth for that
// identity, so every place the brand appears — sidebar, voice mode,
// login — stays visually consistent by construction instead of each
// screen reimplementing its own version.

export function AthenaLogo({
  className,
  glow = false,
  size = "default",
}: {
  className?: string;
  glow?: boolean;
  size?: "default" | "lg";
}) {
  return (
    <span className={cn("relative inline-flex shrink-0", className)}>
      {glow && (
        <span
          aria-hidden
          className="absolute inset-0 rounded-md athena-halo scale-[3]"
        />
      )}
      <span
        className={cn(
          "relative rounded-md bg-gradient-to-br from-primary to-accent shadow-sm ring-1 ring-black/5",
          size === "lg" ? "size-8" : "size-6",
        )}
        aria-hidden
      />
    </span>
  );
}

export function AthenaWordmark({
  className,
  glow = false,
  size = "default",
}: {
  className?: string;
  glow?: boolean;
  /** "default" matches the sidebar; "lg" is for standalone brand moments like login. */
  size?: "default" | "lg";
}) {
  return (
    <div className={cn("flex items-center gap-2.5", className)}>
      <AthenaLogo glow={glow} size={size} />
      <span
        className={cn(
          "font-semibold tracking-tight athena-gradient-text",
          size === "lg" ? "text-3xl" : "text-lg",
        )}
      >
        Athena
      </span>
    </div>
  );
}