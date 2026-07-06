"use client";
import { Suspense, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, Save, Trash2, Loader2, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import { skills } from "@/lib/api";
import type { Skill, SkillFile } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription,
} from "@/components/ui/dialog";
import ScriptEditor, { type EditorSelection } from "@/components/ScriptEditor";
import FileTree, { type TreeFile } from "@/components/FileTree";
import { useResizable } from "@/components/Splitter";
import { useAssistantTarget, type ChangedFile } from "@/components/assistant/AssistantProvider";

const MAIN_FILE = "SKILL.md";

function getLanguage(filename: string): string {
  const ext = filename.split(".").pop()?.toLowerCase() ?? "";
  if (ext === "py") return "python";
  if (ext === "json") return "json";
  if (ext === "yaml" || ext === "yml") return "yaml";
  if (ext === "md") return "markdown";
  if (ext === "sh" || ext === "bash") return "shell";
  if (ext === "html") return "html";
  if (ext === "css") return "css";
  if (ext === "js") return "javascript";
  if (ext === "ts") return "typescript";
  return "plaintext";
}

export default function SkillPageWrapper() {
  return (
    <Suspense fallback={<div className="min-h-screen flex items-center justify-center"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>}>
      <SkillPage />
    </Suspense>
  );
}

function SkillPage() {
  const { t } = useTranslation("skill");
  const router = useRouter();
  const params = useSearchParams();
  const id = params.get("id") ?? "";

  const [loading, setLoading] = useState(true);
  const [skill, setSkill] = useState<Skill | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [enabled, setEnabled] = useState(true);

  const [skillFiles, setSkillFiles] = useState<SkillFile[]>([]);
  const [dirs, setDirs] = useState<string[]>([]);
  const [fileContents, setFileContents] = useState<Map<string, string>>(new Map());
  const [dirtyFiles, setDirtyFiles] = useState<Set<string>>(new Set());
  const [metaDirty, setMetaDirty] = useState(false);
  const [activeFile, setActiveFile] = useState(MAIN_FILE);

  const [saving, setSaving] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const [treeWidth, treeHandle] = useResizable({
    direction: "vertical", initial: 210, min: 140, max: 380,
    storageKey: "ag.skillTreeWidth", side: "start",
  });

  const assistantBaselineRef = useRef<Map<string, string>>(new Map());
  const [selection, setSelection] = useState<EditorSelection | null>(null);

  // Bind the global floating AI assistant to THIS skill while the page is open
  // (handler fns below are hoisted). Unbinds on unmount / while loading.
  useAssistantTarget(
    loading || !id || !skill ? null : {
      kind: "skill", id, label: name,
      buildContext: buildAssistantContext,
      onBeforeTurn: handleAssistantBeforeTurn,
      onAfterTurn: handleAssistantAfterTurn,
      onRevert: handleAssistantRevert,
      onOpenFile: setActiveFile,
    },
  );

  useEffect(() => {
    if (!id) { router.push("/tools"); return; }
    skills.get(id)
      .then(s => {
        setSkill(s);
        setName(s.name);
        setDescription(s.description);
        setEnabled(s.enabled);
        setSkillFiles(s.files);
        setDirs(s.dirs ?? []);
        setFileContents(new Map(s.files.map(f => [f.filename, f.content])));
        const main = s.files.find(f => f.is_main)?.filename ?? s.files[0]?.filename ?? MAIN_FILE;
        setActiveFile(main);
      })
      .catch(() => toast.error(t("toast.loadFailed")))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const activeContent = fileContents.get(activeFile) ?? "";
  const activeLang = getLanguage(activeFile);
  const dirty = dirtyFiles.size > 0 || metaDirty;

  function markDirty(filename: string) {
    setDirtyFiles(prev => new Set(prev).add(filename));
  }

  // ── File tree operations ──────────────────────────────────────────────────

  async function handleNewFile(filename: string) {
    const content = filename.endsWith(".py") ? "# " + filename + "\n" : "";
    await skills.upsertFile(id, { filename, content, is_main: false });
    setSkillFiles(prev => [...prev, {
      id: `local-${Date.now()}`, skill_id: id, filename, content,
      is_main: false, updated_at: new Date().toISOString(),
    }]);
    setFileContents(prev => new Map(prev).set(filename, content));
    setActiveFile(filename);
  }

  async function handleNewFolder(path: string) {
    await skills.createDir(id, path);
    setDirs(prev => Array.from(new Set([...prev, path])));
  }

  async function handleDeleteDir(path: string) {
    await skills.deleteDir(id, path);
    const prefix = path + "/";
    const under = (fn: string) => fn === path || fn.startsWith(prefix);
    setSkillFiles(prev => prev.filter(f => !under(f.filename)));
    setFileContents(prev => {
      const m = new Map(prev);
      for (const k of Array.from(m.keys())) if (under(k)) m.delete(k);
      return m;
    });
    setDirtyFiles(prev => {
      const s = new Set(prev);
      for (const k of Array.from(s)) if (under(k)) s.delete(k);
      return s;
    });
    setDirs(prev => prev.filter(d => d !== path && !d.startsWith(prefix)));
    if (activeFile === path || activeFile.startsWith(prefix)) {
      const remaining = skillFiles.filter(f => !under(f.filename));
      setActiveFile(remaining[0]?.filename ?? MAIN_FILE);
    }
  }

  async function handleDeleteFile(filename: string) {
    await skills.deleteFile(id, filename);
    setSkillFiles(prev => prev.filter(f => f.filename !== filename));
    setFileContents(prev => { const m = new Map(prev); m.delete(filename); return m; });
    setDirtyFiles(prev => { const s = new Set(prev); s.delete(filename); return s; });
    if (activeFile === filename) {
      const remaining = skillFiles.filter(f => f.filename !== filename);
      setActiveFile(remaining[0]?.filename ?? MAIN_FILE);
    }
  }

  async function handleRenameFile(oldName: string, newName: string) {
    const content = fileContents.get(oldName) ?? "";
    const oldFile = skillFiles.find(f => f.filename === oldName);
    if (oldFile?.is_main) { toast.error(t("toast.renameMainForbidden")); return; }
    await skills.upsertFile(id, { filename: newName, content, is_main: false });
    await skills.deleteFile(id, oldName);
    setSkillFiles(prev => prev.map(f => f.filename === oldName ? { ...f, filename: newName } : f));
    setFileContents(prev => {
      const m = new Map(prev);
      m.set(newName, content);
      m.delete(oldName);
      return m;
    });
    setDirtyFiles(prev => {
      const s = new Set(prev);
      if (s.has(oldName)) { s.delete(oldName); s.add(newName); }
      return s;
    });
    if (activeFile === oldName) setActiveFile(newName);
  }

  async function handleUploadFiles(entries: { filename: string; content: string }[]) {
    await Promise.all(entries.map(e => skills.upsertFile(id, { ...e, is_main: false })));
    setSkillFiles(prev => {
      const existing = new Map(prev.map(f => [f.filename, f]));
      for (const e of entries) {
        existing.set(e.filename, {
          id: existing.get(e.filename)?.id ?? `local-${e.filename}`,
          skill_id: id, filename: e.filename, content: e.content,
          is_main: existing.get(e.filename)?.is_main ?? false,
          updated_at: new Date().toISOString(),
        });
      }
      return Array.from(existing.values());
    });
    setFileContents(prev => {
      const m = new Map(prev);
      for (const e of entries) m.set(e.filename, e.content);
      return m;
    });
    if (entries.length === 1) setActiveFile(entries[0].filename);
  }

  function handleDownloadFile(filename: string) {
    const content = fileContents.get(filename) ?? "";
    const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename.split("/").pop() ?? filename;
    a.click();
    URL.revokeObjectURL(url);
  }

  // ── Save / delete ───────────────────────────────────────────────────────────

  async function handleSave() {
    if (!name.trim()) return toast.error(t("toast.nameRequired"));
    setSaving(true);
    try {
      // Write file edits first, then apply name/description — the latter rewrites
      // SKILL.md frontmatter, so it must win over a stale in-editor SKILL.md body.
      const isMain = (fn: string) => skillFiles.find(f => f.filename === fn)?.is_main ?? false;
      for (const fn of dirtyFiles) {
        await skills.upsertFile(id, {
          filename: fn,
          content: fileContents.get(fn) ?? "",
          is_main: isMain(fn),
        });
      }
      if (metaDirty) {
        const updated = await skills.update(id, { name: name.trim(), description, enabled });
        // Re-sync the (frontmatter-rewritten) SKILL.md into the editor.
        const mainFile = updated.files.find(f => f.is_main);
        if (mainFile) {
          setFileContents(prev => new Map(prev).set(mainFile.filename, mainFile.content));
          setSkillFiles(prev => prev.map(f => f.filename === mainFile.filename ? { ...f, content: mainFile.content } : f));
        }
      }
      setDirtyFiles(new Set());
      setMetaDirty(false);
      toast.success(t("toast.saved"));
    } catch (e: unknown) {
      toast.error(String(e));
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    setDeleting(true);
    try {
      await skills.delete(id);
      toast.success(t("toast.deleted"));
      router.push("/tools");
    } catch (e: unknown) {
      toast.error(String(e));
      setDeleting(false);
      setDeleteOpen(false);
    }
  }

  // ── AI assistant turn lifecycle (edits skill files; diff/undo at end of turn) ──
  function syncFromSkill(s: Skill) {
    setSkill(s);
    setName(s.name);
    setDescription(s.description);
    setEnabled(s.enabled);
    setSkillFiles(s.files);
    setDirs(s.dirs ?? []);
    setFileContents(new Map(s.files.map(f => [f.filename, f.content])));
    setDirtyFiles(new Set());
    setMetaDirty(false);
  }

  function buildAssistantContext(): Record<string, unknown> {
    const ctx: Record<string, unknown> = {
      kind: "skill",
      skill_id: id,
      active_file: activeFile,
      active_content: fileContents.get(activeFile) ?? "",
    };
    if (selection?.text) ctx.selection = selection.text;
    return ctx;
  }

  async function handleAssistantBeforeTurn() {
    if (dirty) await handleSave();
    const base = new Map<string, string>();
    for (const f of skillFiles) base.set(f.filename, fileContents.get(f.filename) ?? f.content);
    assistantBaselineRef.current = base;
  }

  async function handleAssistantAfterTurn(): Promise<ChangedFile[]> {
    const s = await skills.get(id);
    syncFromSkill(s);
    const base = assistantBaselineRef.current;
    const changed: ChangedFile[] = [];
    const seen = new Set<string>();
    for (const f of s.files) {
      seen.add(f.filename);
      const before = base.get(f.filename) ?? "";
      if (before !== f.content) changed.push({ filename: f.filename, before, after: f.content });
    }
    for (const [fn, before] of base) {
      if (!seen.has(fn) && before) changed.push({ filename: fn, before, after: "" });
    }
    return changed;
  }

  async function handleAssistantRevert(filenames: string[]) {
    const base = assistantBaselineRef.current;
    const s = await skills.get(id);
    const want = new Set(filenames);
    const baseNames = new Set(base.keys());
    const curNames = new Set(s.files.map(f => f.filename));
    const ops: Promise<unknown>[] = [];
    for (const f of s.files) {
      if (!want.has(f.filename)) continue;
      if (!baseNames.has(f.filename)) {
        if (!f.is_main) ops.push(skills.deleteFile(id, f.filename).catch(() => null));  // assistant-created → remove
      } else if ((base.get(f.filename) ?? "") !== f.content) {
        ops.push(skills.upsertFile(id, { filename: f.filename, content: base.get(f.filename) ?? "", is_main: f.is_main }));
      }
    }
    for (const [fn, content] of base) {  // assistant-deleted → recreate
      if (want.has(fn) && !curNames.has(fn)) ops.push(skills.upsertFile(id, { filename: fn, content, is_main: fn === MAIN_FILE }));
    }
    await Promise.all(ops);
    syncFromSkill(await skills.get(id));
  }

  const treeFiles: TreeFile[] = skillFiles.map(f => ({
    filename: f.filename,
    is_main: f.is_main,
    isDirty: dirtyFiles.has(f.filename),
  }));

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!skill) return null;

  return (
    <div className="h-screen flex flex-col overflow-hidden">
      {/* Header */}
      <header className="border-b border-border px-4 py-2.5 flex items-center gap-3 shrink-0">
        <Link href="/tools">
          <Button variant="ghost" size="icon"><ArrowLeft className="h-4 w-4" /></Button>
        </Link>
        <Sparkles className="h-4 w-4 text-primary shrink-0" />
        <Input
          value={name}
          onChange={e => { setName(e.target.value); setMetaDirty(true); }}
          className="max-w-xs h-8 font-medium"
          placeholder={t("header.namePlaceholder")}
        />
        <label className="flex items-center gap-1.5 text-xs text-muted-foreground cursor-pointer shrink-0">
          <input
            type="checkbox"
            checked={enabled}
            onChange={e => { setEnabled(e.target.checked); setMetaDirty(true); }}
            className="rounded"
          />
          {t("header.enabled")}
        </label>
        <div className="flex-1" />
        <Button size="sm" onClick={handleSave} disabled={saving || !dirty}>
          {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
          {t("header.save")}
        </Button>
        <Button variant="ghost" size="icon" onClick={() => setDeleteOpen(true)} title={t("header.deleteTitle")}>
          <Trash2 className="h-4 w-4 text-destructive" />
        </Button>
      </header>

      {/* Description */}
      <div className="border-b border-border px-4 py-2 shrink-0">
        <Textarea
          value={description}
          onChange={e => { setDescription(e.target.value); setMetaDirty(true); }}
          placeholder={t("description.placeholder")}
          rows={1}
          className="text-xs resize-none min-h-0 h-8 py-1.5"
        />
      </div>

      {/* Body: file tree + editor */}
      <div className="flex flex-1 overflow-hidden">
        <div className="shrink-0 flex flex-col overflow-hidden" style={{ width: `${treeWidth}px` }}>
          <div className="flex-1 min-h-0">
            <FileTree
              files={treeFiles}
              activeFile={activeFile}
              onSelect={setActiveFile}
              onNewFile={handleNewFile}
              onDeleteFile={handleDeleteFile}
              onRenameFile={handleRenameFile}
              onUploadFiles={handleUploadFiles}
              onDownloadFile={handleDownloadFile}
              showRequirements={false}
              emptyDirs={dirs}
              onNewFolder={handleNewFolder}
              onDeleteDir={handleDeleteDir}
            />
          </div>
        </div>

        {treeHandle}

        <div className="flex flex-col flex-1 min-w-0">
          <div className="flex-1 min-h-0">
            <ScriptEditor
              key={activeFile}
              value={activeContent}
              language={activeLang}
              onChange={v => {
                const val = v ?? "";
                setFileContents(prev => new Map(prev).set(activeFile, val));
                markDirty(activeFile);
              }}
              onSelectionChange={setSelection}
            />
          </div>
        </div>

      </div>

      {/* Delete confirmation */}
      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>{t("deleteDialog.title")}</DialogTitle>
            <DialogDescription>
              {t("deleteDialog.description", { name: skill.name })}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteOpen(false)}>{t("deleteDialog.cancel")}</Button>
            <Button variant="destructive" onClick={handleDelete} disabled={deleting}>
              {deleting ? t("deleteDialog.deleting") : t("deleteDialog.delete")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
