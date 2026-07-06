"use client";
import { useEffect, useRef, useState } from "react";
import { Upload, Trash2, Copy, FileText, Loader2 } from "lucide-react";
import { toast } from "sonner";

import { files } from "@/lib/api";
import type { UploadedFile } from "@/lib/types";
import { useConfirm } from "@/components/ConfirmDialogProvider";

interface Props {
  scriptId: string;
  /** Optional: insert `{"$file":"<id>"}` directly into the input editor. */
  onInsertRef?: (snippet: string) => void;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

export default function FileUploadPanel({ scriptId, onInsertRef }: Props) {
  const [items, setItems] = useState<UploadedFile[]>([]);
  const [busy, setBusy] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const confirm = useConfirm();

  async function refresh() {
    try {
      setItems(await files.list(scriptId));
    } catch (e) {
      toast.error(`Failed to list files: ${e}`);
    }
  }

  useEffect(() => { refresh(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [scriptId]);

  async function uploadAll(picked: FileList | File[]) {
    const list = Array.from(picked);
    if (!list.length) return;
    setBusy(true);
    try {
      for (const f of list) {
        await files.upload(f, scriptId);
      }
      toast.success(list.length === 1 ? `Uploaded ${list[0].name}` : `Uploaded ${list.length} files`);
      await refresh();
    } catch (e) {
      toast.error(`Upload failed: ${e}`);
    } finally {
      setBusy(false);
    }
  }

  async function remove(item: UploadedFile) {
    if (!(await confirm(`Delete "${item.original_name}"?`, { confirmLabel: "Delete", destructive: true }))) return;
    try {
      await files.delete(item.id);
      setItems(prev => prev.filter(x => x.id !== item.id));
    } catch (e) {
      toast.error(`Delete failed: ${e}`);
    }
  }

  async function copyRef(item: UploadedFile) {
    const snippet = `{"$file":"${item.id}"}`;
    try {
      await navigator.clipboard.writeText(snippet);
      toast.success(`Copied ref for ${item.original_name}`);
    } catch {
      toast.message(snippet);  // fallback: at least show it
    }
  }

  function insertRef(item: UploadedFile) {
    if (!onInsertRef) return copyRef(item);
    onInsertRef(`{"$file":"${item.id}"}`);
  }

  return (
    <div className="space-y-1.5">
      <p className="text-[10px] uppercase tracking-wider font-semibold text-muted-foreground/70 flex items-center justify-between">
        <span>Files</span>
        <span className="text-[10px] normal-case font-normal text-muted-foreground">
          {items.length > 0 ? `${items.length} uploaded` : ""}
        </span>
      </p>

      {/* Drop zone / file picker */}
      <label
        onDragOver={e => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={e => {
          e.preventDefault();
          setDragOver(false);
          if (e.dataTransfer.files?.length) uploadAll(e.dataTransfer.files);
        }}
        className={`flex items-center justify-center gap-2 h-16 rounded-md border border-dashed cursor-pointer transition-colors text-xs ${
          dragOver
            ? "border-primary/60 bg-primary/5 text-primary"
            : "border-border/60 bg-secondary/20 text-muted-foreground hover:border-border hover:text-foreground"
        }`}
      >
        {busy ? (
          <><Loader2 className="h-3.5 w-3.5 animate-spin" /> Uploading…</>
        ) : (
          <><Upload className="h-3.5 w-3.5" /> Drop files or click to upload</>
        )}
        <input
          ref={inputRef}
          type="file"
          multiple
          className="hidden"
          onChange={e => {
            if (e.target.files?.length) uploadAll(e.target.files);
            if (inputRef.current) inputRef.current.value = "";
          }}
        />
      </label>

      {/* File list */}
      {items.length > 0 && (
        <div className="rounded-md border border-border/60 divide-y divide-border/60 overflow-hidden">
          {items.map(item => (
            <div key={item.id} className="flex items-center gap-1.5 px-2 py-1.5 group hover:bg-secondary/30 transition-colors">
              <FileText className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
              <button
                onClick={() => insertRef(item)}
                className="flex-1 min-w-0 text-left"
                title={onInsertRef ? "Insert {$file} ref into input JSON" : `Copy {"$file":"${item.id}"} to clipboard`}
              >
                <div className="truncate text-xs text-foreground">{item.original_name}</div>
                <div className="text-[10px] text-muted-foreground">
                  {formatSize(item.size)}{item.mime ? ` · ${item.mime}` : ""}
                </div>
              </button>
              <button
                onClick={() => copyRef(item)}
                className="opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-secondary text-muted-foreground hover:text-foreground transition"
                title="Copy {$file} ref"
              >
                <Copy className="h-3 w-3" />
              </button>
              <button
                onClick={() => remove(item)}
                className="opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition"
                title="Delete file"
              >
                <Trash2 className="h-3 w-3" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
