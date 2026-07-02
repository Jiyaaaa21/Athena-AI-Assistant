import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  FileText, Upload, Trash2, Search, Loader2, CheckCircle2,
  Eye, Layers, ChevronDown, ChevronUp, Info, X,
} from "lucide-react";
import { PageHeader } from "@/components/athena/page-header";
import { ExportMenu } from "@/components/athena/export-menu";
import { EmptyState } from "@/components/athena/empty-state";
import { documentsApi, searchApi, API_BASE_URL, isLive, type DocumentChunk } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import { motion } from "framer-motion";
import type { DocItem } from "@/lib/mock";
import {
  Dialog, DialogContent, DialogTitle, DialogDescription,
} from "@/components/ui/dialog";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/documents")({
  head: () => ({
    meta: [
      { title: "Athena — Documents" },
      { name: "description", content: "Upload PDFs and let Athena retrieve answers grounded in your knowledge base." },
    ],
  }),
  component: DocumentsPage,
});

// ── Highlight renderer ───────────────────────────────────────────────────────

function HighlightedText({ text, spans }: { text: string; spans: [number, number][] }) {
  if (!spans.length) return <span>{text}</span>;
  const parts: React.ReactNode[] = [];
  let cursor = 0;
  for (const [start, end] of spans) {
    if (start > cursor) parts.push(<span key={cursor}>{text.slice(cursor, start)}</span>);
    parts.push(
      <mark key={start} className="bg-yellow-200 dark:bg-yellow-800/60 text-foreground rounded-sm px-0.5 font-medium">
        {text.slice(start, end)}
      </mark>
    );
    cursor = end;
  }
  if (cursor < text.length) parts.push(<span key={cursor}>{text.slice(cursor)}</span>);
  return <>{parts}</>;
}

// ── Document detail dialog ───────────────────────────────────────────────────

function DocumentDetailDialog({
  doc,
  open,
  onClose,
}: {
  doc: DocItem | null;
  open: boolean;
  onClose: () => void;
}) {
  const [chunkQuery, setChunkQuery] = useState("");
  const [committedChunkQ, setCommittedChunkQ] = useState("");
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [expandedChunk, setExpandedChunk] = useState<number | null>(null);

  const handleChunkQ = (v: string) => {
    setChunkQuery(v);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => setCommittedChunkQ(v.trim()), 500);
  };

  const { data: chunksData, isFetching: chunksFetching } = useQuery({
    queryKey: ["doc-chunks", doc?.id, committedChunkQ],
    queryFn: () => searchApi.documentChunks(doc!.id, committedChunkQ, 6),
    enabled: !!doc && committedChunkQ.length >= 2,
    staleTime: 30_000,
  });

  const [previewUrl, setPreviewUrl] = useState<string | null>(null);

  useEffect(() => {
    setPreviewUrl(null);
    if (!doc || !isLive) return;
    let cancelled = false;
    documentsApi.fileToken(doc.id).then(({ token }) => {
      if (!cancelled) setPreviewUrl(`${API_BASE_URL}/documents/file/${token}`);
    });
    return () => {
      cancelled = true;
    };
  }, [doc?.id]);

  if (!doc) return null;

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-4xl max-h-[90vh] flex flex-col gap-0 p-0 overflow-hidden">
        {/* Header */}
        <div className="flex items-start gap-3 px-6 pt-5 pb-4 border-b border-border shrink-0">
          <div className="size-10 rounded-lg bg-red-50 text-red-600 grid place-items-center text-xs font-bold shrink-0">PDF</div>
          <div className="flex-1 min-w-0">
            <DialogTitle className="truncate text-base leading-tight">{doc.name}</DialogTitle>
            <DialogDescription className="text-xs mt-0.5">
              {doc.pages} pages · {(doc.size / 1024 / 1024).toFixed(1)} MB
              {doc.chunkCount > 0 && ` · ${doc.chunkCount} indexed chunks`}
              {doc.uploadedAt && ` · Uploaded ${new Date(doc.uploadedAt).toLocaleDateString()}`}
            </DialogDescription>
          </div>
        </div>

        {/* Document metadata badges */}
        <div className="flex flex-wrap gap-2 px-6 py-2 border-b border-border bg-muted/30 shrink-0">
          <Badge variant="outline" className="text-[10px]">
            {doc.status === "processed" ? "✓ Indexed" : doc.status}
          </Badge>
          <Badge variant="outline" className="text-[10px]">{doc.pages} pages</Badge>
          <Badge variant="outline" className="text-[10px]">{doc.chunkCount} chunks</Badge>
          <Badge variant="outline" className="text-[10px]">{(doc.size / 1024 / 1024).toFixed(2)} MB</Badge>
        </div>

        {/* Tabs */}
        <Tabs defaultValue="preview" className="flex-1 overflow-hidden flex flex-col">
          <TabsList className="mx-6 mt-3 self-start shrink-0">
            <TabsTrigger value="preview" className="text-xs gap-1.5"><Eye className="size-3.5" /> Preview</TabsTrigger>
            <TabsTrigger value="chunks" className="text-xs gap-1.5"><Layers className="size-3.5" /> Semantic Search</TabsTrigger>
          </TabsList>

          {/* PDF Preview */}
          <TabsContent value="preview" className="flex-1 overflow-hidden px-6 pb-6 pt-3">
            {previewUrl ? (
              <iframe
                src={previewUrl}
                title={doc.name}
                className="w-full h-full rounded-lg border border-border min-h-[400px]"
              />
            ) : (
              <div className="h-40 flex items-center justify-center text-sm text-muted-foreground rounded-lg border border-border">
                Document preview requires a live backend connection.
              </div>
            )}
          </TabsContent>

          {/* Semantic chunk search */}
          <TabsContent value="chunks" className="overflow-y-auto px-6 pb-6 pt-3 flex flex-col gap-4">
            <div>
              <p className="text-sm text-muted-foreground mb-3">
                Search within this document semantically. Athena finds the most relevant sections even without exact keyword matches.
              </p>
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
                <Input
                  value={chunkQuery}
                  onChange={(e) => handleChunkQ(e.target.value)}
                  placeholder="What are you looking for in this document?"
                  className="pl-9"
                  autoFocus
                />
              </div>
            </div>

            {!committedChunkQ || committedChunkQ.length < 2 ? (
              <div className="text-sm text-muted-foreground text-center py-8">
                Type a query to find relevant sections in this document.
              </div>
            ) : chunksFetching ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground py-4">
                <Loader2 className="size-4 animate-spin" /> Searching…
              </div>
            ) : !chunksData?.chunks.length ? (
              <div className="text-sm text-muted-foreground text-center py-8">
                No relevant sections found for "{committedChunkQ}".
              </div>
            ) : (
              <div className="space-y-3">
                <p className="text-xs text-muted-foreground">
                  {chunksData.chunks.length} relevant section{chunksData.chunks.length !== 1 ? "s" : ""} found
                </p>
                {chunksData.chunks.map((chunk: DocumentChunk, i) => (
                  <div
                    key={i}
                    className="rounded-xl border border-border bg-card p-4 cursor-pointer hover:shadow-sm transition-all"
                    onClick={() => setExpandedChunk(expandedChunk === i ? null : i)}
                  >
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <Badge variant="secondary" className="text-[10px]">
                          Section {chunk.index + 1}
                        </Badge>
                        <Badge
                          className={cn(
                            "text-[10px]",
                            chunk.score > 0.8 ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400" :
                            chunk.score > 0.6 ? "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400" :
                            "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400"
                          )}
                        >
                          {Math.round(chunk.score * 100)}% relevance
                        </Badge>
                      </div>
                      {expandedChunk === i ? <ChevronUp className="size-3.5 text-muted-foreground" /> : <ChevronDown className="size-3.5 text-muted-foreground" />}
                    </div>
                    <div className={cn("text-xs text-muted-foreground leading-relaxed", expandedChunk !== i && "line-clamp-3")}>
                      <HighlightedText text={chunk.text} spans={chunk.highlight as [number, number][]} />
                    </div>
                  </div>
                ))}
              </div>
            )}
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}

// ── Main page ────────────────────────────────────────────────────────────────

function DocumentsPage() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ["documents"], queryFn: documentsApi.list });
  const [q, setQ] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const [detailDoc, setDetailDoc] = useState<DocItem | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const upload = useMutation({
    mutationFn: (file: File) => documentsApi.upload(file, (pct) => setUploadProgress(pct)),
    onMutate: () => setUploadProgress(0),
    onSuccess: () => { toast.success("Document uploaded"); qc.invalidateQueries({ queryKey: ["documents"] }); },
    onError: (e: Error) => toast.error(e.message || "Upload failed"),
    onSettled: () => setUploadProgress(null),
  });

  const remove = useMutation({
    mutationFn: (id: string) => documentsApi.remove(id),
    onSuccess: () => { toast.success("Document removed"); qc.invalidateQueries({ queryKey: ["documents"] }); },
  });

  const MAX_UPLOAD_SIZE_MB = 25;
  const handleFiles = useCallback((files: FileList | null) => {
    if (!files) return;
    Array.from(files).forEach((f) => {
      if (f.size > MAX_UPLOAD_SIZE_MB * 1024 * 1024) {
        toast.error(`${f.name} is ${(f.size / 1024 / 1024).toFixed(1)} MB, exceeds ${MAX_UPLOAD_SIZE_MB} MB limit.`);
        return;
      }
      upload.mutate(f);
    });
  }, [upload]);

  const filtered = (data ?? []).filter((d) => d.name.toLowerCase().includes(q.toLowerCase()));

  return (
    <div className="max-w-5xl mx-auto w-full px-4 sm:px-6 py-10">
      <PageHeader
        title="Documents"
        description="Drop a PDF — Athena will index it for retrieval-augmented answers."
        actions={<Button onClick={() => fileRef.current?.click()}><Upload className="size-4" /> Upload</Button>}
      />

      <input ref={fileRef} type="file" accept="application/pdf" multiple className="hidden"
        onChange={(e) => handleFiles(e.target.files)} />

      {/* Drop zone */}
      <div
        onClick={() => fileRef.current?.click()}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileRef.current?.click(); } }}
        role="button" tabIndex={0} aria-label="Upload PDF"
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => { e.preventDefault(); setDragOver(false); handleFiles(e.dataTransfer.files); }}
        className={cn(
          "rounded-2xl border-2 border-dashed transition-all p-10 text-center mb-8 cursor-pointer",
          dragOver ? "border-primary bg-primary/5" : "border-border bg-muted/40 hover:bg-muted/60",
        )}
      >
        <div className="size-12 rounded-2xl bg-card shadow-sm border border-border grid place-items-center mx-auto mb-3">
          <Upload className="size-5 text-primary" />
        </div>
        <p className="text-sm font-medium">Drag PDFs here or click upload</p>
        <p className="text-xs text-muted-foreground mt-1">Athena chunks, embeds, and indexes for instant RAG retrieval.</p>
        {upload.isPending && (
          <div className="mt-3 flex flex-col items-center gap-2">
            <div className="inline-flex items-center gap-2 text-xs text-primary">
              <Loader2 className="size-3.5 animate-spin" />
              {uploadProgress !== null ? `Uploading… ${uploadProgress}%` : "Processing…"}
            </div>
            {uploadProgress !== null && (
              <div className="w-full max-w-xs h-1.5 rounded-full bg-muted overflow-hidden">
                <div className="h-full bg-primary transition-all duration-200" style={{ width: `${uploadProgress}%` }} />
              </div>
            )}
          </div>
        )}
      </div>

      {!isLoading && (data?.length ?? 0) > 0 && (
        <div className="relative mb-4 max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter by name…" className="pl-9" />
        </div>
      )}

      {isLoading ? (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {Array.from({ length: 6 }).map((_, i) => <div key={i} className="h-32 rounded-xl bg-muted animate-pulse" />)}
        </div>
      ) : filtered.length === 0 ? (
        <EmptyState icon={FileText} title="No documents yet" description="Upload a PDF to start grounding your conversations." tone="info" />
      ) : (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map((d, i) => (
            <motion.div
              key={d.id}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.04 }}
              className="rounded-xl border border-border bg-card p-4 ring-1 ring-black/5 hover:shadow-md transition-shadow group"
            >
              <div className="flex items-start gap-3">
                <div className="size-10 rounded-lg bg-red-50 text-red-600 grid place-items-center text-[10px] font-bold shrink-0">PDF</div>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium truncate">{d.name}</div>
                  <div className="text-xs text-muted-foreground mt-0.5">
                    {d.pages} pages · {(d.size / 1024 / 1024).toFixed(1)} MB
                    {d.chunkCount > 0 && ` · ${d.chunkCount} chunks`}
                  </div>
                </div>
              </div>

              {/* Metadata row */}
              <div className="flex flex-wrap gap-1 mt-2">
                {d.uploadedAt && (
                  <span className="text-[10px] text-muted-foreground">
                    {new Date(d.uploadedAt).toLocaleDateString()}
                  </span>
                )}
              </div>

              <div className="flex items-center justify-between mt-4">
                <div className="flex items-center gap-1.5 text-xs">
                  {d.status === "processed" ? (
                    <><CheckCircle2 className="size-3.5 text-emerald-600" /><span className="text-emerald-700">Indexed</span></>
                  ) : d.status === "processing" ? (
                    <><Loader2 className="size-3.5 animate-spin text-primary" /><span className="text-primary">Processing</span></>
                  ) : (
                    <span className="text-destructive">Failed</span>
                  )}
                </div>
                <div className="opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-1">
                  {/* Open detail (preview + semantic search + metadata) */}
                  <button
                    onClick={() => setDetailDoc(d)}
                    className="text-muted-foreground hover:text-primary p-1 rounded"
                    title="Preview & Search"
                    aria-label="Preview & Search"
                  >
                    <Eye className="size-3.5" />
                  </button>
                  {/* Quick info icon also opens detail */}
                  <button
                    onClick={() => setDetailDoc(d)}
                    className="text-muted-foreground hover:text-primary p-1 rounded"
                    title="Metadata"
                    aria-label="Metadata"
                  >
                    <Info className="size-3.5" />
                  </button>
                  {/* Phase 8: Export document summary as PDF */}
                  <ExportMenu type="documentSummary" docId={d.id} label="" size="icon" variant="ghost" />
                  <button
                    onClick={() => remove.mutate(d.id)}
                    className="text-muted-foreground hover:text-destructive p-1 rounded"
                    aria-label="Delete"
                  >
                    <Trash2 className="size-3.5" />
                  </button>
                </div>
              </div>
            </motion.div>
          ))}
        </div>
      )}

      {/* Unified detail dialog: preview + metadata + semantic chunk search */}
      <DocumentDetailDialog
        doc={detailDoc}
        open={!!detailDoc}
        onClose={() => setDetailDoc(null)}
      />
    </div>
  );
} 