"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import {
  FileCode2, FileText, File, Package, Braces, Terminal,
  Plus, Upload, Download, Trash2, Check, X, Pencil,
} from "lucide-react";
import { toast } from "sonner";
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
}

type ContextMenu =
  | { type: "file"; x: number; y: number; filename: string; isMain: boolean; isReq: boolean }
  | { type: "blank"; x: number; y: number }
  | null;

export function getFileIcon(filename: string): { Icon: React.ElementType; cls: string } {
  if (filename === "requirements.txt") return { Icon: Package, cls: "text-amber-400" };
  const ext = filename.split(".").pop()?.toLowerCase() ?? "";
  if (ext === "py") return { Icon: FileCode2, cls: "text-blue-400" };
  if (ext === "json") return { Icon: Braces, cls: "text-emerald-400" };
  if (ext === "sh" || ext === "bash") return { Icon: Terminal, cls: "text-yellow-400" };
  if (ext === "yaml" || ext === "yml") return { Icon: FileText, cls: "text-purple-400" };
  if (ext === "md") return { Icon: FileText, cls: "text-slate-400" };
  if (ext === "txt") return { Icon: FileText, cls: "text-muted-foreground" };
  return { Icon: File, cls: "text-muted-foreground" };
}

export default function FileTree({
  files, activeFile, onSelect, onNewFile, onDeleteFile, onRenameFile, onUploadFiles, onDownloadFile,
}: Props) {
  const [renamingFile, setRenamingFile] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [addingNew, setAddingNew] = useState(false);
  const [newFileName, setNewFileName] = useState("");
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  const [isDragOver, setIsDragOver] = useState(false);
  const [contextMenu, setContextMenu] = useState<ContextMenu>(null);

  const uploadRef = useRef<HTMLInputElement>(null);
  const renameInputRef = useRef<HTMLInputElement>(null);
  const newFileInputRef = useRef<HTMLInputElement>(null);

  // Close context menu on outside click
  useEffect(() => {
    if (!contextMenu) return;
    const close = () => setContextMenu(null);
    window.addEventListener("click", close, true);
    window.addEventListener("contextmenu", close, true);
    return () => {
      window.removeEventListener("click", close, true);
      window.removeEventListener("contextmenu", close, true);
    };
  }, [!!contextMenu]); // eslint-disable-line react-hooks/exhaustive-deps

  // Sort: main.py first → other .py → other files → requirements.txt last
  const reqEntry = files.find(f => f.filename === "requirements.txt")
    ?? { filename: "requirements.txt", is_main: false, isDirty: false };
  const rest = files
    .filter(f => f.filename !== "requirements.txt")
    .sort((a, b) => {
      if (a.is_main !== b.is_main) return a.is_main ? -1 : 1;
      const aPy = a.filename.endsWith(".py") ? 0 : 1;
      const bPy = b.filename.endsWith(".py") ? 0 : 1;
      if (aPy !== bPy) return aPy - bPy;
      return a.filename.localeCompare(b.filename);
    });
  const allEntries: TreeFile[] = [...rest, reqEntry];

  /* ── Rename ── */
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

  /* ── New file ── */
  function startAddNew() {
    setAddingNew(true);
    setNewFileName("");
    setTimeout(() => newFileInputRef.current?.focus(), 0);
  }

  async function commitNewFile() {
    const name = newFileName.trim();
    if (!name) { setAddingNew(false); return; }
    try { await onNewFile(name); }
    catch (e) { toast.error(String(e)); }
    setAddingNew(false);
    setNewFileName("");
  }

  /* ── Upload ── */
  async function handleUploadInput(e: React.ChangeEvent<HTMLInputElement>) {
    const picked = Array.from(e.target.files ?? []);
    if (!picked.length) return;
    const entries = await Promise.all(picked.map(async f => ({ filename: f.name, content: await f.text() })));
    try {
      await onUploadFiles(entries);
      toast.success(`${entries.length} file${entries.length > 1 ? "s" : ""} uploaded`);
    } catch (e) { toast.error(String(e)); }
    e.target.value = "";
  }

  /* ── Drag & drop ── */
  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault(); e.dataTransfer.dropEffect = "copy"; setIsDragOver(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    if (!e.currentTarget.contains(e.relatedTarget as Node)) setIsDragOver(false);
  }, []);

  const handleDrop = useCallback(async (e: React.DragEvent) => {
    e.preventDefault(); setIsDragOver(false);
    const dropped = Array.from(e.dataTransfer.files);
    if (!dropped.length) return;
    const entries = await Promise.all(dropped.map(async f => ({ filename: f.name, content: await f.text() })));
    try {
      await onUploadFiles(entries);
      toast.success(`${entries.length} file${entries.length > 1 ? "s" : ""} uploaded`);
    } catch (e) { toast.error(String(e)); }
  }, [onUploadFiles]);

  /* ── Context menu handlers ── */
  function handleContextMenu(e: React.MouseEvent, entry: TreeFile) {
    e.preventDefault();
    e.stopPropagation();
    setContextMenu({
      type: "file", x: e.clientX, y: e.clientY,
      filename: entry.filename,
      isMain: entry.is_main,
      isReq: entry.filename === "requirements.txt",
    });
  }

  function handleBlankContextMenu(e: React.MouseEvent) {
    e.preventDefault();
    setContextMenu({ type: "blank", x: e.clientX, y: e.clientY });
  }

  return (
    <div
      className={`relative flex flex-col h-full select-none border-r border-border transition-colors ${
        isDragOver ? "bg-primary/5 ring-2 ring-inset ring-primary/30" : "bg-[#1e1e1e]"
      }`}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      onContextMenu={handleBlankContextMenu}
    >
      {/* Toolbar */}
      <div className="flex items-center px-2 border-b border-border shrink-0 h-8">
        <span className="text-[10px] uppercase tracking-widest text-muted-foreground/60 font-semibold flex-1 pl-0.5">
          Explorer
        </span>
        <button onClick={startAddNew} title="New file"
          className="h-5 w-5 rounded flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-white/10 transition-colors">
          <Plus className="h-3.5 w-3.5" />
        </button>
        <button onClick={() => uploadRef.current?.click()} title="Upload files"
          className="h-5 w-5 rounded flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-white/10 transition-colors ml-0.5">
          <Upload className="h-3.5 w-3.5" />
        </button>
      </div>

      <input ref={uploadRef} type="file" multiple className="hidden" onChange={handleUploadInput} />

      {/* File list */}
      <ScrollArea className="flex-1">
        <div className="py-0.5">
          {allEntries.map(entry => {
            const { Icon, cls } = getFileIcon(entry.filename);
            const isActive = entry.filename === activeFile;
            const isRenaming = renamingFile === entry.filename;
            const isDeleting = pendingDelete === entry.filename;
            const canDelete = !entry.is_main && entry.filename !== "requirements.txt";
            const canRename = entry.filename !== "requirements.txt";
            const hasDir = entry.filename.includes("/");
            const dirPart = hasDir ? entry.filename.slice(0, entry.filename.lastIndexOf("/") + 1) : "";
            const basePart = hasDir ? entry.filename.slice(entry.filename.lastIndexOf("/") + 1) : entry.filename;

            if (isRenaming) {
              return (
                <div key={entry.filename} className="flex items-center gap-1.5 px-2 h-[22px] bg-[#2a2d2e]">
                  {dirPart && <span className="text-[10px] text-muted-foreground/50 font-mono shrink-0">{dirPart}</span>}
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
                <div key={entry.filename} className="flex items-center gap-1.5 px-2 h-[22px] bg-destructive/15">
                  <Icon className={`h-3.5 w-3.5 shrink-0 ${cls}`} />
                  <span className="flex-1 text-xs font-mono truncate min-w-0 text-muted-foreground">{basePart}</span>
                  <span className="text-[10px] text-muted-foreground mr-1 shrink-0">Delete?</span>
                  <button onClick={async () => {
                    try { await onDeleteFile(entry.filename); }
                    catch (e) { toast.error(String(e)); }
                    finally { setPendingDelete(null); }
                  }} className="h-4 w-4 rounded flex items-center justify-center text-destructive hover:bg-destructive/20 shrink-0" title="Confirm">
                    <Check className="h-3 w-3" />
                  </button>
                  <button onClick={() => setPendingDelete(null)}
                    className="h-4 w-4 rounded flex items-center justify-center text-muted-foreground hover:bg-white/10 shrink-0" title="Cancel">
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
                onContextMenu={e => handleContextMenu(e, entry)}
                title={entry.filename}
                className={`group flex items-center gap-1.5 px-2 h-[22px] cursor-pointer transition-colors ${
                  isActive ? "bg-[#37373d] text-white" : "text-[#bbb] hover:bg-[#2a2d2e] hover:text-white"
                }`}
              >
                {dirPart && <span className="text-[10px] text-muted-foreground/50 font-mono shrink-0">{dirPart}</span>}
                <Icon className={`h-3.5 w-3.5 shrink-0 ${cls}`} />
                <span className="flex-1 text-xs font-mono truncate min-w-0">{basePart}</span>

                {/* Badges — swap out on hover */}
                <div className="flex items-center gap-1 group-hover:hidden shrink-0">
                  {entry.isDirty && <span className="h-[7px] w-[7px] rounded-full bg-foreground/50 shrink-0" title="Unsaved" />}
                  {entry.is_main && <span className="text-[9px] px-1 rounded-sm border border-border/50 text-muted-foreground/60 font-mono leading-4 shrink-0">M</span>}
                </div>

                {/* Action buttons — show on hover */}
                <div className="hidden group-hover:flex items-center gap-0.5 shrink-0">
                  <button onClick={e => { e.stopPropagation(); onDownloadFile(entry.filename); }}
                    className="h-5 w-5 rounded flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-white/10 transition-colors" title="Download">
                    <Download className="h-3 w-3" />
                  </button>
                  {canDelete && (
                    <button onClick={e => { e.stopPropagation(); setPendingDelete(entry.filename); }}
                      className="h-5 w-5 rounded flex items-center justify-center text-muted-foreground hover:text-destructive hover:bg-white/10 transition-colors" title="Delete">
                      <Trash2 className="h-3 w-3" />
                    </button>
                  )}
                </div>
              </div>
            );
          })}

          {/* New file input */}
          {addingNew && (
            <div className="flex items-center gap-1.5 px-2 h-[22px] bg-[#2a2d2e]">
              <File className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
              <input
                ref={newFileInputRef}
                value={newFileName}
                onChange={e => setNewFileName(e.target.value)}
                onKeyDown={e => {
                  if (e.key === "Enter") { e.preventDefault(); commitNewFile(); }
                  if (e.key === "Escape") { setAddingNew(false); setNewFileName(""); }
                }}
                onBlur={() => { if (!newFileName.trim()) setAddingNew(false); else commitNewFile(); }}
                placeholder="filename.py"
                className="flex-1 min-w-0 bg-[#1a1a1a] border border-[#007acc] rounded-sm px-1.5 h-[18px] text-xs font-mono text-foreground placeholder:text-muted-foreground/40 focus:outline-none"
                spellCheck={false}
              />
            </div>
          )}
        </div>
      </ScrollArea>

      {/* Drop overlay */}
      {isDragOver && (
        <div className="absolute inset-0 flex items-end justify-center pb-4 pointer-events-none">
          <div className="text-xs text-primary font-medium bg-background/90 px-3 py-1.5 rounded-md border border-primary/40 shadow">
            Drop to upload
          </div>
        </div>
      )}

      {/* Right-click context menu */}
      {contextMenu?.type === "file" && (
        <ContextMenuPanel
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
      {contextMenu?.type === "blank" && (
        <BlankContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          onNewFile={() => { setContextMenu(null); startAddNew(); }}
          onUpload={() => { setContextMenu(null); uploadRef.current?.click(); }}
        />
      )}
    </div>
  );
}

/* ── Blank area context menu ────────────────────────────────────────────── */

function BlankContextMenu({ x, y, onNewFile, onUpload }: {
  x: number; y: number; onNewFile: () => void; onUpload: () => void;
}) {
  const menuW = 160, menuH = 68;
  const adjX = x + menuW > window.innerWidth ? x - menuW : x;
  const adjY = y + menuH > window.innerHeight ? y - menuH : y;
  return (
    <div
      className="fixed z-50 min-w-[160px] rounded-md border border-border bg-popover shadow-lg py-1 text-sm"
      style={{ left: adjX, top: adjY }}
      onClick={e => e.stopPropagation()}
      onContextMenu={e => e.preventDefault()}
    >
      <button onClick={onNewFile}
        className="w-full flex items-center gap-2 px-3 py-1.5 text-xs hover:bg-secondary transition-colors text-left">
        <Plus className="h-3 w-3 text-muted-foreground" />
        New file
      </button>
      <button onClick={onUpload}
        className="w-full flex items-center gap-2 px-3 py-1.5 text-xs hover:bg-secondary transition-colors text-left">
        <Upload className="h-3 w-3 text-muted-foreground" />
        Upload files
      </button>
    </div>
  );
}

/* ── Context menu panel ─────────────────────────────────────────────────── */

function ContextMenuPanel({
  x, y, filename, canRename, canDelete, onRename, onDownload, onDelete,
}: {
  x: number; y: number; filename: string;
  canRename: boolean; canDelete: boolean;
  onRename: () => void; onDownload: () => void; onDelete: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);

  // Adjust position so menu stays on screen
  const menuW = 180, menuH = canDelete ? 116 : 84;
  const adjX = x + menuW > window.innerWidth ? x - menuW : x;
  const adjY = y + menuH > window.innerHeight ? y - menuH : y;

  return (
    <div
      ref={ref}
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
          Rename
          <span className="ml-auto text-[10px] text-muted-foreground/60">F2</span>
        </button>
      )}
      <button onClick={onDownload}
        className="w-full flex items-center gap-2 px-3 py-1.5 text-xs hover:bg-secondary transition-colors text-left">
        <Download className="h-3 w-3 text-muted-foreground" />
        Download
      </button>

      {canDelete && (
        <>
          <div className="h-px bg-border/60 my-1" />
          <button onClick={onDelete}
            className="w-full flex items-center gap-2 px-3 py-1.5 text-xs hover:bg-destructive/10 text-destructive transition-colors text-left">
            <Trash2 className="h-3 w-3" />
            Delete
          </button>
        </>
      )}
    </div>
  );
}
