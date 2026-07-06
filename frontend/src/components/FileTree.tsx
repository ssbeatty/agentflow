"use client";

import { useState, useRef, useCallback } from "react";
import {
  FileCode2, FileText, File, Package, Braces, Terminal,
  Folder, FolderOpen, ChevronRight, ChevronDown,
  Plus, FolderPlus, Upload, FolderUp, Download, Trash2, Check, X, Pencil,
} from "lucide-react";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import { ScrollArea } from "@/components/ui/scroll-area";

export interface TreeFile {
  filename: string;
  is_main: boolean;
  isDirty: boolean;
}

interface Props {
  files: TreeFile[];
  activeFile: string;
  onSelect: (filename: string) => void;
  onNewFile: (filename: string) => Promise<void>;
  onDeleteFile: (filename: string) => Promise<void>;
  onRenameFile: (oldName: string, newName: string) => Promise<void>;
  onUploadFiles: (entries: { filename: string; content: string }[]) => Promise<void>;
  onDownloadFile: (filename: string) => void;
  /** Pin a requirements.txt row at the bottom (scripts). Off for skills. */
  showRequirements?: boolean;
  /** Directories that exist on their own (incl. empty ones) — shown in the tree. */
  emptyDirs?: string[];
  /** Persist a real (possibly empty) folder. When provided, "New folder" creates
   *  the folder immediately instead of chaining into naming its first file. */
  onNewFolder?: (path: string) => Promise<void>;
  /** Delete a folder and everything under it. When provided, dir rows / the dir
   *  context menu offer a "Delete folder" action. */
  onDeleteDir?: (path: string) => Promise<void>;
}

const REQ = "requirements.txt";

type ContextMenu =
  | { type: "file"; x: number; y: number; filename: string; isMain: boolean; isReq: boolean }
  | { type: "dir"; x: number; y: number; path: string }
  | { type: "blank"; x: number; y: number }
  | null;

// ── Tree model ────────────────────────────────────────────────────────────────
type FileNode = { kind: "file"; name: string; path: string; file: TreeFile };
type DirNode = { kind: "dir"; name: string; path: string; children: TreeNode[] };
type TreeNode = FileNode | DirNode;

function buildTree(files: TreeFile[], extraDirs: string[] = []): TreeNode[] {
  const root: DirNode = { kind: "dir", name: "", path: "", children: [] };
  const dirs = new Map<string, DirNode>([["", root]]);

  function ensureDir(path: string): DirNode {
    const existing = dirs.get(path);
    if (existing) return existing;
    const idx = path.lastIndexOf("/");
    const parentPath = idx >= 0 ? path.slice(0, idx) : "";
    const name = idx >= 0 ? path.slice(idx + 1) : path;
    const parent = ensureDir(parentPath);
    const dir: DirNode = { kind: "dir", name, path, children: [] };
    parent.children.push(dir);
    dirs.set(path, dir);
    return dir;
  }

  for (const d of extraDirs) if (d) ensureDir(d);
  for (const f of files) {
    const parts = f.filename.split("/");
    const base = parts.pop() as string;
    const parent = ensureDir(parts.join("/"));
    parent.children.push({ kind: "file", name: base, path: f.filename, file: f });
  }
  sortNodes(root.children);
  return root.children;
}

function sortNodes(nodes: TreeNode[]) {
  nodes.sort((a, b) => {
    if (a.kind !== b.kind) return a.kind === "dir" ? -1 : 1; // folders first
    if (a.kind === "file" && b.kind === "file") {
      if (a.file.is_main !== b.file.is_main) return a.file.is_main ? -1 : 1;
      const aPy = a.name.endsWith(".py") ? 0 : 1;
      const bPy = b.name.endsWith(".py") ? 0 : 1;
      if (aPy !== bPy) return aPy - bPy;
    }
    return a.name.localeCompare(b.name);
  });
  for (const n of nodes) if (n.kind === "dir") sortNodes(n.children);
}

export function getFileIcon(filename: string): { Icon: React.ElementType; cls: string } {
  const base = filename.split("/").pop() ?? filename;
  if (base === REQ) return { Icon: Package, cls: "text-amber-400" };
  const ext = base.split(".").pop()?.toLowerCase() ?? "";
  if (ext === "py") return { Icon: FileCode2, cls: "text-blue-400" };
  if (ext === "json") return { Icon: Braces, cls: "text-emerald-400" };
  if (ext === "sh" || ext === "bash") return { Icon: Terminal, cls: "text-yellow-400" };
  if (ext === "yaml" || ext === "yml") return { Icon: FileText, cls: "text-purple-400" };
  if (ext === "md") return { Icon: FileText, cls: "text-slate-400" };
  if (ext === "txt") return { Icon: FileText, cls: "text-muted-foreground" };
  return { Icon: File, cls: "text-muted-foreground" };
}

// ── Drag & drop / folder traversal helpers ──────────────────────────────────────
type Entry = { filename: string; content: string };

async function readFileEntry(entry: any): Promise<File> {
  return new Promise((resolve, reject) => entry.file(resolve, reject));
}

async function readAllDirEntries(reader: any): Promise<any[]> {
  const out: any[] = [];
  // readEntries returns at most 100 at a time — call until it yields none.
  for (;;) {
    const batch: any[] = await new Promise((resolve, reject) => reader.readEntries(resolve, reject));
    if (!batch.length) break;
    out.push(...batch);
  }
  return out;
}

/** Walk a dropped FileSystemDirectoryEntry, collecting files with paths relative
 *  to (but NOT including) the dropped folder itself. */
async function walkDirEntry(dirEntry: any, base: string, out: Entry[]) {
  const entries = await readAllDirEntries(dirEntry.createReader());
  for (const e of entries) {
    const rel = base ? `${base}/${e.name}` : e.name;
    if (e.isFile) {
      const file = await readFileEntry(e);
      out.push({ filename: rel, content: await file.text() });
    } else if (e.isDirectory) {
      await walkDirEntry(e, rel, out);
    }
  }
}

export default function FileTree({
  files, activeFile, onSelect, onNewFile, onDeleteFile, onRenameFile,
  onUploadFiles, onDownloadFile, showRequirements = true,
  emptyDirs = [], onNewFolder, onDeleteDir,
}: Props) {
  const { t } = useTranslation("scriptEditor");
  const [renamingFile, setRenamingFile] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [addingIn, setAddingIn] = useState<string | null>(null); // dir path prefix while adding a file, or null
  const [newFileName, setNewFileName] = useState("");
  const [addingFolderIn, setAddingFolderIn] = useState<string | null>(null); // dir path prefix while adding a folder, or null
  const [newFolderName, setNewFolderName] = useState("");
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  const [pendingDeleteDir, setPendingDeleteDir] = useState<string | null>(null);
  const [isDragOver, setIsDragOver] = useState(false);
  const [contextMenu, setContextMenu] = useState<ContextMenu>(null);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  const uploadRef = useRef<HTMLInputElement>(null);
  const uploadDirRef = useRef<HTMLInputElement>(null);
  const renameInputRef = useRef<HTMLInputElement>(null);
  const newFileInputRef = useRef<HTMLInputElement>(null);
  const newFolderInputRef = useRef<HTMLInputElement>(null);

  // The context menu is dismissed by a full-screen backdrop rendered below it
  // (see the JSX). A previous window-level capture-phase "click" listener raced
  // with the menu buttons' own onClick and swallowed them — the backdrop avoids
  // that entirely because the menu panel sits above it and receives clicks first.

  const showReq = showRequirements;
  const tree = buildTree(files.filter(f => f.filename !== REQ), emptyDirs);
  const reqEntry: TreeFile | null = showReq
    ? (files.find(f => f.filename === REQ) ?? { filename: REQ, is_main: false, isDirty: false })
    : null;

  // Directory paths that actually exist (from files, plus standalone/empty dirs).
  const dirPaths = new Set<string>();
  for (const d of emptyDirs) {
    const parts = d.split("/");
    let acc = "";
    for (const p of parts) { acc = acc ? `${acc}/${p}` : p; dirPaths.add(acc); }
  }
  for (const f of files) {
    const parts = f.filename.split("/"); parts.pop();
    let acc = "";
    for (const p of parts) { acc = acc ? `${acc}/${p}` : p; dirPaths.add(acc); }
  }
  // When creating a file inside a not-yet-existing folder (i.e. right after
  // "New folder"), the folder has no tree node to host the input — render it at
  // the root with the folder shown as a prefix so the first file can be named.
  const pendingFilePrefix = addingIn && addingIn !== "" && !dirPaths.has(addingIn) ? addingIn : null;

  function toggleDir(path: string) {
    setCollapsed(prev => {
      const s = new Set(prev);
      if (s.has(path)) s.delete(path); else s.add(path);
      return s;
    });
  }

  /* ── Rename (basename only, keeps the folder prefix) ── */
  function startRename(filename: string) {
    const baseName = filename.includes("/") ? filename.slice(filename.lastIndexOf("/") + 1) : filename;
    setRenamingFile(filename);
    setRenameValue(baseName);
    setContextMenu(null);
    setTimeout(() => renameInputRef.current?.select(), 0);
  }

  async function commitRename() {
    if (!renamingFile) return;
    const trimmed = renameValue.trim();
    const prefix = renamingFile.includes("/") ? renamingFile.slice(0, renamingFile.lastIndexOf("/") + 1) : "";
    const newFull = prefix + trimmed;
    if (trimmed && newFull !== renamingFile) {
      try { await onRenameFile(renamingFile, newFull); }
      catch (e) { toast.error(String(e)); }
    }
    setRenamingFile(null);
  }

  /* ── New file (optionally inside a folder) ── */
  function startAddNew(dirPath: string = "") {
    setAddingFolderIn(null);
    setAddingIn(dirPath);
    setNewFileName("");
    setContextMenu(null);
    if (dirPath) setCollapsed(prev => { const s = new Set(prev); s.delete(dirPath); return s; });
    setTimeout(() => newFileInputRef.current?.focus(), 0);
  }

  async function commitNewFile() {
    const name = newFileName.trim();
    if (!name) { setAddingIn(null); return; }
    const full = addingIn ? `${addingIn}/${name}` : name;
    try { await onNewFile(full); }
    catch (e) { toast.error(String(e)); }
    setAddingIn(null);
    setNewFileName("");
  }

  /* ── New folder. When onNewFolder is wired (skills, disk-backed) the folder is
        persisted immediately (empty folders are fine on disk). Otherwise (scripts,
        where a dir exists only via a file) we chain into naming its first file. ── */
  function startAddFolder(dirPath: string = "") {
    setAddingIn(null);
    setAddingFolderIn(dirPath);
    setNewFolderName("");
    setContextMenu(null);
    if (dirPath) setCollapsed(prev => { const s = new Set(prev); s.delete(dirPath); return s; });
    setTimeout(() => newFolderInputRef.current?.focus(), 0);
  }

  async function commitNewFolder() {
    const name = newFolderName.trim().replace(/^\/+|\/+$/g, "");
    const parent = addingFolderIn;
    setAddingFolderIn(null);
    setNewFolderName("");
    if (!name) return;
    const folder = parent ? `${parent}/${name}` : name;
    if (onNewFolder) {
      try { await onNewFolder(folder); }
      catch (e) { toast.error(String(e)); return; }
      setCollapsed(prev => { const s = new Set(prev); s.delete(folder); return s; });
    } else {
      startAddNew(folder); // no persistence → name the first file inside it
    }
  }

  async function commitDeleteDir(path: string) {
    if (!onDeleteDir || !path) { setPendingDeleteDir(null); return; }
    try { await onDeleteDir(path); }
    catch (e) { toast.error(String(e)); }
    finally { setPendingDeleteDir(null); }
  }

  /* ── Upload: individual files (basename) ── */
  async function handleUploadInput(e: React.ChangeEvent<HTMLInputElement>) {
    const picked = Array.from(e.target.files ?? []);
    if (!picked.length) return;
    const entries = await Promise.all(picked.map(async f => ({ filename: f.name, content: await f.text() })));
    await doUpload(entries);
    e.target.value = "";
  }

  /* ── Upload: a whole folder, preserving structure (drops the top folder name
        so its CONTENTS map to this item's root — ideal for importing a skill). ── */
  async function handleUploadDirInput(e: React.ChangeEvent<HTMLInputElement>) {
    const picked = Array.from(e.target.files ?? []);
    if (!picked.length) return;
    const entries = await Promise.all(picked.map(async f => {
      const rel = (f as any).webkitRelativePath as string | undefined;
      const stripped = rel ? rel.split("/").slice(1).join("/") : f.name; // drop chosen folder name
      return { filename: stripped || f.name, content: await f.text() };
    }));
    await doUpload(entries.filter(e => e.filename));
    e.target.value = "";
  }

  async function doUpload(entries: Entry[]) {
    if (!entries.length) return;
    try {
      await onUploadFiles(entries);
      toast.success(t("fileTree.toast.filesUploaded", { count: entries.length }));
    } catch (e) { toast.error(String(e)); }
  }

  /* ── Drag & drop (supports files AND folders) ── */
  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault(); e.dataTransfer.dropEffect = "copy"; setIsDragOver(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    if (!e.currentTarget.contains(e.relatedTarget as Node)) setIsDragOver(false);
  }, []);

  const handleDrop = useCallback(async (e: React.DragEvent) => {
    e.preventDefault(); setIsDragOver(false);
    const items = Array.from(e.dataTransfer.items ?? []);
    const roots = items
      .map(it => (it.webkitGetAsEntry ? it.webkitGetAsEntry() : null))
      .filter(Boolean) as any[];

    const out: Entry[] = [];
    if (roots.length) {
      for (const entry of roots) {
        if (entry.isFile) {
          const file = await readFileEntry(entry);
          out.push({ filename: entry.name, content: await file.text() });
        } else if (entry.isDirectory) {
          await walkDirEntry(entry, "", out); // contents map to root
        }
      }
    } else {
      // Fallback: no entry API — flat files only.
      const dropped = Array.from(e.dataTransfer.files);
      for (const f of dropped) out.push({ filename: f.name, content: await f.text() });
    }
    await doUpload(out);
  }, [onUploadFiles]); // eslint-disable-line react-hooks/exhaustive-deps

  /* ── Context menus ── */
  function fileContextMenu(e: React.MouseEvent, node: FileNode) {
    e.preventDefault(); e.stopPropagation();
    setContextMenu({
      type: "file", x: e.clientX, y: e.clientY,
      filename: node.path, isMain: node.file.is_main, isReq: node.path === REQ,
    });
  }
  function dirContextMenu(e: React.MouseEvent, path: string) {
    e.preventDefault(); e.stopPropagation();
    setContextMenu({ type: "dir", x: e.clientX, y: e.clientY, path });
  }
  function blankContextMenu(e: React.MouseEvent) {
    e.preventDefault();
    setContextMenu({ type: "blank", x: e.clientX, y: e.clientY });
  }

  // ── Row renderers ──────────────────────────────────────────────────────────
  function renderFileRow(node: FileNode, depth: number) {
    const entry = node.file;
    const { Icon, cls } = getFileIcon(entry.filename);
    const isActive = entry.filename === activeFile;
    const isRenaming = renamingFile === entry.filename;
    const isDeleting = pendingDelete === entry.filename;
    const canDelete = !entry.is_main && entry.filename !== REQ;
    const canRename = entry.filename !== REQ;
    const pad = 8 + depth * 12;

    if (isRenaming) {
      return (
        <div key={entry.filename} className="flex items-center gap-1.5 pr-2 h-[22px] bg-[#2a2d2e]" style={{ paddingLeft: pad }}>
          <Icon className={`h-3.5 w-3.5 shrink-0 ${cls}`} />
          <input
            ref={renameInputRef}
            value={renameValue}
            onChange={e => setRenameValue(e.target.value)}
            onKeyDown={e => {
              if (e.key === "Enter") { e.preventDefault(); commitRename(); }
              if (e.key === "Escape") setRenamingFile(null);
            }}
            onBlur={commitRename}
            className="flex-1 min-w-0 bg-[#1a1a1a] border border-[#007acc] rounded-sm px-1.5 h-[18px] text-xs font-mono text-foreground focus:outline-none"
            spellCheck={false}
          />
        </div>
      );
    }

    if (isDeleting) {
      return (
        <div key={entry.filename} className="flex items-center gap-1.5 pr-2 h-[22px] bg-destructive/15" style={{ paddingLeft: pad }}>
          <Icon className={`h-3.5 w-3.5 shrink-0 ${cls}`} />
          <span className="flex-1 text-xs font-mono truncate min-w-0 text-muted-foreground">{node.name}</span>
          <span className="text-[10px] text-muted-foreground mr-1 shrink-0">{t("fileTree.deleteConfirm")}</span>
          <button onClick={async () => {
            try { await onDeleteFile(entry.filename); }
            catch (e) { toast.error(String(e)); }
            finally { setPendingDelete(null); }
          }} className="h-4 w-4 rounded flex items-center justify-center text-destructive hover:bg-destructive/20 shrink-0" title={t("fileTree.confirm")}>
            <Check className="h-3 w-3" />
          </button>
          <button onClick={() => setPendingDelete(null)}
            className="h-4 w-4 rounded flex items-center justify-center text-muted-foreground hover:bg-white/10 shrink-0" title={t("fileTree.cancel")}>
            <X className="h-3 w-3" />
          </button>
        </div>
      );
    }

    return (
      <div
        key={entry.filename}
        onClick={() => onSelect(entry.filename)}
        onDoubleClick={() => canRename && startRename(entry.filename)}
        onContextMenu={e => fileContextMenu(e, node)}
        title={entry.filename}
        style={{ paddingLeft: pad }}
        className={`group flex items-center gap-1.5 pr-2 h-[22px] cursor-pointer transition-colors ${
          isActive ? "bg-[#37373d] text-white" : "text-[#bbb] hover:bg-[#2a2d2e] hover:text-white"
        }`}
      >
        <Icon className={`h-3.5 w-3.5 shrink-0 ${cls}`} />
        <span className="flex-1 text-xs font-mono truncate min-w-0">{node.name}</span>

        <div className="flex items-center gap-1 group-hover:hidden shrink-0">
          {entry.isDirty && <span className="h-[7px] w-[7px] rounded-full bg-foreground/50 shrink-0" title={t("fileTree.unsaved")} />}
          {entry.is_main && <span className="text-[9px] px-1 rounded-sm border border-border/50 text-muted-foreground/60 font-mono leading-4 shrink-0">{t("fileTree.mainBadge")}</span>}
        </div>

        <div className="hidden group-hover:flex items-center gap-0.5 shrink-0">
          <button onClick={e => { e.stopPropagation(); onDownloadFile(entry.filename); }}
            className="h-5 w-5 rounded flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-white/10 transition-colors" title={t("fileTree.actions.download")}>
            <Download className="h-3 w-3" />
          </button>
          {canDelete && (
            <button onClick={e => { e.stopPropagation(); setPendingDelete(entry.filename); }}
              className="h-5 w-5 rounded flex items-center justify-center text-muted-foreground hover:text-destructive hover:bg-white/10 transition-colors" title={t("fileTree.actions.delete")}>
              <Trash2 className="h-3 w-3" />
            </button>
          )}
        </div>
      </div>
    );
  }

  function renderDirRow(node: DirNode, depth: number) {
    const open = !collapsed.has(node.path);
    const pad = 8 + depth * 12;
    const Chevron = open ? ChevronDown : ChevronRight;
    const FolderIcon = open ? FolderOpen : Folder;
    const isDeleting = pendingDeleteDir === node.path;

    if (isDeleting) {
      return (
        <div key={`dir:${node.path}`}>
          <div className="flex items-center gap-1 pr-2 h-[22px] bg-destructive/15" style={{ paddingLeft: pad }}>
            <Folder className="h-3.5 w-3.5 shrink-0 text-sky-400/80" />
            <span className="flex-1 text-xs font-mono truncate min-w-0 text-muted-foreground">{node.name}</span>
            <span className="text-[10px] text-muted-foreground mr-1 shrink-0">{t("fileTree.deleteFolderConfirm")}</span>
            <button onClick={() => commitDeleteDir(node.path)}
              className="h-4 w-4 rounded flex items-center justify-center text-destructive hover:bg-destructive/20 shrink-0" title={t("fileTree.confirm")}>
              <Check className="h-3 w-3" />
            </button>
            <button onClick={() => setPendingDeleteDir(null)}
              className="h-4 w-4 rounded flex items-center justify-center text-muted-foreground hover:bg-white/10 shrink-0" title={t("fileTree.cancel")}>
              <X className="h-3 w-3" />
            </button>
          </div>
        </div>
      );
    }

    return (
      <div key={`dir:${node.path}`}>
        <div
          onClick={() => toggleDir(node.path)}
          onContextMenu={e => dirContextMenu(e, node.path)}
          title={node.path}
          style={{ paddingLeft: pad }}
          className="group flex items-center gap-1 pr-2 h-[22px] cursor-pointer text-[#bbb] hover:bg-[#2a2d2e] hover:text-white transition-colors"
        >
          <Chevron className="h-3 w-3 shrink-0 text-muted-foreground/70" />
          <FolderIcon className="h-3.5 w-3.5 shrink-0 text-sky-400/80" />
          <span className="flex-1 text-xs font-mono truncate min-w-0">{node.name}</span>
          <div className="hidden group-hover:flex items-center gap-0.5 shrink-0">
            <button onClick={e => { e.stopPropagation(); startAddNew(node.path); }}
              className="h-5 w-5 rounded flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-white/10 transition-colors" title={t("fileTree.actions.newFileInFolder")}>
              <Plus className="h-3 w-3" />
            </button>
            {onDeleteDir && (
              <button onClick={e => { e.stopPropagation(); setPendingDeleteDir(node.path); }}
                className="h-5 w-5 rounded flex items-center justify-center text-muted-foreground hover:text-destructive hover:bg-white/10 transition-colors" title={t("fileTree.actions.deleteFolder")}>
                <Trash2 className="h-3 w-3" />
              </button>
            )}
          </div>
        </div>
        {open && (
          <>
            {node.children.map(c => c.kind === "dir" ? renderDirRow(c, depth + 1) : renderFileRow(c, depth + 1))}
            {addingFolderIn === node.path && renderNewFolderInput(depth + 1)}
            {addingIn === node.path && renderNewFileInput(depth + 1)}
          </>
        )}
      </div>
    );
  }

  function renderNewFileInput(depth: number, prefix = "") {
    return (
      <div className="flex items-center gap-1.5 pr-2 h-[22px] bg-[#2a2d2e]" style={{ paddingLeft: 8 + depth * 12 }}>
        <File className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        {prefix && <span className="text-[10px] text-muted-foreground/60 font-mono shrink-0">{prefix}/</span>}
        <input
          ref={newFileInputRef}
          value={newFileName}
          onChange={e => setNewFileName(e.target.value)}
          onKeyDown={e => {
            if (e.key === "Enter") { e.preventDefault(); commitNewFile(); }
            if (e.key === "Escape") { setAddingIn(null); setNewFileName(""); }
          }}
          onBlur={() => { if (!newFileName.trim()) setAddingIn(null); else commitNewFile(); }}
          placeholder={t("fileTree.placeholder.filename")}
          className="flex-1 min-w-0 bg-[#1a1a1a] border border-[#007acc] rounded-sm px-1.5 h-[18px] text-xs font-mono text-foreground placeholder:text-muted-foreground/40 focus:outline-none"
          spellCheck={false}
        />
      </div>
    );
  }

  function renderNewFolderInput(depth: number) {
    return (
      <div className="flex items-center gap-1.5 pr-2 h-[22px] bg-[#2a2d2e]" style={{ paddingLeft: 8 + depth * 12 }}>
        <Folder className="h-3.5 w-3.5 shrink-0 text-sky-400/80" />
        <input
          ref={newFolderInputRef}
          value={newFolderName}
          onChange={e => setNewFolderName(e.target.value)}
          onKeyDown={e => {
            if (e.key === "Enter") { e.preventDefault(); commitNewFolder(); }
            if (e.key === "Escape") { setAddingFolderIn(null); setNewFolderName(""); }
          }}
          onBlur={() => { if (!newFolderName.trim()) setAddingFolderIn(null); else commitNewFolder(); }}
          placeholder={t("fileTree.placeholder.folderName")}
          className="flex-1 min-w-0 bg-[#1a1a1a] border border-[#007acc] rounded-sm px-1.5 h-[18px] text-xs font-mono text-foreground placeholder:text-muted-foreground/40 focus:outline-none"
          spellCheck={false}
        />
      </div>
    );
  }

  return (
    <div
      className={`relative flex flex-col h-full select-none border-r border-border transition-colors ${
        isDragOver ? "bg-primary/5 ring-2 ring-inset ring-primary/30" : "bg-[#1e1e1e]"
      }`}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      onContextMenu={blankContextMenu}
    >
      {/* Toolbar */}
      <div className="flex items-center px-2 border-b border-border shrink-0 h-8">
        <span className="text-[10px] uppercase tracking-widest text-muted-foreground/60 font-semibold flex-1 pl-0.5">
          {t("fileTree.explorer")}
        </span>
        <button onClick={() => startAddNew("")} title={t("fileTree.actions.newFile")}
          className="h-5 w-5 rounded flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-white/10 transition-colors">
          <Plus className="h-3.5 w-3.5" />
        </button>
        <button onClick={() => startAddFolder("")} title={t("fileTree.actions.newFolder")}
          className="h-5 w-5 rounded flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-white/10 transition-colors ml-0.5">
          <FolderPlus className="h-3.5 w-3.5" />
        </button>
        <button onClick={() => uploadRef.current?.click()} title={t("fileTree.actions.uploadFiles")}
          className="h-5 w-5 rounded flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-white/10 transition-colors ml-0.5">
          <Upload className="h-3.5 w-3.5" />
        </button>
        <button onClick={() => uploadDirRef.current?.click()} title={t("fileTree.actions.uploadFolderHint")}
          className="h-5 w-5 rounded flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-white/10 transition-colors ml-0.5">
          <FolderUp className="h-3.5 w-3.5" />
        </button>
      </div>

      <input ref={uploadRef} type="file" multiple className="hidden" onChange={handleUploadInput} />
      {/* webkitdirectory: folder picker. Non-standard attrs via spread to satisfy TS. */}
      <input
        ref={uploadDirRef}
        type="file"
        className="hidden"
        onChange={handleUploadDirInput}
        {...({ webkitdirectory: "", directory: "", mozdirectory: "" } as any)}
      />

      {/* File list */}
      <ScrollArea className="flex-1">
        <div className="py-0.5">
          {tree.map(n => n.kind === "dir" ? renderDirRow(n, 0) : renderFileRow(n, 0))}

          {/* Root-level new folder / new file inputs */}
          {addingFolderIn === "" && renderNewFolderInput(0)}
          {addingIn === "" && renderNewFileInput(0)}
          {/* First file of a brand-new folder (no tree node exists yet) */}
          {pendingFilePrefix && renderNewFileInput(0, pendingFilePrefix)}

          {/* Pinned requirements.txt (scripts only) */}
          {reqEntry && renderFileRow({ kind: "file", name: REQ, path: REQ, file: reqEntry }, 0)}
        </div>
      </ScrollArea>

      {/* Drop overlay */}
      {isDragOver && (
        <div className="absolute inset-0 flex items-end justify-center pb-4 pointer-events-none">
          <div className="text-xs text-primary font-medium bg-background/90 px-3 py-1.5 rounded-md border border-primary/40 shadow">
            {t("fileTree.dropOverlay")}
          </div>
        </div>
      )}

      {/* Backdrop: dismisses the context menu on any outside click / right-click.
          Sits at z-40, below the menu panels (z-50), so menu buttons get the click. */}
      {contextMenu && (
        <div
          className="fixed inset-0 z-40"
          onClick={() => setContextMenu(null)}
          onContextMenu={e => { e.preventDefault(); setContextMenu(null); }}
        />
      )}

      {/* Context menus */}
      {contextMenu?.type === "file" && (
        <FileContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          filename={contextMenu.filename}
          canRename={!contextMenu.isReq}
          canDelete={!contextMenu.isMain && !contextMenu.isReq}
          onRename={() => { setContextMenu(null); startRename(contextMenu.filename); }}
          onDownload={() => { setContextMenu(null); onDownloadFile(contextMenu.filename); }}
          onDelete={() => { setContextMenu(null); setPendingDelete(contextMenu.filename); }}
        />
      )}
      {contextMenu?.type === "dir" && (
        <DirContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          onNewFile={() => { const p = contextMenu.path; setContextMenu(null); startAddNew(p); }}
          onNewFolder={() => { const p = contextMenu.path; setContextMenu(null); startAddFolder(p); }}
          onUpload={() => { setContextMenu(null); uploadRef.current?.click(); }}
          onDelete={onDeleteDir ? () => { const p = contextMenu.path; setContextMenu(null); setPendingDeleteDir(p); } : undefined}
        />
      )}
      {contextMenu?.type === "blank" && (
        <DirContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          onNewFile={() => { setContextMenu(null); startAddNew(""); }}
          onNewFolder={() => { setContextMenu(null); startAddFolder(""); }}
          onUpload={() => { setContextMenu(null); uploadRef.current?.click(); }}
          onUploadFolder={() => { setContextMenu(null); uploadDirRef.current?.click(); }}
        />
      )}
    </div>
  );
}

/* ── Directory / blank-area context menu ─────────────────────────────────────── */

function DirContextMenu({ x, y, onNewFile, onNewFolder, onUpload, onUploadFolder, onDelete }: {
  x: number; y: number; onNewFile: () => void; onNewFolder?: () => void;
  onUpload: () => void; onUploadFolder?: () => void; onDelete?: () => void;
}) {
  const { t } = useTranslation("scriptEditor");
  const rows = 2 + (onNewFolder ? 1 : 0) + (onUploadFolder ? 1 : 0) + (onDelete ? 1 : 0);
  const menuW = 170, menuH = 12 + rows * 28;
  const adjX = x + menuW > window.innerWidth ? x - menuW : x;
  const adjY = y + menuH > window.innerHeight ? y - menuH : y;
  return (
    <div
      className="fixed z-50 min-w-[170px] rounded-md border border-border bg-popover shadow-lg py-1 text-sm"
      style={{ left: adjX, top: adjY }}
      onClick={e => e.stopPropagation()}
      onContextMenu={e => e.preventDefault()}
    >
      <button onClick={onNewFile}
        className="w-full flex items-center gap-2 px-3 py-1.5 text-xs hover:bg-secondary transition-colors text-left">
        <Plus className="h-3 w-3 text-muted-foreground" />
        {t("fileTree.actions.newFile")}
      </button>
      {onNewFolder && (
        <button onClick={onNewFolder}
          className="w-full flex items-center gap-2 px-3 py-1.5 text-xs hover:bg-secondary transition-colors text-left">
          <FolderPlus className="h-3 w-3 text-muted-foreground" />
          {t("fileTree.actions.newFolder")}
        </button>
      )}
      <button onClick={onUpload}
        className="w-full flex items-center gap-2 px-3 py-1.5 text-xs hover:bg-secondary transition-colors text-left">
        <Upload className="h-3 w-3 text-muted-foreground" />
        {t("fileTree.actions.uploadFiles")}
      </button>
      {onUploadFolder && (
        <button onClick={onUploadFolder}
          className="w-full flex items-center gap-2 px-3 py-1.5 text-xs hover:bg-secondary transition-colors text-left">
          <FolderUp className="h-3 w-3 text-muted-foreground" />
          {t("fileTree.actions.uploadFolder")}
        </button>
      )}
      {onDelete && (
        <>
          <div className="h-px bg-border/60 my-1" />
          <button onClick={onDelete}
            className="w-full flex items-center gap-2 px-3 py-1.5 text-xs hover:bg-destructive/10 text-destructive transition-colors text-left">
            <Trash2 className="h-3 w-3" />
            {t("fileTree.actions.deleteFolder")}
          </button>
        </>
      )}
    </div>
  );
}

/* ── File context menu panel ─────────────────────────────────────────────────── */

function FileContextMenu({
  x, y, filename, canRename, canDelete, onRename, onDownload, onDelete,
}: {
  x: number; y: number; filename: string;
  canRename: boolean; canDelete: boolean;
  onRename: () => void; onDownload: () => void; onDelete: () => void;
}) {
  const { t } = useTranslation("scriptEditor");
  const menuW = 180, menuH = canDelete ? 116 : 84;
  const adjX = x + menuW > window.innerWidth ? x - menuW : x;
  const adjY = y + menuH > window.innerHeight ? y - menuH : y;

  return (
    <div
      className="fixed z-50 min-w-[180px] rounded-md border border-border bg-popover shadow-lg py-1 text-sm"
      style={{ left: adjX, top: adjY }}
      onClick={e => e.stopPropagation()}
      onContextMenu={e => e.preventDefault()}
    >
      <div className="px-2 py-1 text-[10px] text-muted-foreground/70 font-mono truncate border-b border-border/60 mb-1">
        {filename.split("/").pop()}
      </div>

      {canRename && (
        <button onClick={onRename}
          className="w-full flex items-center gap-2 px-3 py-1.5 text-xs hover:bg-secondary transition-colors text-left">
          <Pencil className="h-3 w-3 text-muted-foreground" />
          {t("fileTree.actions.rename")}
          <span className="ml-auto text-[10px] text-muted-foreground/60">F2</span>
        </button>
      )}
      <button onClick={onDownload}
        className="w-full flex items-center gap-2 px-3 py-1.5 text-xs hover:bg-secondary transition-colors text-left">
        <Download className="h-3 w-3 text-muted-foreground" />
        {t("fileTree.actions.download")}
      </button>

      {canDelete && (
        <>
          <div className="h-px bg-border/60 my-1" />
          <button onClick={onDelete}
            className="w-full flex items-center gap-2 px-3 py-1.5 text-xs hover:bg-destructive/10 text-destructive transition-colors text-left">
            <Trash2 className="h-3 w-3" />
            {t("fileTree.actions.delete")}
          </button>
        </>
      )}
    </div>
  );
}
