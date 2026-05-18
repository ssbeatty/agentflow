"use client";
import { useState, useEffect, useCallback } from "react";
import { DiffEditor } from "@monaco-editor/react";
import { History, Tag, Trash2, GitFork, ChevronDown, ChevronRight, Loader2, GitBranch } from "lucide-react";
import { toast } from "sonner";
import { revisions as revisionsApi } from "@/lib/api";
import type { ScriptRevision, ScriptRevisionDetail } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription,
} from "@/components/ui/dialog";
import { formatDate } from "@/lib/utils";

interface Props {
  scriptId: string;
  currentFileContents: Map<string, string>;
  onLoad: (rev: ScriptRevisionDetail) => void;
  refreshTrigger: number;
}

export default function RevisionPanel({ scriptId, currentFileContents, onLoad, refreshTrigger }: Props) {
  const [items, setItems] = useState<ScriptRevision[]>([]);
  const [loading, setLoading] = useState(false);

  // Diff dialog state
  const [diffRev, setDiffRev] = useState<ScriptRevisionDetail | null>(null);
  const [diffFile, setDiffFile] = useState<string>("");
  const [diffLoading, setDiffLoading] = useState(false);

  // Rollback confirm dialog
  const [rollbackTarget, setRollbackTarget] = useState<ScriptRevision | null>(null);
  const [rollbackLoading, setRollbackLoading] = useState(false);

  // Fork dialog
  const [forkTarget, setForkTarget] = useState<ScriptRevision | null>(null);
  const [forkName, setForkName] = useState("");
  const [forking, setForking] = useState(false);

  // Inline label editing
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingLabel, setEditingLabel] = useState("");

  const reload = useCallback(() => {
    setLoading(true);
    revisionsApi.list(scriptId)
      .then(setItems)
      .catch(() => null)
      .finally(() => setLoading(false));
  }, [scriptId]);

  useEffect(() => { reload(); }, [reload, refreshTrigger]);

  async function openDiff(rev: ScriptRevision) {
    setDiffLoading(true);
    try {
      const detail = await revisionsApi.get(scriptId, rev.id);
      const mainFile = detail.files.find(f => f.is_main) ?? detail.files[0];
      setDiffFile(mainFile?.filename ?? "");
      setDiffRev(detail);
    } catch (e) {
      toast.error(String(e));
    } finally {
      setDiffLoading(false);
    }
  }

  async function confirmRollback() {
    if (!rollbackTarget) return;
    setRollbackLoading(true);
    try {
      const detail = await revisionsApi.get(scriptId, rollbackTarget.id);
      onLoad(detail);
      setRollbackTarget(null);
    } catch (e) {
      toast.error(String(e));
    } finally {
      setRollbackLoading(false);
    }
  }

  async function confirmFork() {
    if (!forkTarget || !forkName.trim()) return;
    setForking(true);
    try {
      const newScript = await revisionsApi.fork(scriptId, forkTarget.id, forkName.trim());
      toast.success(`Created "${newScript.name}"`);
      setForkTarget(null);
      setForkName("");
    } catch (e) {
      toast.error(String(e));
    } finally {
      setForking(false);
    }
  }

  async function handleDelete(rev: ScriptRevision) {
    try {
      await revisionsApi.delete(scriptId, rev.id);
      setItems(prev => prev.filter(r => r.id !== rev.id));
    } catch (e) {
      toast.error(String(e));
    }
  }

  async function saveLabel(rev: ScriptRevision) {
    try {
      await revisionsApi.updateLabel(scriptId, rev.id, editingLabel);
      setItems(prev => prev.map(r => r.id === rev.id ? { ...r, label: editingLabel } : r));
    } catch (e) {
      toast.error(String(e));
    } finally {
      setEditingId(null);
    }
  }

  const diffRevOriginal = diffRev?.files.find(f => f.filename === diffFile)?.content ?? "";
  const diffRevCurrent = currentFileContents.get(diffFile) ?? "";

  return (
    <>
      <ScrollArea className="h-full">
        <div className="p-3 space-y-1">
          {loading && items.length === 0 && (
            <div className="flex items-center gap-2 text-xs text-muted-foreground py-4 justify-center">
              <Loader2 className="h-3 w-3 animate-spin" /> Loading…
            </div>
          )}
          {!loading && items.length === 0 && (
            <div className="text-xs text-muted-foreground text-center py-6">
              No revisions yet. Save to create the first one.
            </div>
          )}

          {items.map(rev => (
            <div
              key={rev.id}
              className="group rounded-lg border border-border bg-secondary/10 hover:bg-secondary/20 transition-colors px-2.5 py-2"
            >
              <div className="flex items-center gap-2 min-w-0">
                <span className="text-[10px] font-mono text-muted-foreground shrink-0">
                  #{rev.revision_number}
                </span>

                {editingId === rev.id ? (
                  <Input
                    autoFocus
                    value={editingLabel}
                    onChange={e => setEditingLabel(e.target.value)}
                    onBlur={() => saveLabel(rev)}
                    onKeyDown={e => {
                      if (e.key === "Enter") saveLabel(rev);
                      if (e.key === "Escape") setEditingId(null);
                    }}
                    className="h-5 text-xs flex-1 min-w-0 px-1.5 py-0"
                  />
                ) : (
                  <span
                    className="text-xs text-foreground/80 flex-1 min-w-0 truncate cursor-pointer hover:text-foreground"
                    title="Click to edit label"
                    onClick={() => { setEditingId(rev.id); setEditingLabel(rev.label); }}
                  >
                    {rev.label || <span className="text-muted-foreground/50 italic">add label…</span>}
                  </span>
                )}

                <span className="text-[10px] text-muted-foreground shrink-0">
                  {formatDate(rev.created_at)}
                </span>
              </div>

              <div className="flex items-center gap-1 mt-1.5 opacity-0 group-hover:opacity-100 transition-opacity">
                <button
                  onClick={() => openDiff(rev)}
                  disabled={diffLoading}
                  className="text-[10px] px-2 py-0.5 rounded border border-border/60 text-muted-foreground hover:text-foreground hover:border-border transition-colors flex items-center gap-1"
                >
                  {diffLoading ? <Loader2 className="h-2.5 w-2.5 animate-spin" /> : <History className="h-2.5 w-2.5" />}
                  Diff
                </button>
                <button
                  onClick={() => setRollbackTarget(rev)}
                  className="text-[10px] px-2 py-0.5 rounded border border-border/60 text-muted-foreground hover:text-foreground hover:border-border transition-colors flex items-center gap-1"
                >
                  <GitBranch className="h-2.5 w-2.5" />
                  Load
                </button>
                <button
                  onClick={() => { setForkTarget(rev); setForkName(`${rev.name} (copy)`); }}
                  className="text-[10px] px-2 py-0.5 rounded border border-border/60 text-muted-foreground hover:text-foreground hover:border-border transition-colors flex items-center gap-1"
                >
                  <GitFork className="h-2.5 w-2.5" />
                  Fork
                </button>
                <button
                  onClick={() => handleDelete(rev)}
                  className="ml-auto text-[10px] px-2 py-0.5 rounded border border-border/60 text-muted-foreground hover:text-destructive hover:border-destructive/40 transition-colors flex items-center gap-1"
                >
                  <Trash2 className="h-2.5 w-2.5" />
                </button>
              </div>
            </div>
          ))}
        </div>
      </ScrollArea>

      {/* Diff dialog */}
      <Dialog open={!!diffRev} onOpenChange={open => { if (!open) setDiffRev(null); }}>
        <DialogContent className="max-w-5xl w-[90vw] h-[80vh] flex flex-col gap-0 p-0">
          <DialogHeader className="px-4 py-3 border-b border-border shrink-0">
            <DialogTitle className="text-sm">
              Revision #{diffRev?.revision_number}
              {diffRev?.label && <span className="ml-2 text-muted-foreground font-normal">— {diffRev.label}</span>}
            </DialogTitle>
            {diffRev && diffRev.files.length > 1 && (
              <div className="flex gap-1 flex-wrap mt-1">
                {diffRev.files.map(f => (
                  <button
                    key={f.filename}
                    onClick={() => setDiffFile(f.filename)}
                    className={`text-[10px] px-2 py-0.5 rounded border transition-colors ${
                      diffFile === f.filename
                        ? "bg-primary/10 border-primary/40 text-primary"
                        : "border-border/60 text-muted-foreground hover:border-border hover:text-foreground"
                    }`}
                  >
                    {f.filename}
                  </button>
                ))}
              </div>
            )}
          </DialogHeader>
          <div className="flex-1 min-h-0">
            <DiffEditor
              original={diffRevOriginal}
              modified={diffRevCurrent}
              language={diffFile.endsWith(".py") ? "python" : diffFile.endsWith(".json") ? "json" : "plaintext"}
              theme="vs-dark"
              options={{
                readOnly: true,
                renderSideBySide: true,
                minimap: { enabled: false },
                fontSize: 12,
                lineNumbers: "on",
                scrollBeyondLastLine: false,
              }}
            />
          </div>
          <div className="px-4 py-2 border-t border-border shrink-0 flex items-center gap-2">
            <span className="text-[10px] text-muted-foreground">Left: revision &nbsp;·&nbsp; Right: current editor</span>
          </div>
        </DialogContent>
      </Dialog>

      {/* Rollback (Load) confirm dialog */}
      <Dialog open={!!rollbackTarget} onOpenChange={open => { if (!open) setRollbackTarget(null); }}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>Load revision #{rollbackTarget?.revision_number}?</DialogTitle>
            <DialogDescription>
              {rollbackTarget?.label
                ? <>This will load <span className="font-medium text-foreground">"{rollbackTarget.label}"</span> into the editor.</>
                : <>This will load revision #{rollbackTarget?.revision_number} into the editor.</>
              }
              {" "}Your current unsaved changes will remain until you save.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRollbackTarget(null)} disabled={rollbackLoading}>
              Cancel
            </Button>
            <Button onClick={confirmRollback} disabled={rollbackLoading}>
              {rollbackLoading ? <Loader2 className="h-3 w-3 animate-spin" /> : <GitBranch className="h-3 w-3" />}
              Load into editor
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Fork dialog */}
      <Dialog open={!!forkTarget} onOpenChange={open => { if (!open) setForkTarget(null); }}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>Fork revision #{forkTarget?.revision_number}</DialogTitle>
            <DialogDescription>
              Create a new script from this snapshot.
            </DialogDescription>
          </DialogHeader>
          <Input
            value={forkName}
            onChange={e => setForkName(e.target.value)}
            placeholder="New script name"
            className="text-sm"
            onKeyDown={e => { if (e.key === "Enter") confirmFork(); }}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setForkTarget(null)} disabled={forking}>Cancel</Button>
            <Button onClick={confirmFork} disabled={forking || !forkName.trim()}>
              {forking ? <Loader2 className="h-3 w-3 animate-spin" /> : <GitFork className="h-3 w-3" />}
              Fork
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
