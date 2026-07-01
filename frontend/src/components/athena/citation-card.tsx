/**
 * CitationCard  —  Phase 15 fix
 *
 * Problem: clicking a source card showed nothing because the iframe
 * loaded /documents/{id}/file which requires Authorization headers
 * that browsers can't send in iframes.
 *
 * Fix: On click, fetch a short-lived file token (POST with auth header),
 * then set the iframe src to /documents/file/{token} — no JWT needed there.
 */
import { useState, useCallback } from "react";
import { FileText, ExternalLink, Loader2 } from "lucide-react";
import { API_BASE_URL, isLive } from "@/lib/api";
import { getAccessToken } from "@/stores/auth";
import type { Source } from "@/lib/mock";
import {
  Dialog,
  DialogContent,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";

export function CitationCard({ source }: { source: Source }) {
  const [open, setOpen]           = useState(false);
  const [tokenUrl, setTokenUrl]   = useState<string | null>(null);
  const [loading, setLoading]     = useState(false);
  const [error, setError]         = useState<string | null>(null);

  const isPdf     = source.type === "pdf";
  const canPreview = isPdf && !!source.documentId && isLive;

  const handleClick = useCallback(async () => {
    if (!canPreview) return;
    setError(null);

    // Already have a token URL — just open
    if (tokenUrl) { setOpen(true); return; }

    setLoading(true);
    try {
      const tok = getAccessToken();
      const res = await fetch(
        `${API_BASE_URL}/documents/${source.documentId}/file-token`,
        {
          method: "POST",
          headers: tok ? { Authorization: `Bearer ${tok}` } : {},
        },
      );
      if (!res.ok) throw new Error("Could not get file token");
      const { token } = await res.json() as { token: string };
      setTokenUrl(`${API_BASE_URL}/documents/file/${token}`);
      setOpen(true);
    } catch (err) {
      setError("Could not load document preview.");
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [canPreview, tokenUrl, source.documentId]);

  return (
    <>
      <div
        onClick={handleClick}
        className={`athena-glass rounded-xl p-3 flex gap-3 items-center hover:bg-muted/80 transition-colors group max-w-md ${
          canPreview ? "cursor-pointer" : "cursor-default"
        }`}
      >
        {/* Icon */}
        <div
          className={`size-10 rounded grid place-items-center shrink-0 ${
            isPdf ? "bg-red-50 text-red-600" : "bg-blue-50 text-blue-600"
          }`}
        >
          {isPdf ? (
            <span className="text-[10px] font-bold">PDF</span>
          ) : (
            <ExternalLink className="size-4" />
          )}
        </div>

        {/* Info */}
        <div className="flex-1 min-w-0">
          <div className="text-xs font-medium truncate flex items-center gap-1.5">
            <FileText className="size-3 text-muted-foreground" />
            {source.title}
          </div>
          <div className="text-[10px] text-muted-foreground flex items-center gap-1 flex-wrap">
            {source.page ? `Page ${source.page} • ` : ""}Verified by Athena RAG
            {typeof source.confidence === "number" && (
              <span
                className={`ml-1 px-1.5 py-0.5 rounded-full font-medium ${
                  source.confidence >= 70
                    ? "bg-emerald-50 text-emerald-700"
                    : source.confidence >= 40
                      ? "bg-amber-50 text-amber-700"
                      : "bg-red-50 text-red-700"
                }`}
              >
                {source.confidence}% match
              </span>
            )}
          </div>
          {error && <p className="text-[10px] text-destructive mt-0.5">{error}</p>}
        </div>

        {/* Arrow / loader */}
        <div
          className={`size-6 rounded-full border grid place-items-center transition-colors ${
            canPreview
              ? "border-border group-hover:border-primary/40 group-hover:bg-primary/5"
              : "border-border opacity-30"
          }`}
          title={canPreview ? "Preview document" : "Document not available"}
        >
          {loading
            ? <Loader2 className="size-3 animate-spin text-muted-foreground" />
            : <span className="text-xs text-muted-foreground">→</span>}
        </div>
      </div>

      {/* Preview dialog */}
      {canPreview && (
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogContent className="sm:max-w-4xl h-[85vh] flex flex-col p-0 gap-0">
            <div className="flex items-center justify-between px-4 py-3 border-b border-border shrink-0">
              <DialogTitle className="truncate pr-6 text-sm font-medium">
                {source.title}
              </DialogTitle>
            </div>
            <DialogDescription className="sr-only">
              Preview of {source.title}
            </DialogDescription>
            {tokenUrl ? (
              <iframe
                src={tokenUrl}
                title={source.title}
                className="flex-1 w-full rounded-b-lg"
              />
            ) : (
              <div className="flex-1 flex items-center justify-center text-muted-foreground text-sm">
                <Loader2 className="size-5 animate-spin mr-2" /> Loading…
              </div>
            )}
          </DialogContent>
        </Dialog>
      )}
    </>
  );
}
