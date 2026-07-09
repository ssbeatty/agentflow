"use client";
import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, Save, Trash2, Loader2, Blocks } from "lucide-react";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import { scripts } from "@/lib/api";
import type { Script, ScriptFile, ScriptSummary } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription,
} from "@/components/ui/dialog";
import ScriptEditor from "@/components/ScriptEditor";
import FileTree, { type TreeFile } from "@/components/FileTree";
import { useResizable } from "@/components/Splitter";

const MAIN_FILE = "__init__.py";

function getLanguage(filename: string): string {
  const ext = filename.split(".").pop()?.toLowerCase() ?? "";
  if (ext === "py") return "python";
  if (ext === "json") return "json";
  if (ext === "yaml" || ext === "yml") return "yaml";
  if (ext === "md") return "markdown";
  if (ext === "txt") return "plaintext";
  return "plaintext";
}

export default function ModulePageWrapper() {
  return (
    <Suspense fallback={<div className="min-h-screen flex items-center justify-center"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>}>
      <ModulePage />
    </Suspense>
  );
}

function ModulePage() {
  const { t } = useTranslation("module");
  const router = useRouter();
  const params = useSearchParams();
  const id = params.get("id") ?? "";

  const [loading, setLoading] = useState(true);
  const [module, setModule] = useState<Script | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [pkg, setPkg] = useState("");
  const [dependents, setDependents] = useState<ScriptSummary[]>([]);

  const [moduleFiles, setModuleFiles] = useState<ScriptFile[]>([]);
  const [fileContents, setFileContents] = useState<Map<string, string>>(new Map());
  const [dirtyFiles, setDirtyFiles] = useState<Set<string>>(new Set());
  const [metaDirty, setMetaDirty] = useState(false);
  const [activeFile, setActiveFile] = useState(MAIN_FILE);

  const [saving, setSaving] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const [treeWidth, treeHandle] = useResizable({
    direction: "vertical", initial: 220, min: 150, max: 400,
    storageKey: "ag.moduleTreeWidth", side: "start",
  });

  useEffect(() => {
    if (!id) { router.push("/modules"); return; }
    Promise.all([scripts.get(id), scripts.dependents(id)])
      .then(([s, deps]) => {
        setModule(s);
        setName(s.name);
        setDescription(s.description);
        setPkg(s.module_package ?? "");
        setModuleFiles(s.files);
        const contents = new Map(s.files.map(f => [f.filename, f.content]));
        contents.set("requirements.txt", s.requirements || "");
        setFileContents(contents);
        setDependents(deps);
        const main = s.files.find(f => f.is_main)?.filename ?? s.files[0]?.filename ?? MAIN_FILE;
        setActiveFile(main);
      })
      .catch(() => { toast.error(t("toast.loadFailed")); router.push("/modules"); })
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const activeContent = fileContents.get(activeFile) ?? "";
  const activeLang = getLanguage(activeFile);
  const dirty = dirtyFiles.size > 0 || metaDirty;

  function markDirty(filename: string) {
    setDirtyFiles(prev => new Set(prev).add(filename));
  }

  // ── File tree operations (modules are Scripts under the hood) ───────────────

  async function handleNewFile(filename: string) {
    const content = filename.endsWith(".py") ? "# " + filename + "\n" : "";
    await scripts.upsertFile(id, { filename, content, is_main: false });
    setModuleFiles(prev => [...prev, {
      id: `local-${Date.now()}`, script_id: id, filename, content,
      is_main: false, updated_at: new Date().toISOString(),
    }]);
    setFileContents(prev => new Map(prev).set(filename, content));
    setActiveFile(filename);
  }

  async function handleDeleteFile(filename: string) {
    await scripts.deleteFile(id, filename);
    setModuleFiles(prev => prev.filter(f => f.filename !== filename));
    setFileContents(prev => { const m = new Map(prev); m.delete(filename); return m; });
    setDirtyFiles(prev => { const s = new Set(prev); s.delete(filename); return s; });
    if (activeFile === filename) {
      const remaining = moduleFiles.filter(f => f.filename !== filename);
      setActiveFile(remaining[0]?.filename ?? MAIN_FILE);
    }
  }

  // Modules (like scripts) have no on-disk folders — deleting a folder deletes
  // every non-main file under its prefix.
  async function handleDeleteDir(path: string) {
    const prefix = path + "/";
    const victims = moduleFiles.filter(f => f.filename.startsWith(prefix) && !f.is_main);
    for (const f of victims) await scripts.deleteFile(id, f.filename);
    const names = new Set(victims.map(f => f.filename));
    setModuleFiles(prev => prev.filter(f => !names.has(f.filename)));
    setFileContents(prev => { const m = new Map(prev); for (const n of names) m.delete(n); return m; });
    setDirtyFiles(prev => { const s = new Set(prev); for (const n of names) s.delete(n); return s; });
    if (names.has(activeFile)) setActiveFile(moduleFiles.find(f => !names.has(f.filename))?.filename ?? MAIN_FILE);
  }

  async function handleRenameFile(oldName: string, newName: string) {
    const content = fileContents.get(oldName) ?? "";
    const oldFile = moduleFiles.find(f => f.filename === oldName);
    if (oldFile?.is_main) { toast.error(t("toast.renameMainForbidden")); return; }
    await scripts.upsertFile(id, { filename: newName, content, is_main: false });
    await scripts.deleteFile(id, oldName);
    setModuleFiles(prev => prev.map(f => f.filename === oldName ? { ...f, filename: newName } : f));
    setFileContents(prev => { const m = new Map(prev); m.set(newName, content); m.delete(oldName); return m; });
    setDirtyFiles(prev => { const s = new Set(prev); if (s.has(oldName)) { s.delete(oldName); s.add(newName); } return s; });
    if (activeFile === oldName) setActiveFile(newName);
  }

  async function handleUploadFiles(entries: { filename: string; content: string }[]) {
    await Promise.all(entries.map(e => scripts.upsertFile(id, { ...e, is_main: false })));
    setModuleFiles(prev => {
      const existing = new Map(prev.map(f => [f.filename, f]));
      for (const e of entries) {
        existing.set(e.filename, {
          id: existing.get(e.filename)?.id ?? `local-${e.filename}`,
          script_id: id, filename: e.filename, content: e.content,
          is_main: existing.get(e.filename)?.is_main ?? false,
          updated_at: new Date().toISOString(),
        });
      }
      return Array.from(existing.values());
    });
    setFileContents(prev => { const m = new Map(prev); for (const e of entries) m.set(e.filename, e.content); return m; });
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
      for (const fn of dirtyFiles) {
        if (fn === "requirements.txt" || fn === "__meta__") continue;
        const file = moduleFiles.find(f => f.filename === fn);
        await scripts.upsertFile(id, { filename: fn, content: fileContents.get(fn) ?? "", is_main: file?.is_main ?? false });
      }
      if (metaDirty || dirtyFiles.has("requirements.txt")) {
        await scripts.update(id, {
          name: name.trim(),
          description,
          requirements: fileContents.get("requirements.txt") ?? "",
          module_package: pkg.trim() || undefined,
        });
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
      await scripts.delete(id);
      toast.success(t("toast.deleted"));
      router.push("/modules");
    } catch (e: unknown) {
      toast.error(String(e));
      setDeleting(false);
      setDeleteOpen(false);
    }
  }

  const treeFiles: TreeFile[] = moduleFiles.map(f => ({
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
  if (!module) return null;

  return (
    <div className="h-screen flex flex-col overflow-hidden">
      {/* Header */}
      <header className="border-b border-border px-4 py-2.5 flex items-center gap-3 shrink-0">
        <Link href="/modules">
          <Button variant="ghost" size="icon"><ArrowLeft className="h-4 w-4" /></Button>
        </Link>
        <Blocks className="h-4 w-4 text-primary shrink-0" />
        <Input
          value={name}
          onChange={e => { setName(e.target.value); setMetaDirty(true); }}
          className="max-w-xs h-8 font-medium"
          placeholder={t("header.namePlaceholder")}
        />
        <span className="text-[10px] uppercase tracking-wide text-muted-foreground/70 border border-border/60 rounded px-1.5 py-0.5 shrink-0">
          {t("header.badge")}
        </span>
        <div className="flex-1" />
        <Button size="sm" onClick={handleSave} disabled={saving || !dirty}>
          {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
          {t("header.save")}
        </Button>
        <Button variant="ghost" size="icon" onClick={() => setDeleteOpen(true)} title={t("header.deleteTitle")}>
          <Trash2 className="h-4 w-4 text-destructive" />
        </Button>
      </header>

      {/* Meta strip: package name + description */}
      <div className="border-b border-border px-4 py-2 shrink-0 flex flex-col gap-2 sm:flex-row sm:items-center">
        <div className="flex items-center gap-2 shrink-0">
          <label className="text-xs text-muted-foreground shrink-0">{t("meta.packageLabel")}</label>
          <Input
            value={pkg}
            onChange={e => { setPkg(e.target.value); setMetaDirty(true); }}
            placeholder="my_module"
            className="h-8 w-40 font-mono text-xs"
          />
          <code className="text-[10px] text-muted-foreground/70 hidden sm:inline">
            {t("meta.importHint", { pkg: pkg.trim() || "my_module" })}
          </code>
        </div>
        <Textarea
          value={description}
          onChange={e => { setDescription(e.target.value); setMetaDirty(true); }}
          placeholder={t("meta.descriptionPlaceholder")}
          rows={1}
          className="text-xs resize-none min-h-0 h-8 py-1.5 flex-1"
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
              onDeleteDir={handleDeleteDir}
            />
          </div>
          {/* Used-by panel */}
          <div className="border-t border-border p-2.5 text-xs shrink-0 max-h-40 overflow-y-auto">
            <p className="text-[10px] uppercase tracking-wider font-semibold text-muted-foreground/70 mb-1.5">
              {t("usedBy.label", { count: dependents.length })}
            </p>
            {dependents.length === 0 ? (
              <p className="text-[11px] text-muted-foreground/60 leading-snug">{t("usedBy.none")}</p>
            ) : (
              <div className="space-y-0.5">
                {dependents.map(d => (
                  <Link key={d.id} href={`/script/?id=${d.id}`}
                    className="block truncate text-muted-foreground hover:text-primary transition-colors">
                    {d.name}
                  </Link>
                ))}
              </div>
            )}
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
              {dependents.length > 0
                ? t("deleteDialog.descriptionInUse", { name: module.name, count: dependents.length })
                : t("deleteDialog.description", { name: module.name })}
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
