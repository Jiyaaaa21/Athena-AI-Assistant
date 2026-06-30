/**
 * Phase 8: Export Menu
 *
 * A reusable dropdown for exporting data in various formats.
 * Renders differently depending on the `type` prop.
 */

import { Download, FileText, FileType, Hash } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { exportApi } from "@/lib/api";
import { toast } from "sonner";
import { isLive } from "@/lib/api";

type ExportType = "notes" | "memories" | "documentSummary";

interface ExportMenuProps {
  type: ExportType;
  docId?: string;           // required when type === "documentSummary"
  label?: string;
  variant?: "outline" | "ghost" | "default";
  size?: "sm" | "default" | "icon";
}

const ICONS: Record<string, typeof FileText> = {
  pdf: FileText,
  txt: Hash,
  md: FileType,
};

function notAvailable() {
  toast.info("Connect to a live backend to export.");
}

export function ExportMenu({
  type,
  docId,
  label = "Export",
  variant = "outline",
  size = "sm",
}: ExportMenuProps) {
  const showFormats = type !== "documentSummary";

  const handleExport = (fmt: "pdf" | "txt" | "md") => {
    if (!isLive) { notAvailable(); return; }
    if (type === "notes") exportApi.notes(fmt);
    else if (type === "memories") exportApi.memories(fmt);
  };

  const handleDocExport = () => {
    if (!isLive) { notAvailable(); return; }
    if (docId) exportApi.documentSummary(docId);
  };

  if (type === "documentSummary") {
    return (
      <Button variant={variant} size={size} onClick={handleDocExport} className="gap-1.5">
        <Download className="size-3.5" />
        {label}
      </Button>
    );
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant={variant} size={size} className="gap-1.5">
          <Download className="size-3.5" />
          {label}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-40">
        <DropdownMenuLabel className="text-xs">Export format</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {(["pdf", "txt", "md"] as const).map((fmt) => {
          const Icon = ICONS[fmt] ?? FileText;
          return (
            <DropdownMenuItem key={fmt} onClick={() => handleExport(fmt)}>
              <Icon className="size-3.5 mr-2" />
              {fmt === "pdf" ? "PDF Document" : fmt === "txt" ? "Plain Text" : "Markdown"}
            </DropdownMenuItem>
          );
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
