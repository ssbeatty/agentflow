"use client";
import { useState, useEffect, useCallback } from "react";
import { DiffEditor } from "@monaco-editor/react";
import { History, Tag, Trash2, GitFork, ChevronDown, ChevronRight, Loader2, GitBranch } from "lucide-react";
import { useTranslation } from "react-i18next";
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
  const { t } = useTranslation("scriptPanels");
  const [items, setItems] = useState<ScriptRevision[]>([]);
  const [loading, setLoading] = useState(false);

  // Diff dialog state
  const [diffRev, setDiffRev] = useState<ScriptRevisionDetail | null>(null);
  const [diffPrev, setDiffPrev] = useState<ScriptRevisionDetail | null>(null);
  const [diffMode, setDiffMode] = useState<"prev" | "current">("prev");
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
      // Baseline of the diff = the *previous* revision, so "Diff" answers
      // "what did this version change?" (like `git show`). #1 has no previous
      // revision → fall back to comparing against the current editor.
      const prevSummary = items.find(r => r.revision_number === rev.revision_number - 1);
      const prevDetail = prevSummary ? await revisionsApi.get(scriptId, prevSummary.id) : null;
      const mainFile = detail.files.find(f => f.is_main) ?? detail.files[0];
      setDiffFile(mainFile?.filename ?? "");
      setDiffPrev(prevDetail);
      setDiffMode(prevDetail ? "prev" : "current");
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
      toast.success(t("revisionPanel.toast.forked", { name: newScript.name }));
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

  const revContent = (d: ScriptRevisionDetail | null, fn: string) =>
    d?.files.find(f => f.filename === fn)?.content ?? "";

  // Files across both sides being compared, so an added/removed file still shows
  // up as a tab (and diffs as fully added / fully removed).
  const diffFileList = (() => {
    if (!diffRev) return [] as string[];
    const names = new Set<string>();
    for (const f of diffRev.files) names.add(f.filename);
    for (const f of diffMode === "prev" ? diffPrev?.files ?? [] : []) names.add(f.filename);
    return [...names].sort();
  })();

  // prev mode: previous revision (left) → this revision (right)
  // current mode: this revision (left) → current editor (right)
  const diffOriginal = diffMode === "prev" ? revContent(diffPrev, diffFile) : revContent(diffRev, diffFile);
  const diffModified = diffMode === "prev" ? revContent(diffRev, diffFile) : currentFileContents.get(diffFile) ?? "";

  // The earliest kept revision is the baseline origin (shown with a distinct label).
  const baselineNum = items.length ? items[items.length - 1].revision_number : null;

  return (
    <>
      <ScrollArea className="h-full">
        <div className="p-3 space-y-1">
          {loading && items.length === 0 && (
            <div className="flex items-center gap-2 text-xs text-muted-foreground py-4 justify-center">
              <Loader2 className="h-3 w-3 animate-spin" /> {t("revisionPanel.loading")}
            </div>
          )}
          {!loading && items.length === 0 && (
            <div className="text-xs text-muted-foreground text-center py-6">
              {t("revisionPanel.empty")}
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
                    title={t("revisionPanel.labelEditHint")}
                    onClick={() => { setEditingId(rev.id); setEditingLabel(rev.label); }}
                  >
                    {rev.label
                      ? rev.label
                      : rev.revision_number === baselineNum
                        ? <span className="text-muted-foreground/70">{t("revisionPanel.initialVersion")}</span>
                        : <span className="text-muted-foreground/50 italic">{t("revisionPanel.addLabelPlaceholder")}</span>}
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
                  {t("revisionPanel.actions.diff")}
                </button>
                <button
                  onClick={() => setRollbackTarget(rev)}
                  className="text-[10px] px-2 py-0.5 rounded border border-border/60 text-muted-foreground hover:text-foreground hover:border-border transition-colors flex items-center gap-1"
                >
                  <GitBranch className="h-2.5 w-2.5" />
                  {t("revisionPanel.actions.load")}
                </button>
                <button
                  onClick={() => { setForkTarget(rev); setForkName(t("revisionPanel.forkNameSuffix", { name: rev.name })); }}
                  className="text-[10px] px-2 py-0.5 rounded border border-border/60 text-muted-foreground hover:text-foreground hover:border-border transition-colors flex items-center gap-1"
                >
                  <GitFork className="h-2.5 w-2.5" />
                  {t("revisionPanel.actions.fork")}
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
      <Dialog open={!!diffRev} onOpenChange={open => { if (!open) { setDiffRev(null); setDiffPrev(null); } }}>
        <DialogContent className="max-w-5xl w-[90vw] h-[80vh] flex flex-col gap-0 p-0">
          <DialogHeader className="px-4 py-3 border-b border-border shrink-0">
            <DialogTitle className="text-sm">
              {t("revisionPanel.diffDialog.title", { number: diffRev?.revision_number })}
              {diffRev?.label && <span className="ml-2 text-muted-foreground font-normal">{t("revisionPanel.diffDialog.labelSuffix", { label: diffRev.label })}</span>}
            </DialogTitle>
            {/* Compare target: previous revision (default) vs the current editor */}
            <div className="flex gap-1 mt-1.5">
              <button
                onClick={() => setDiffMode("prev")}
                disabled={!diffPrev}
                title={!diffPrev ? t("revisionPanel.diffDialog.noPrevHint") : undefined}
                className={`text-[10px] px-2 py-0.5 rounded border transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
                  diffMode === "prev"
                    ? "bg-primary/10 border-primary/40 text-primary"
                    : "border-border/60 text-muted-foreground hover:border-border hover:text-foreground"
                }`}
              >
                {t("revisionPanel.diffDialog.comparePrev")}
              </button>
              <button
                onClick={() => setDiffMode("current")}
                className={`text-[10px] px-2 py-0.5 rounded border transition-colors ${
                  diffMode === "current"
                    ? "bg-primary/10 border-primary/40 text-primary"
                    : "border-border/60 text-muted-foreground hover:border-border hover:text-foreground"
                }`}
              >
                {t("revisionPanel.diffDialog.compareCurrent")}
              </button>
            </div>
            {diffFileList.length > 1 && (
              <div className="flex gap-1 flex-wrap mt-1.5">
                {diffFileList.map(fn => (
                  <button
                    key={fn}
                    onClick={() => setDiffFile(fn)}
                    className={`text-[10px] px-2 py-0.5 rounded border transition-colors ${
                      diffFile === fn
                        ? "bg-primary/10 border-primary/40 text-primary"
                        : "border-border/60 text-muted-foreground hover:border-border hover:text-foreground"
                    }`}
                  >
                    {fn}
                  </button>
                ))}
              </div>
            )}
          </DialogHeader>
          <div className="flex-1 min-h-0">
            <DiffEditor
              original={diffOriginal}
              modified={diffModified}
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
            <span className="text-[10px] text-muted-foreground">
              {diffMode === "prev"
                ? t("revisionPanel.diffDialog.legendPrev", { prev: diffPrev?.revision_number ?? "—", current: diffRev?.revision_number })
                : t("revisionPanel.diffDialog.legendCurrent")}
            </span>
          </div>
        </DialogContent>
      </Dialog>

      {/* Rollback (Load) confirm dialog */}
      <Dialog open={!!rollbackTarget} onOpenChange={open => { if (!open) setRollbackTarget(null); }}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>{t("revisionPanel.rollbackDialog.title", { number: rollbackTarget?.revision_number })}</DialogTitle>
            <DialogDescription>
              {rollbackTarget?.label
                ? <>{t("revisionPanel.rollbackDialog.withLabelPrefix")}<span className="font-medium text-foreground">"{rollbackTarget.label}"</span>{t("revisionPanel.rollbackDialog.withLabelSuffix")}</>
                : <>{t("revisionPanel.rollbackDialog.withoutLabel", { number: rollbackTarget?.revision_number })}</>
              }
              {" "}{t("revisionPanel.rollbackDialog.unsavedNote")}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRollbackTarget(null)} disabled={rollbackLoading}>
              {t("revisionPanel.rollbackDialog.cancel")}
            </Button>
            <Button onClick={confirmRollback} disabled={rollbackLoading}>
              {rollbackLoading ? <Loader2 className="h-3 w-3 animate-spin" /> : <GitBranch className="h-3 w-3" />}
              {t("revisionPanel.rollbackDialog.confirm")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Fork dialog */}
      <Dialog open={!!forkTarget} onOpenChange={open => { if (!open) setForkTarget(null); }}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>{t("revisionPanel.forkDialog.title", { number: forkTarget?.revision_number })}</DialogTitle>
            <DialogDescription>
              {t("revisionPanel.forkDialog.description")}
            </DialogDescription>
          </DialogHeader>
          <Input
            value={forkName}
            onChange={e => setForkName(e.target.value)}
            placeholder={t("revisionPanel.forkDialog.namePlaceholder")}
            className="text-sm"
            onKeyDown={e => { if (e.key === "Enter") confirmFork(); }}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setForkTarget(null)} disabled={forking}>{t("revisionPanel.forkDialog.cancel")}</Button>
            <Button onClick={confirmFork} disabled={forking || !forkName.trim()}>
              {forking ? <Loader2 className="h-3 w-3 animate-spin" /> : <GitFork className="h-3 w-3" />}
              {t("revisionPanel.forkDialog.confirm")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
