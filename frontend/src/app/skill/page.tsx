"use client";
import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, Save, Trash2, Loader2, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { skills } from "@/lib/api";
import type { Skill, SkillFile } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription,
} from "@/components/ui/dialog";
import ScriptEditor from "@/components/ScriptEditor";
import FileTree, { type TreeFile } from "@/components/FileTree";
import { useResizable } from "@/components/Splitter";

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
      .catch(() => toast.error("Failed to load skill"))
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
    if (oldFile?.is_main) { toast.error("Cannot rename SKILL.md"); return; }
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
    if (!name.trim()) return toast.error("Name is required");
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
      toast.success("Saved");
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
      toast.success("Skill deleted");
      router.push("/tools");
    } catch (e: unknown) {
      toast.error(String(e));
      setDeleting(false);
      setDeleteOpen(false);
    }
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
          placeholder="skill-name"
        />
        <label className="flex items-center gap-1.5 text-xs text-muted-foreground cursor-pointer shrink-0">
          <input
            type="checkbox"
            checked={enabled}
            onChange={e => { setEnabled(e.target.checked); setMetaDirty(true); }}
            className="rounded"
          />
          Enabled
        </label>
        <div className="flex-1" />
        <Button size="sm" onClick={handleSave} disabled={saving || !dirty}>
          {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
          Save
        </Button>
        <Button variant="ghost" size="icon" onClick={() => setDeleteOpen(true)} title="Delete skill">
          <Trash2 className="h-4 w-4 text-destructive" />
        </Button>
      </header>

      {/* Description */}
      <div className="border-b border-border px-4 py-2 shrink-0">
        <Textarea
          value={description}
          onChange={e => { setDescription(e.target.value); setMetaDirty(true); }}
          placeholder="Description — what this skill does and when to use it (shown to the agent)"
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
            />
          </div>
        </div>
      </div>

      {/* Delete confirmation */}
      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>Delete skill?</DialogTitle>
            <DialogDescription>
              This permanently removes “{skill.name}” and all its files. Scripts bound to it
              will simply stop loading it.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteOpen(false)}>Cancel</Button>
            <Button variant="destructive" onClick={handleDelete} disabled={deleting}>
              {deleting ? "Deleting…" : "Delete"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
