import { Menu } from "lucide-react";
import { AthenaWordmark } from "./logo";
import {
  Sheet,
  SheetContent,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { AppSidebar } from "./app-sidebar";

export function MobileTopbar() {
  return (
    <div className="md:hidden flex items-center justify-between px-4 h-14 border-b border-border bg-background sticky top-0 z-30">
      <Sheet>
        <SheetTrigger asChild>
          <button aria-label="Open menu" className="p-2 rounded-md hover:bg-muted">
            <Menu className="size-4" />
          </button>
        </SheetTrigger>
        <SheetContent side="left" className="p-0 w-72">
          <SheetTitle className="sr-only">Navigation</SheetTitle>
          <div className="[&>aside]:flex [&>aside]:h-svh [&>aside]:w-72">
            <AppSidebar />
          </div>
        </SheetContent>
      </Sheet>
      <AthenaWordmark />
      <div className="size-8" />
    </div>
  );
}