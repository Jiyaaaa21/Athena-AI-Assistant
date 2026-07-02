import { Menu } from "lucide-react";
import { useEffect, useState } from "react";
import { useRouterState } from "@tanstack/react-router";
import { AthenaWordmark } from "./logo";
import {
  Sheet,
  SheetContent,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { AppSidebar } from "./app-sidebar";

export function MobileTopbar() {
  // The Sheet below was uncontrolled: AppSidebar's nav Links navigate via
  // the router but have no idea the sidebar is currently rendered inside a
  // mobile drawer, so they never told the Sheet to close. On desktop that's
  // irrelevant (AppSidebar renders inline, no Sheet involved), but on
  // mobile every tap on Documents/Notes/etc. navigated correctly *behind*
  // the still-open drawer, which then sat there covering most of the
  // screen until the person manually swiped/tapped it away.
  //
  // Fix: control the Sheet's open state here and close it any time the
  // route actually changes, regardless of which link inside AppSidebar
  // triggered the navigation.
  const [open, setOpen] = useState(false);
  const pathname = useRouterState({ select: (s) => s.location.pathname });

  useEffect(() => {
    setOpen(false);
  }, [pathname]);

  return (
    <div className="md:hidden flex items-center justify-between px-4 h-14 border-b border-border bg-background sticky top-0 z-30">
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetTrigger asChild>
          <button aria-label="Open menu" className="p-2 rounded-md hover:bg-muted">
            <Menu className="size-4" />
          </button>
        </SheetTrigger>
        <SheetContent side="left" className="p-0 w-72">
          <SheetTitle className="sr-only">Navigation</SheetTitle>
          <div className="[&>aside]:flex [&>aside]:h-svh [&>aside]:w-72">
            <AppSidebar onNavigate={() => setOpen(false)} />
          </div>
        </SheetContent>
      </Sheet>
      <AthenaWordmark />
      <div className="size-8" />
    </div>
  );
}