"use client";
import { Suspense, useEffect, useRef, useState, useCallback } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { useTranslation } from "react-i18next";
import {
  ArrowLeft, Play, Square, Save, Terminal, Settings2,
  Clock, ChevronRight, Loader2, CalendarClock, Workflow,
  History, CheckCircle2, XCircle, MinusCircle, Copy, Trash2, Check, Sparkles, Coins, FlaskConical, Flame,
  Search, X, PanelLeft, PanelRight, ChevronDown, ChevronUp,
} from "lucide-react";
import { toast } from "sonner";
import { scripts, executions, mcpServers, skills as skillsApi, revisions as revisionsApi, inputPresets } from "@/lib/api";
import type { Script, ScriptSummary, ScriptFile, ExecutionLog, WsEvent, MCPServerConfig, SkillSummary, ScriptRevisionDetail, TraceEvent, GraphTopology, ScriptInputPreset, ArtifactEvent } from "@/lib/types";
import ResourcePicker, { type ResourceItem, type ResourceSelection } from "@/components/ResourcePicker";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription,
} from "@/components/ui/dialog";
import ScriptEditor, { type LintIssue, type EditorSelection } from "@/components/ScriptEditor";
import LogPanel from "@/components/LogPanel";
import FlowPanel from "@/components/FlowPanel";
import DependencyManager from "@/components/DependencyManager";
import FileTree, { type TreeFile } from "@/components/FileTree";
import { useResizable } from "@/components/Splitter";
import RevisionPanel from "@/components/RevisionPanel";
import { useAssistantTarget, type ChangedFile } from "@/components/assistant/AssistantProvider";
import SchemaInput from "@/components/SchemaInput";
import FileUploadPanel from "@/components/FileUploadPanel";
import ArtifactsPanel from "@/components/ArtifactsPanel";
import EvalPanel from "@/components/EvalPanel";
import { summarizeError } from "@/lib/utils";

type RunStatus = "idle" | "queued" | "running" | "completed" | "failed" | "cancelled";

const STATUS_COLORS: Record<RunStatus, string> = {
  idle: "text-muted-foreground",
  queued: "text-yellow-400",
  running: "text-blue-400",
  completed: "text-emerald-400",
  failed: "text-destructive",
  cancelled: "text-amber-400",
};

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

export default function ScriptPageWrapper() {
  return (
    <Suspense fallback={<div className="min-h-screen flex items-center justify-center"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>}>
      <ScriptPage />
    </Suspense>
  );
}

function ScriptPage() {
  const { t } = useTranslation("script");
  const searchParams = useSearchParams();
  const id = searchParams.get("id") || "";
  const router = useRouter();

  useEffect(() => { if (!id) router.push("/"); }, [id, router]);

  const [script, setScript] = useState<Script | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  // Script metadata
  const [name, setName] = useState("");
  const [entryFn, setEntryFn] = useState("run");
  const [maxExec, setMaxExec] = useState(50);
  const [warm, setWarm] = useState(true);
  const [keepWarm, setKeepWarm] = useState(false);
  const [preheating, setPreheating] = useState(false);
  const [selectedMcpIds, setSelectedMcpIds] = useState<string[]>([]);
  const [availableMcpServers, setAvailableMcpServers] = useState<MCPServerConfig[]>([]);
  const [selectedSkillIds, setSelectedSkillIds] = useState<string[]>([]);
  const [availableSkills, setAvailableSkills] = useState<SkillSummary[]>([]);
  const [selectedModuleIds, setSelectedModuleIds] = useState<string[]>([]);
  const [availableModules, setAvailableModules] = useState<ScriptSummary[]>([]);
  const [inputJson, setInputJson] = useState("{}");
  const [inputError, setInputError] = useState("");
  const [activeTab, setActiveTab] = useState("logs");

  // Multi-file state
  const [scriptFiles, setScriptFiles] = useState<ScriptFile[]>([]);
  const [fileContents, setFileContents] = useState<Map<string, string>>(new Map());
  const [dirtyFiles, setDirtyFiles] = useState<Set<string>>(new Set());
  const [activeFile, setActiveFile] = useState("main.py");

  const dirty = dirtyFiles.size > 0;

  // Execution
  const [runStatus, setRunStatus] = useState<RunStatus>("idle");
  const [currentExecId, setCurrentExecId] = useState<string | null>(null);
  const [logs, setLogs] = useState<ExecutionLog[]>([]);
  const [output, setOutput] = useState<unknown>(null);
  const [trace, setTrace] = useState<TraceEvent[]>([]);
  const [topology, setTopology] = useState<GraphTopology | null>(null);
  const [artifacts, setArtifacts] = useState<ArtifactEvent[]>([]);
  const wsRef = useRef<WebSocket | null>(null);

  const [lintIssues, setLintIssues] = useState<LintIssue[]>([]);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);

  // Revision history
  const [revisionRefresh, setRevisionRefresh] = useState(0);
  const [loadedRevision, setLoadedRevision] = useState<{ number: number; label: string } | null>(null);
  const [rightTab, setRightTab] = useState<"config" | "history">("config");

  // Lint: debounce on active .py file content
  useEffect(() => {
    if (!id || !activeFile.endsWith(".py")) { setLintIssues([]); return; }
    const content = fileContents.get(activeFile) ?? "";
    if (!content) { setLintIssues([]); return; }
    const timer = setTimeout(() => {
      scripts.lint(id, content)
        .then(r => setLintIssues(r.issues))
        .catch(() => setLintIssues([]));
    }, 500);
    return () => clearTimeout(timer);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, activeFile, fileContents]);

  // Resizable panels
  const [treeWidth, treeHandle] = useResizable({
    direction: "vertical", initial: 210, min: 140, max: 380,
    storageKey: "ag.treeWidth", side: "start",
  });
  const [pkgHeight, pkgHandle] = useResizable({
    direction: "horizontal", initial: 180, min: 80, max: 360,
    storageKey: "ag.pkgHeight", side: "end",
  });
  // Cap the bottom panel so it can never swallow the whole editor: reserve
  // ~220px for the header + a minimum editor slice + the handle. Without this,
  // dragging the panel to the top collapsed the editor to 0 and pinned the 1px
  // handle under the header with no way to drag it back. A stale over-max value
  // saved from before this cap is re-clamped by useResizable on load.
  const bottomMax = typeof window !== "undefined" ? Math.max(240, window.innerHeight - 220) : 900;
  const [bottomHeight, bottomHandle] = useResizable({
    direction: "horizontal", initial: 200, min: 80, max: bottomMax,
    storageKey: "ag.bottomHeight", side: "end",
  });
  // The bottom panel can also be collapsed to just its tab strip — a guaranteed
  // one-click way to reclaim the editor, independent of the drag handle.
  const [bottomCollapsed, setBottomCollapsed] = useState<boolean>(
    () => typeof window !== "undefined" && localStorage.getItem("ag.bottomCollapsed") === "1",
  );
  useEffect(() => { localStorage.setItem("ag.bottomCollapsed", bottomCollapsed ? "1" : "0"); }, [bottomCollapsed]);
  const [rightWidth, rightHandle] = useResizable({
    direction: "vertical", initial: 360, min: 260, max: 720,
    storageKey: "ag.rightWidth", side: "end",
  });
  // Collapsible side panels (VS Code style). Collapsing a panel reclaims its
  // width for the editor — the escape hatch when a narrow viewport / zoom would
  // otherwise crush the center column. Persisted so it survives reloads.
  const [leftCollapsed, setLeftCollapsed] = useState<boolean>(
    () => typeof window !== "undefined" && localStorage.getItem("ag.leftCollapsed") === "1",
  );
  const [rightCollapsed, setRightCollapsed] = useState<boolean>(
    () => typeof window !== "undefined" && localStorage.getItem("ag.rightCollapsed") === "1",
  );
  useEffect(() => { localStorage.setItem("ag.leftCollapsed", leftCollapsed ? "1" : "0"); }, [leftCollapsed]);
  useEffect(() => { localStorage.setItem("ag.rightCollapsed", rightCollapsed ? "1" : "0"); }, [rightCollapsed]);

  // Pre-turn snapshot of the saved file contents, for the post-turn diff/undo.
  const assistantBaselineRef = useRef<Map<string, string>>(new Map());
  // Current editor selection, fed to the assistant for "edit this selection".
  const [selection, setSelection] = useState<EditorSelection | null>(null);

  // Bind the global floating AI assistant to THIS script while the page is open
  // (handler fns below are hoisted). Unbinds on unmount / while loading.
  useAssistantTarget(
    loading || !id ? null : {
      kind: "script", id, label: name,
      buildContext: buildAssistantContext,
      onBeforeTurn: handleAssistantBeforeTurn,
      onAfterTurn: handleAssistantAfterTurn,
      onRevert: handleAssistantRevert,
      onOpenFile: setActiveFile,
    },
  );

  // Load script
  useEffect(() => {
    Promise.all([scripts.get(id), mcpServers.list(), skillsApi.list(), scripts.list("module")])
      .then(([s, servers, skillList, moduleList]) => {
        setScript(s);
        setName(s.name);
        setEntryFn(s.entry_function);
        setMaxExec(s.max_executions ?? 50);
        setWarm(s.warm ?? true);
        setKeepWarm(s.keep_warm ?? false);
        setSelectedMcpIds(s.mcp_server_ids || []);
        setAvailableMcpServers(servers.filter(srv => srv.enabled));
        setSelectedSkillIds(s.skill_ids || []);
        setAvailableSkills(skillList.filter(sk => sk.enabled));
        setSelectedModuleIds(s.module_ids || []);
        setAvailableModules(moduleList);

        const contents = new Map<string, string>();
        for (const f of s.files) contents.set(f.filename, f.content);
        contents.set("requirements.txt", s.requirements || "");
        setFileContents(contents);
        setScriptFiles(s.files);

        const main = s.files.find(f => f.is_main) ?? s.files[0];
        setActiveFile(main?.filename ?? "main.py");
      })
      .catch(() => { toast.error(t("toast.scriptNotFound")); router.push("/"); })
      .finally(() => setLoading(false));
  }, [id, router, t]);

  // Ctrl+S save shortcut
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "s") {
        e.preventDefault();
        if (dirty && !saving) handleSave();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dirty, saving]);

  // WebSocket
  const connectWs = useCallback((execId: string) => {
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${window.location.host}/ws/executions/${execId}`);
    wsRef.current = ws;
    ws.onmessage = (e) => {
      const msg: WsEvent = JSON.parse(e.data);
      if (msg.type === "log") {
        setLogs(prev => [...prev, {
          id: `${Date.now()}-${Math.random()}`,
          timestamp: msg.timestamp,
          level: msg.level as ExecutionLog["level"],
          message: msg.message,
          data: msg.data,
          step: msg.step,
        }]);
      } else if (msg.type === "trace") {
        setTrace(prev => [...prev, msg]);
      } else if (msg.type === "graph") {
        setTopology(msg);
      } else if (msg.type === "artifact") {
        setArtifacts(prev => [...prev, msg]);
      } else if (msg.type === "status") {
        setRunStatus(msg.status as RunStatus);
        if (msg.output !== undefined) setOutput(msg.output);
        const terminal = ["completed", "failed", "cancelled"].includes(msg.status);
        if (terminal) {
          ws.close();
          if (msg.status === "failed" && msg.error) {
            toast.error(t("toast.executionFailed", { error: summarizeError(msg.error) }), {
              // Persist until the user acts on it — an 8s auto-dismiss meant
              // the "view logs" action could vanish before it was clicked,
              // leaving no way back to that failure's logs except digging
              // through run history manually.
              duration: 8000,
              action: { label: t("toast.viewLogs"), onClick: () => setActiveTab("logs") },
            });
          }
          if (msg.status === "completed") toast.success(t("toast.executionCompleted"));
        }
      }
    };
    ws.onerror = () => setRunStatus("failed");
  }, [t]);

  async function handleRun() {
    try {
      const parsed = JSON.parse(inputJson || "{}");
      setInputError("");
      if (dirty) await handleSave();
      setLogs([]);
      setOutput(null);
      setTrace([]);
      setTopology(null);
      setArtifacts([]);
      setRunStatus("running");
      setActiveTab("logs");
      const exec = await executions.create(id, parsed);
      setCurrentExecId(exec.id);
      connectWs(exec.id);
    } catch (e: unknown) {
      if (e instanceof SyntaxError) { setInputError(t("toast.invalidJson")); return; }
      toast.error(String(e));
      setRunStatus("failed");
    }
  }

  async function handleStop() {
    if (!currentExecId) return;
    try {
      const r = await executions.stop(currentExecId);
      setRunStatus((r as { status?: RunStatus }).status ?? "cancelled");
    } catch (e) {
      toast.error(t("toast.stopFailed", { error: e }));
      setRunStatus("cancelled");
    } finally { wsRef.current?.close(); }
  }

  async function handleSave() {
    if (!script) return;
    setSaving(true);
    try {
      const reqContent = fileContents.get("requirements.txt") ?? "";
      const ops: Promise<unknown>[] = [
        scripts.update(id, { name, entry_function: entryFn, requirements: reqContent, mcp_server_ids: selectedMcpIds, skill_ids: selectedSkillIds, module_ids: selectedModuleIds, max_executions: maxExec, warm, keep_warm: keepWarm }),
      ];
      for (const filename of dirtyFiles) {
        if (filename === "requirements.txt" || filename === "__meta__") continue;
        const content = fileContents.get(filename) ?? "";
        const file = scriptFiles.find(f => f.filename === filename);
        ops.push(scripts.upsertFile(id, { filename, content, is_main: file?.is_main ?? false }));
      }
      await Promise.all(ops);
      setDirtyFiles(new Set());
      setScript(prev => prev ? { ...prev, name, entry_function: entryFn, requirements: reqContent, mcp_server_ids: selectedMcpIds, skill_ids: selectedSkillIds, module_ids: selectedModuleIds, max_executions: maxExec, warm, keep_warm: keepWarm } : prev);
      setLoadedRevision(null);
      // Create revision snapshot after successful save
      revisionsApi.create(id).then(() => setRevisionRefresh(n => n + 1)).catch(() => null);
      toast.success(t("toast.saved"));
    } catch (e: unknown) {
      toast.error(String(e));
    } finally {
      setSaving(false);
    }
  }

  function handleRevisionLoad(rev: ScriptRevisionDetail) {
    const newContents = new Map(fileContents);
    const newDirty = new Set(dirtyFiles);

    for (const f of rev.files) {
      newContents.set(f.filename, f.content);
      newDirty.add(f.filename);
    }
    // Also restore metadata
    setName(rev.name);
    setEntryFn(rev.entry_function);
    newContents.set("requirements.txt", rev.requirements);
    newDirty.add("__meta__");
    newDirty.add("requirements.txt");

    setFileContents(newContents);
    setDirtyFiles(newDirty);
    setLoadedRevision({ number: rev.revision_number, label: rev.label });

    const mainFile = rev.files.find(f => f.is_main) ?? rev.files[0];
    if (mainFile) setActiveFile(mainFile.filename);
    setRightTab("config");
  }

  async function handleDelete() {
    setDeleting(true);
    try {
      await scripts.delete(id);
      toast.success(t("toast.deleted"));
      router.push("/");
    } catch (e: unknown) {
      toast.error(String(e));
      setDeleting(false);
      setDeleteOpen(false);
    }
  }

  // ── AI assistant turn lifecycle (diff-approval at end of turn) ───────────────
  // Reflect a freshly-fetched script into all editor state.
  function syncFromScript(s: Script) {
    const contents = new Map<string, string>();
    for (const f of s.files) contents.set(f.filename, f.content);
    contents.set("requirements.txt", s.requirements || "");
    setFileContents(contents);
    setScriptFiles(s.files);
    setDirtyFiles(new Set());
    setScript(s);
    setName(s.name);
    setEntryFn(s.entry_function);
    setMaxExec(s.max_executions ?? 50);
    setWarm(s.warm ?? true);
    setKeepWarm(s.keep_warm ?? false);
    setSelectedMcpIds(s.mcp_server_ids || []);
    setSelectedSkillIds(s.skill_ids || []);
  }

  function buildAssistantContext(): Record<string, unknown> {
    const ctx: Record<string, unknown> = {
      kind: "script",
      script_id: id,
      entry_function: entryFn,
      active_file: activeFile,
      active_content: fileContents.get(activeFile) ?? "",
    };
    if (selection?.text) ctx.selection = selection.text;
    return ctx;
  }

  // Before a turn: persist any unsaved edits (so the assistant sees them) and
  // snapshot the baseline (files + requirements) + a revision for one-click rollback.
  async function handleAssistantBeforeTurn() {
    if (dirty) await handleSave();
    const base = new Map<string, string>();
    for (const f of scriptFiles) base.set(f.filename, fileContents.get(f.filename) ?? f.content);
    base.set("requirements.txt", fileContents.get("requirements.txt") ?? script?.requirements ?? "");
    assistantBaselineRef.current = base;
    await revisionsApi.create(id, "AI 助手改动前").catch(() => null);
    setRevisionRefresh(n => n + 1);
  }

  // After a turn: refetch, reflect the assistant's changes, and diff vs baseline
  // (script files + requirements.txt, incl. adds/deletes).
  async function handleAssistantAfterTurn(): Promise<ChangedFile[]> {
    const s = await scripts.get(id);
    syncFromScript(s);
    const base = assistantBaselineRef.current;
    const changed: ChangedFile[] = [];
    const seen = new Set<string>();
    for (const f of s.files) {
      seen.add(f.filename);
      const before = base.get(f.filename) ?? "";
      if (before !== f.content) changed.push({ filename: f.filename, before, after: f.content });
    }
    for (const [fn, before] of base) {
      if (fn === "requirements.txt") continue;
      if (!seen.has(fn) && before) changed.push({ filename: fn, before, after: "" });
    }
    const reqBefore = base.get("requirements.txt") ?? "";
    const reqAfter = s.requirements ?? "";
    if (reqBefore !== reqAfter) changed.push({ filename: "requirements.txt", before: reqBefore, after: reqAfter });
    setRevisionRefresh(n => n + 1);
    return changed;
  }

  // Undo specific files to the pre-turn baseline (per-file or the whole turn).
  async function handleAssistantRevert(filenames: string[]) {
    const base = assistantBaselineRef.current;
    const s = await scripts.get(id);
    const want = new Set(filenames);
    const baseNames = new Set(Array.from(base.keys()).filter(k => k !== "requirements.txt"));
    const curNames = new Set(s.files.map(f => f.filename));
    const ops: Promise<unknown>[] = [];
    if (want.has("requirements.txt")) {
      ops.push(scripts.update(id, { requirements: base.get("requirements.txt") ?? "" }));
    }
    for (const f of s.files) {
      if (!want.has(f.filename)) continue;
      if (!baseNames.has(f.filename)) {
        if (!f.is_main) ops.push(scripts.deleteFile(id, f.filename).catch(() => null));  // assistant-created → remove
      } else if ((base.get(f.filename) ?? "") !== f.content) {
        ops.push(scripts.upsertFile(id, { filename: f.filename, content: base.get(f.filename) ?? "", is_main: f.is_main }));
      }
    }
    for (const [fn, content] of base) {  // assistant-deleted → recreate
      if (fn === "requirements.txt") continue;
      if (want.has(fn) && !curNames.has(fn)) ops.push(scripts.upsertFile(id, { filename: fn, content, is_main: fn === "main.py" }));
    }
    await Promise.all(ops);
    syncFromScript(await scripts.get(id));
    setRevisionRefresh(n => n + 1);
  }

  // ── File tree operations ──────────────────────────────────────────────────

  function markDirty(filename: string) {
    setDirtyFiles(prev => new Set(prev).add(filename));
  }

  // ── Resources (MCP + skills + modules) for the unified picker ──────────────
  const resourceItems: ResourceItem[] = [
    ...availableMcpServers.map(s => ({ type: "mcp" as const, id: s.id, name: s.name, description: s.transport })),
    ...availableSkills.map(s => ({ type: "skill" as const, id: s.id, name: s.name, description: s.description })),
    ...availableModules.map(m => ({ type: "module" as const, id: m.id, name: m.name, description: m.module_package ? `${m.module_package} — ${m.description}` : m.description })),
  ];
  const resourceSelection: ResourceSelection = {
    mcp: selectedMcpIds, skill: selectedSkillIds, module: selectedModuleIds,
  };
  function handleResourceChange(next: ResourceSelection) {
    setSelectedMcpIds(next.mcp);
    setSelectedSkillIds(next.skill);
    setSelectedModuleIds(next.module);
    markDirty("__meta__");
  }

  async function handleNewFile(filename: string) {
    const content = filename.endsWith(".py") ? "# " + filename + "\n" : "";
    await scripts.upsertFile(id, { filename, content, is_main: false });
    const newFile: ScriptFile = {
      id: `local-${Date.now()}`, script_id: id,
      filename, content, is_main: false,
      updated_at: new Date().toISOString(),
    };
    setScriptFiles(prev => [...prev, newFile]);
    setFileContents(prev => new Map(prev).set(filename, content));
    setActiveFile(filename);
  }

  async function handleDeleteFile(filename: string) {
    await scripts.deleteFile(id, filename);
    setScriptFiles(prev => prev.filter(f => f.filename !== filename));
    setFileContents(prev => { const m = new Map(prev); m.delete(filename); return m; });
    setDirtyFiles(prev => { const s = new Set(prev); s.delete(filename); return s; });
    if (activeFile === filename) {
      const remaining = scriptFiles.filter(f => f.filename !== filename);
      setActiveFile(remaining[0]?.filename ?? "main.py");
    }
  }

  // Scripts have no on-disk folders — a folder is virtual, derived from file
  // paths. Deleting one deletes every (non-main) file under its prefix; the
  // folder then vanishes from the tree because nothing references it anymore.
  async function handleDeleteDir(path: string) {
    const prefix = path + "/";
    const victims = scriptFiles.filter(f => f.filename.startsWith(prefix) && !f.is_main);
    for (const f of victims) await scripts.deleteFile(id, f.filename);
    const names = new Set(victims.map(f => f.filename));
    setScriptFiles(prev => prev.filter(f => !names.has(f.filename)));
    setFileContents(prev => { const m = new Map(prev); for (const n of names) m.delete(n); return m; });
    setDirtyFiles(prev => { const s = new Set(prev); for (const n of names) s.delete(n); return s; });
    if (names.has(activeFile)) {
      const remaining = scriptFiles.filter(f => !names.has(f.filename));
      setActiveFile(remaining[0]?.filename ?? "main.py");
    }
  }

  async function handleRenameFile(oldName: string, newName: string) {
    const content = fileContents.get(oldName) ?? "";
    const oldFile = scriptFiles.find(f => f.filename === oldName);
    await scripts.upsertFile(id, { filename: newName, content, is_main: false });
    if (oldFile && !oldFile.is_main) await scripts.deleteFile(id, oldName);

    setScriptFiles(prev => prev.map(f => f.filename === oldName ? { ...f, filename: newName } : f));
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
    await Promise.all(entries.map(e => scripts.upsertFile(id, { ...e, is_main: false })));
    setScriptFiles(prev => {
      const existing = new Map(prev.map(f => [f.filename, f]));
      for (const e of entries) {
        existing.set(e.filename, {
          id: existing.get(e.filename)?.id ?? `local-${e.filename}`,
          script_id: id, filename: e.filename, content: e.content,
          is_main: false, updated_at: new Date().toISOString(),
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

  // ── Build tree file list ──────────────────────────────────────────────────

  const treeFiles: TreeFile[] = [
    ...scriptFiles.map(f => ({
      filename: f.filename,
      is_main: f.is_main,
      isDirty: dirtyFiles.has(f.filename),
    })),
    {
      filename: "requirements.txt",
      is_main: false,
      isDirty: dirtyFiles.has("requirements.txt"),
    },
  ];

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const activeContent = fileContents.get(activeFile) ?? "";
  const activeLang = getLanguage(activeFile);
  const lintForActive = activeFile.endsWith(".py") ? lintIssues : [];

  return (
    <div className="h-screen flex flex-col overflow-hidden">
      {/* Header */}
      <header className="border-b border-border px-4 py-2 flex items-center gap-3 shrink-0">
        <Link href="/">
          <Button variant="ghost" size="icon" className="h-8 w-8">
            <ArrowLeft className="h-4 w-4" />
          </Button>
        </Link>
        <input
          value={name}
          onChange={e => { setName(e.target.value); markDirty("__meta__"); }}
          className="bg-transparent text-sm font-medium focus:outline-none border-b border-transparent focus:border-border w-48"
        />
        <Button variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground hover:text-foreground"
          title={t("header.copyIdTitle")} onClick={() => { navigator.clipboard.writeText(id); toast.success(t("toast.idCopied")); }}>
          <Copy className="h-3 w-3" />
        </Button>
        <Button variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground hover:text-destructive"
          title={t("header.deleteTitle")} onClick={() => setDeleteOpen(true)}>
          <Trash2 className="h-3 w-3" />
        </Button>

        {loadedRevision && (
          <span className="text-xs text-amber-400 flex items-center gap-1">
            <History className="h-3 w-3" />
            {t("header.revisionLoaded", {
              number: loadedRevision.number,
              label: loadedRevision.label ? ` "${loadedRevision.label}"` : "",
            })}
          </span>
        )}
        {!loadedRevision && dirty && <span className="text-xs text-muted-foreground">{t("header.unsaved")}</span>}
        {lintForActive.length > 0 && (
          <span className={`text-xs flex items-center gap-1 ${
            lintForActive.some(i => i.severity === "error") ? "text-destructive" : "text-amber-400"
          }`}>
            ● {t("header.issueCount", { count: lintForActive.length })}
          </span>
        )}

        <div className="ml-auto flex items-center gap-2">
          {/* Layout: collapse/expand the side panels (VS Code-style view controls) */}
          <div className="flex items-center gap-0.5">
            <Button variant="ghost" size="icon" className="h-7 w-7"
              title={t("header.toggleFiles")} aria-pressed={!leftCollapsed}
              onClick={() => setLeftCollapsed(c => !c)}>
              <PanelLeft className={`h-3.5 w-3.5 ${leftCollapsed ? "text-muted-foreground/50" : "text-foreground"}`} />
            </Button>
            <Button variant="ghost" size="icon" className="h-7 w-7"
              title={t("header.toggleConfig")} aria-pressed={!rightCollapsed}
              onClick={() => setRightCollapsed(c => !c)}>
              <PanelRight className={`h-3.5 w-3.5 ${rightCollapsed ? "text-muted-foreground/50" : "text-foreground"}`} />
            </Button>
          </div>
          <div className="h-4 w-px bg-border" />
          {runStatus !== "idle" && (
            <span className={`text-xs font-medium flex items-center gap-1.5 ${STATUS_COLORS[runStatus]}`}>
              {(runStatus === "queued" || runStatus === "running") && <Loader2 className="h-3 w-3 animate-spin" />}
              {t(`status.${runStatus}`, { defaultValue: runStatus })}
            </span>
          )}
          <Button variant="outline" size="sm" onClick={handleSave} disabled={saving || !dirty}>
            {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />}
            {t("header.save")}
          </Button>
          {(runStatus === "queued" || runStatus === "running") ? (
            <Button variant="destructive" size="sm" onClick={handleStop}>
              <Square className="h-3 w-3" />{t("header.stop")}
            </Button>
          ) : (
            <Button size="sm" onClick={handleRun}>
              <Play className="h-3 w-3" />{t("header.run")}
            </Button>
          )}
        </div>
      </header>

      {/* Body */}
      <div className="flex flex-1 overflow-hidden">

        {/* Left panel: File tree (top) + Packages (bottom) — collapsible */}
        {!leftCollapsed && (
          <>
            <div className="shrink-0 flex flex-col overflow-hidden" style={{ width: `${treeWidth}px` }}>
              <div className="flex-1 min-h-0">
                <FileTree
                  files={treeFiles}
                  activeFile={activeFile}
                  onSelect={setActiveFile}
                  onNewFile={handleNewFile}
                  onDeleteFile={handleDeleteFile}
                  onDeleteDir={handleDeleteDir}
                  onRenameFile={handleRenameFile}
                  onUploadFiles={handleUploadFiles}
                  onDownloadFile={handleDownloadFile}
                />
              </div>
              {pkgHandle}
              <div className="shrink-0 border-t border-border overflow-hidden" style={{ height: `${pkgHeight}px` }}>
                <DependencyManager
                  scriptId={id}
                  requirements={fileContents.get("requirements.txt") ?? ""}
                  onRequirementsSaved={() => {
                    setDirtyFiles(prev => { const s = new Set(prev); s.delete("requirements.txt"); return s; });
                  }}
                />
              </div>
            </div>
            {treeHandle}
          </>
        )}

        {/* Center: Editor + bottom tabs. overflow-hidden so that when a narrow
            viewport / zoom shrinks this min-w-0 column toward zero, the editor
            and bottom-tab content are CLIPPED instead of bleeding rightward over
            the config panel. */}
        <div className="flex flex-col flex-1 min-w-0 border-r border-border overflow-hidden">
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
              issues={lintForActive}
            />
          </div>

          {!bottomCollapsed && bottomHandle}
          {/* Bottom tabs: Logs, Output, Schedule, Runs — collapsible to its tab strip */}
          <div className="shrink-0 border-t border-border overflow-hidden" style={bottomCollapsed ? undefined : { height: `${bottomHeight}px` }}>
            {/*
              activationMode="manual": with the default "automatic" mode, Radix's
              roving-focus-group reclaims focus onto whichever trigger last had
              real DOM focus whenever focus is lost elsewhere on the page (e.g.
              a focused toast action button being removed on click) — and under
              automatic activation, refocusing a trigger re-selects it, silently
              reverting a just-applied setActiveTab() call. Manual activation
              decouples keyboard focus from tab selection so that reclaim can't
              undo a programmatic tab switch.
            */}
            <Tabs value={activeTab} onValueChange={v => { setActiveTab(v); if (bottomCollapsed) setBottomCollapsed(false); }} activationMode="manual" className="h-full flex flex-col">
              <TabsList className="rounded-none border-b border-border bg-transparent px-4 h-9 justify-start gap-1 shrink-0">
                <TabsTrigger value="logs" className="text-xs gap-1.5">
                  <Terminal className="h-3 w-3" />{t("tabs.logs")}
                </TabsTrigger>
                <TabsTrigger value="flow" className="text-xs gap-1.5">
                  <Workflow className="h-3 w-3" />{t("tabs.flow")}
                  {trace.length > 0 && (
                    <span className="text-[10px] text-muted-foreground tabular-nums">{trace.filter(ev => ev.phase === "start" || ev.phase === "event").length}</span>
                  )}
                </TabsTrigger>
                <TabsTrigger value="output" className="text-xs gap-1.5">
                  <ChevronRight className="h-3 w-3" />{t("tabs.output")}
                </TabsTrigger>
                <TabsTrigger value="artifacts" className="text-xs gap-1.5">
                  <Sparkles className="h-3 w-3" />{t("tabs.artifacts")}
                  {artifacts.length > 0 && (
                    <span className="text-[10px] text-muted-foreground tabular-nums">{artifacts.length}</span>
                  )}
                </TabsTrigger>
                <TabsTrigger value="schedule" className="text-xs gap-1.5">
                  <CalendarClock className="h-3 w-3" />{t("tabs.schedule")}
                </TabsTrigger>
                <TabsTrigger value="runs" className="text-xs gap-1.5">
                  <History className="h-3 w-3" />{t("tabs.runs")}
                </TabsTrigger>
                <TabsTrigger value="eval" className="text-xs gap-1.5">
                  <FlaskConical className="h-3 w-3" />{t("tabs.eval")}
                </TabsTrigger>
                <button
                  onClick={() => setBottomCollapsed(c => !c)}
                  title={bottomCollapsed ? t("tabs.expandPanel") : t("tabs.collapsePanel")}
                  className="ml-auto self-center flex items-center justify-center h-6 w-6 rounded text-muted-foreground hover:text-foreground hover:bg-accent/40 transition-colors"
                >
                  {bottomCollapsed ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                </button>
              </TabsList>
              {!bottomCollapsed && (
              <div className="flex-1 overflow-hidden">
                <TabsContent value="logs" className="h-full m-0">
                  <LogPanel logs={logs} />
                </TabsContent>
                <TabsContent value="flow" className="h-full m-0">
                  <FlowPanel trace={trace} topology={topology} runEnded={["completed", "failed", "cancelled"].includes(runStatus)} />
                </TabsContent>
                <TabsContent value="output" className="h-full m-0 p-3">
                  <ScrollArea className="h-full">
                    {output !== null
                      ? <pre className="text-xs font-mono text-muted-foreground whitespace-pre-wrap">{JSON.stringify(output, null, 2)}</pre>
                      : <p className="text-xs text-muted-foreground">{t("run.noOutput")}</p>}
                  </ScrollArea>
                </TabsContent>
                <TabsContent value="artifacts" className="h-full m-0">
                  <ArtifactsPanel items={artifacts} />
                </TabsContent>
                <TabsContent value="schedule" className="h-full m-0">
                  <ScheduleTab scriptId={id} />
                </TabsContent>
                <TabsContent value="runs" className="h-full m-0">
                  <RunsTab
                    scriptId={id}
                    currentExecId={currentExecId}
                    runStatus={runStatus}
                    onSelect={exec => {
                      setCurrentExecId(exec.id);
                      setLogs(exec.logs.map(l => ({ ...l })));
                      setOutput(exec.output_data ?? null);
                      setTrace(exec.trace);
                      setTopology(exec.topology);
                      setArtifacts(exec.artifacts);
                      setRunStatus(exec.status as RunStatus);
                      setActiveTab("logs");
                    }}
                  />
                </TabsContent>
                <TabsContent value="eval" className="h-full m-0">
                  <EvalPanel scriptId={id} />
                </TabsContent>
              </div>
              )}
            </Tabs>
          </div>
        </div>

        {!rightCollapsed && (<>
        {rightHandle}

        {/* Right: Config + History panel — collapsible */}
        <div className="shrink-0 flex flex-col overflow-hidden border-l border-border" style={{ width: `${rightWidth}px` }}>
          {/* Tab bar */}
          <div className="flex border-b border-border shrink-0">
            <button
              onClick={() => setRightTab("config")}
              className={`flex-1 py-2 text-[11px] font-medium transition-colors ${
                rightTab === "config"
                  ? "border-b-2 border-primary text-foreground"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {t("rightPanel.config")}
            </button>
            <button
              onClick={() => setRightTab("history")}
              className={`flex-1 py-2 text-[11px] font-medium transition-colors flex items-center justify-center gap-1 ${
                rightTab === "history"
                  ? "border-b-2 border-primary text-foreground"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              <History className="h-3 w-3" />{t("rightPanel.history")}
            </button>
          </div>

          {rightTab === "config" ? (
            <div className="flex-1 overflow-y-auto">
              <div className="p-4 space-y-5">

                {/* Entry function */}
                <div className="space-y-1.5">
                  <p className="text-[10px] uppercase tracking-wider font-semibold text-muted-foreground/70">{t("config.entryFunction.label")}</p>
                  <div className="relative">
                    <Settings2 className="absolute left-2.5 top-[9px] h-3.5 w-3.5 text-muted-foreground pointer-events-none" />
                    <Input
                      value={entryFn}
                      onChange={e => { setEntryFn(e.target.value); markDirty("__meta__"); }}
                      className="pl-8 h-8 text-xs font-mono"
                      placeholder={t("config.entryFunction.placeholder")}
                    />
                  </div>
                </div>

                {/* Execution retention */}
                <div className="space-y-1.5">
                  <p className="text-[10px] uppercase tracking-wider font-semibold text-muted-foreground/70 flex items-center gap-1.5">
                    <History className="h-3 w-3" />{t("config.maxExec.label")}
                  </p>
                  <div className="relative">
                    <Input
                      type="number"
                      min={0}
                      max={10000}
                      value={maxExec}
                      onChange={e => {
                        const n = Math.max(0, Math.min(10000, Math.floor(Number(e.target.value) || 0)));
                        setMaxExec(n);
                        markDirty("__meta__");
                      }}
                      className="h-8 text-xs font-mono"
                      placeholder={t("config.maxExec.placeholder")}
                    />
                  </div>
                  <p className="text-[10px] text-muted-foreground/70 leading-snug">
                    {t("config.maxExec.hint")}
                  </p>
                </div>

                {/* Warm worker (serverless-style reuse) */}
                <div className="space-y-2">
                  <p className="text-[10px] uppercase tracking-wider font-semibold text-muted-foreground/70 flex items-center gap-1.5">
                    <Flame className="h-3 w-3" />{t("config.warm.label")}
                  </p>
                  <label className="flex items-start gap-2 cursor-pointer select-none">
                    <input type="checkbox" checked={warm}
                      onChange={e => { setWarm(e.target.checked); if (!e.target.checked) setKeepWarm(false); markDirty("__meta__"); }}
                      className="h-3.5 w-3.5 mt-0.5 rounded border-border accent-primary" />
                    <span className="text-xs">
                      {t("config.warm.reuse")}
                      <span className="block text-[10px] text-muted-foreground/70 leading-snug">{t("config.warm.reuseHint")}</span>
                    </span>
                  </label>
                  <label className={`flex items-start gap-2 select-none ${warm ? "cursor-pointer" : "opacity-40 cursor-not-allowed"}`}>
                    <input type="checkbox" checked={keepWarm} disabled={!warm}
                      onChange={e => { setKeepWarm(e.target.checked); markDirty("__meta__"); }}
                      className="h-3.5 w-3.5 mt-0.5 rounded border-border accent-primary" />
                    <span className="text-xs">
                      {t("config.warm.keepWarm")}
                      <span className="block text-[10px] text-muted-foreground/70 leading-snug">{t("config.warm.keepWarmHint")}</span>
                    </span>
                  </label>
                  {warm && (
                    <Button variant="outline" size="sm" className="h-7 text-xs w-full" disabled={preheating}
                      onClick={async () => {
                        setPreheating(true);
                        try {
                          const r = await scripts.preheat(id);
                          if (!r.enabled) toast.info(t("config.warm.disabled"));
                          else toast.success(t("config.warm.preheated"));
                        } catch (e: unknown) { toast.error(String(e)); }
                        finally { setPreheating(false); }
                      }}>
                      {preheating ? <Loader2 className="h-3 w-3 animate-spin" /> : <Flame className="h-3 w-3" />}
                      {preheating ? t("config.warm.preheating") : t("config.warm.preheat")}
                    </Button>
                  )}
                </div>

                {/* Resources: MCP servers + skills + code modules, one searchable picker */}
                <ResourcePicker
                  items={resourceItems}
                  selected={resourceSelection}
                  onChange={handleResourceChange}
                />

                {/* Input — typed form when the script declares INPUT_SCHEMA,
                    else the classic JSON preset editor */}
                <SchemaInput
                  scriptId={id}
                  schema={script?.input_schema}
                  value={inputJson}
                  onChange={setInputJson}
                  error={inputError}
                  onError={setInputError}
                />

                {/* Uploaded files */}
                <FileUploadPanel
                  scriptId={id}
                  onInsertRef={snippet => {
                    setInputJson(prev => {
                      const trimmed = (prev ?? "").trim();
                      // empty / placeholder → start a fresh object with key "file"
                      if (!trimmed || trimmed === "{}") {
                        return `{\n  "file": ${snippet}\n}`;
                      }
                      // valid JSON object → add/replace top-level "file" key
                      try {
                        const obj = JSON.parse(trimmed);
                        if (obj && typeof obj === "object" && !Array.isArray(obj)) {
                          let key = "file";
                          let i = 2;
                          while (key in obj) key = `file${i++}`;
                          obj[key] = JSON.parse(snippet);
                          return JSON.stringify(obj, null, 2);
                        }
                      } catch { /* fallthrough to append */ }
                      // otherwise just append on a new line
                      return `${prev}\n${snippet}`;
                    });
                    setInputError("");
                  }}
                />

              </div>
            </div>
          ) : (
            <div className="flex-1 min-h-0">
              <RevisionPanel
                scriptId={id}
                currentFileContents={fileContents}
                onLoad={handleRevisionLoad}
                refreshTrigger={revisionRefresh}
              />
            </div>
          )}
        </div>
        </>)}

      </div>

      {/* Delete dialog */}
      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>{t("dialog.delete.title")}</DialogTitle>
            <DialogDescription>
              <span className="font-medium text-foreground">{name}</span> {t("dialog.delete.description")}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteOpen(false)} disabled={deleting}>{t("dialog.delete.cancel")}</Button>
            <Button variant="destructive" onClick={handleDelete} disabled={deleting}>
              {deleting ? <Loader2 className="h-3 w-3 animate-spin" /> : <Trash2 className="h-3 w-3" />}
              {t("dialog.delete.confirm")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

// ── Schedule Tab ────────────────────────────────────────────────────────────

import { cronJobs } from "@/lib/api";
import type { CronJob, ExecutionSummary } from "@/lib/types";
import { formatDate, compactNumber } from "@/lib/utils";
import { Plus } from "lucide-react";

const CRON_PRESETS = [
  { key: "every5m", value: "*/5 * * * *" },
  { key: "hourly", value: "0 * * * *" },
  { key: "daily", value: "0 0 * * *" },
  { key: "weekly", value: "0 0 * * 0" },
  { key: "monthly", value: "0 0 1 * *" },
] as const;

function ScheduleTab({ scriptId }: { scriptId: string }) {
  const { t } = useTranslation("script");
  const [jobs, setJobs] = useState<CronJob[]>([]);
  const [expr, setExpr] = useState("0 * * * *");
  const [label, setLabel] = useState("");
  const [adding, setAdding] = useState(false);
  const [presets, setPresets] = useState<ScriptInputPreset[]>([]);
  const [newInput, setNewInput] = useState("{}");
  const [newInputError, setNewInputError] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editJson, setEditJson] = useState("");
  const [editError, setEditError] = useState("");
  const [savingEdit, setSavingEdit] = useState(false);
  const [tz, setTz] = useState<{ timezone: string; utc_offset: string | null } | null>(null);

  useEffect(() => {
    cronJobs.list(scriptId).then(setJobs).catch(() => null);
    inputPresets.list(scriptId).then(setPresets).catch(() => null);
    cronJobs.timezone().then(setTz).catch(() => null);
  }, [scriptId]);

  async function add() {
    if (!expr) return;
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(newInput || "{}");
    } catch {
      setNewInputError(t("schedule.invalidJson"));
      return;
    }
    setNewInputError("");
    setAdding(true);
    try {
      const j = await cronJobs.create({ script_id: scriptId, label, cron_expression: expr, input_data: parsed, enabled: true });
      setJobs(p => [...p, j]);
      setLabel("");
      setNewInput("{}");
    } catch (e: unknown) {
      toast.error(String(e));
    } finally { setAdding(false); }
  }

  async function remove(jobId: string) {
    await cronJobs.delete(jobId);
    setJobs(p => p.filter(j => j.id !== jobId));
    if (editingId === jobId) setEditingId(null);
  }

  async function toggle(job: CronJob) {
    const updated = await cronJobs.update(job.id, { enabled: !job.enabled });
    setJobs(p => p.map(j => j.id === updated.id ? updated : j));
  }

  function startEdit(job: CronJob) {
    setEditingId(job.id);
    setEditJson(JSON.stringify(job.input_data ?? {}, null, 2));
    setEditError("");
  }

  async function saveEdit() {
    if (!editingId) return;
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(editJson || "{}");
    } catch {
      setEditError(t("schedule.invalidJson"));
      return;
    }
    setSavingEdit(true);
    try {
      const updated = await cronJobs.update(editingId, { input_data: parsed });
      setJobs(p => p.map(j => j.id === updated.id ? updated : j));
      setEditingId(null);
    } catch (e: unknown) {
      toast.error(String(e));
    } finally { setSavingEdit(false); }
  }

  function applyPreset(setter: (v: string) => void, errSetter: (e: string) => void, presetId: string) {
    if (!presetId) return;
    const p = presets.find(x => x.id === presetId);
    if (!p) return;
    setter(p.input_json);
    errSetter("");
  }

  const hasInput = (d: Record<string, unknown> | undefined | null) =>
    d && Object.keys(d).length > 0;

  return (
    <ScrollArea className="h-full">
      <div className="p-3 space-y-4">

        {/* Add form */}
        <div className="space-y-2">
          <p className="text-[10px] uppercase tracking-wider font-semibold text-muted-foreground/70">{t("schedule.newSchedule")}</p>
          <div className="flex flex-wrap gap-1">
            {CRON_PRESETS.map(p => (
              <button key={p.value} onClick={() => setExpr(p.value)}
                className={`text-[10px] px-2.5 py-1 rounded-full border transition-colors ${
                  expr === p.value
                    ? "bg-primary/10 border-primary/40 text-primary"
                    : "border-border/60 text-muted-foreground hover:border-border hover:text-foreground"
                }`}>
                {t(`schedule.presets.${p.key}`)}
              </button>
            ))}
          </div>
          <div className="flex gap-1.5">
            <Input value={expr} onChange={e => setExpr(e.target.value)} placeholder={t("schedule.cronPlaceholder")}
              className="h-7 text-xs font-mono flex-1 min-w-0" />
            <Input value={label} onChange={e => setLabel(e.target.value)} placeholder={t("schedule.labelPlaceholder")}
              className="h-7 text-xs w-20 shrink-0" />
            <Button size="sm" className="h-7 px-2 shrink-0" onClick={add} disabled={adding || !expr}>
              {adding ? <Loader2 className="h-3 w-3 animate-spin" /> : <Plus className="h-3 w-3" />}
            </Button>
          </div>
          {tz && (
            <p className="text-[10px] text-muted-foreground/70">
              {t("schedule.timezoneHint", {
                tz: tz.timezone + (tz.utc_offset ? ` (UTC${tz.utc_offset})` : ""),
              })}
            </p>
          )}
          <div className="space-y-1">
            <div className="flex items-center justify-between">
              <span className="text-[10px] uppercase tracking-wider font-semibold text-muted-foreground/70">
                {t("schedule.inputJsonLabel")} {newInputError && <span className="text-destructive normal-case font-normal ml-1">{newInputError}</span>}
              </span>
              {presets.length > 0 && (
                <select
                  value=""
                  onChange={e => { applyPreset(setNewInput, setNewInputError, e.target.value); e.target.value = ""; }}
                  className="h-6 text-[10px] bg-secondary/30 border border-border rounded px-1.5 text-muted-foreground hover:text-foreground"
                  title={t("schedule.presetTitle")}>
                  <option value="">{t("schedule.fromPreset")}</option>
                  {presets.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                </select>
              )}
            </div>
            <textarea
              value={newInput}
              onChange={e => { setNewInput(e.target.value); setNewInputError(""); }}
              className="w-full text-xs font-mono px-2 py-1.5 rounded-md border border-border bg-input min-h-[60px] resize-y focus:outline-none focus:ring-1 focus:ring-ring"
              placeholder="{}"
              spellCheck={false}
            />
          </div>
        </div>

        {/* Job list */}
        {jobs.length > 0 && (
          <div className="space-y-1.5">
            <p className="text-[10px] uppercase tracking-wider font-semibold text-muted-foreground/70">{t("schedule.schedulesLabel")}</p>
            {jobs.map(j => (
              <div key={j.id} className="rounded-lg border border-border bg-secondary/10 hover:bg-secondary/20 transition-colors group">
                <div className="flex items-center gap-2.5 px-2.5 py-2">
                  <button onClick={() => toggle(j)} title={j.enabled ? t("schedule.disable") : t("schedule.enable")} className="shrink-0">
                    <div className={`h-2 w-2 rounded-full transition-colors ${j.enabled ? "bg-emerald-400" : "bg-muted-foreground/30"}`} />
                  </button>
                  <div className="flex-1 min-w-0">
                    <div className="font-mono text-xs text-foreground flex items-center gap-1.5">
                      {j.cron_expression}
                      {hasInput(j.input_data) && (
                        <span className="text-[9px] px-1 py-0.5 rounded bg-secondary/60 text-muted-foreground font-sans" title={JSON.stringify(j.input_data)}>
                          {t("schedule.inputBadge")}
                        </span>
                      )}
                    </div>
                    {j.label && <div className="text-[10px] text-muted-foreground truncate mt-0.5">{j.label}</div>}
                  </div>
                  <button onClick={() => editingId === j.id ? setEditingId(null) : startEdit(j)}
                    className="text-muted-foreground hover:text-foreground transition-colors shrink-0 text-[10px]"
                    title={t("schedule.editInputTitle")}>
                    {editingId === j.id ? t("schedule.inputToggleClose") : t("schedule.inputToggleOpen")}
                  </button>
                  <button onClick={() => remove(j.id)}
                    className="opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive transition-all shrink-0">
                    <Trash2 className="h-3 w-3" />
                  </button>
                </div>
                {editingId === j.id && (
                  <div className="px-2.5 pb-2.5 space-y-1.5 border-t border-border/60 pt-2">
                    <div className="flex items-center justify-between">
                      <span className="text-[10px] uppercase tracking-wider font-semibold text-muted-foreground/70">
                        {t("schedule.inputJsonLabel")} {editError && <span className="text-destructive normal-case font-normal ml-1">{editError}</span>}
                      </span>
                      {presets.length > 0 && (
                        <select
                          value=""
                          onChange={e => { applyPreset(setEditJson, setEditError, e.target.value); e.target.value = ""; }}
                          className="h-6 text-[10px] bg-secondary/30 border border-border rounded px-1.5 text-muted-foreground hover:text-foreground">
                          <option value="">{t("schedule.fromPreset")}</option>
                          {presets.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                        </select>
                      )}
                    </div>
                    <textarea
                      value={editJson}
                      onChange={e => { setEditJson(e.target.value); setEditError(""); }}
                      className="w-full text-xs font-mono px-2 py-1.5 rounded-md border border-border bg-input min-h-[80px] resize-y focus:outline-none focus:ring-1 focus:ring-ring"
                      spellCheck={false}
                    />
                    <div className="flex justify-end gap-1.5">
                      <Button variant="outline" size="sm" className="h-6 px-2 text-xs" onClick={() => setEditingId(null)}>
                        {t("schedule.cancel")}
                      </Button>
                      <Button size="sm" className="h-6 px-2 text-xs" onClick={saveEdit} disabled={savingEdit}>
                        {savingEdit ? <Loader2 className="h-3 w-3 animate-spin" /> : t("schedule.save")}
                      </Button>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {jobs.length === 0 && (
          <p className="text-xs text-muted-foreground text-center py-6">{t("schedule.empty")}</p>
        )}
      </div>
    </ScrollArea>
  );
}

// ── Runs Tab ────────────────────────────────────────────────────────────────

const RUN_STATUS_FILTERS = ["all", "completed", "failed", "cancelled", "running"] as const;

function RunsTab({
  scriptId, currentExecId, runStatus, onSelect,
}: {
  scriptId: string;
  currentExecId: string | null;
  runStatus: RunStatus;
  onSelect: (exec: {
    id: string;
    status: string;
    logs: ExecutionLog[];
    output_data: unknown;
    trace: TraceEvent[];
    topology: GraphTopology | null;
    artifacts: ArtifactEvent[];
  }) => void;
}) {
  const { t } = useTranslation("script");
  const [items, setItems] = useState<ExecutionSummary[]>([]);
  const [loadingRuns, setLoadingRuns] = useState(false);
  const [confirmDelId, setConfirmDelId] = useState<string | null>(null);
  const [confirmClear, setConfirmClear] = useState(false);
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");  // "" = all
  const hasFilter = !!search || !!statusFilter;

  // Debounce the free-text search so we don't hit the API on every keystroke.
  useEffect(() => {
    const h = setTimeout(() => setDebouncedSearch(search.trim()), 300);
    return () => clearTimeout(h);
  }, [search]);

  const reload = useCallback(() => {
    setLoadingRuns(true);
    executions.list(scriptId, {
      status: statusFilter || undefined,
      q: debouncedSearch || undefined,
    }).then(setItems).catch(() => null).finally(() => setLoadingRuns(false));
  }, [scriptId, statusFilter, debouncedSearch]);

  async function delOne(id: string) {
    setConfirmDelId(null);
    try {
      await executions.delete(id);
      setItems(prev => prev.filter(x => x.id !== id));
    } catch (e) { toast.error(String(e)); }
  }

  async function clearAll() {
    setConfirmClear(false);
    try {
      const r = await executions.clear(scriptId);
      toast.success(t("runs.toast.cleared", { count: r.deleted }));
      reload();
    } catch (e) { toast.error(String(e)); }
  }

  useEffect(() => { reload(); }, [reload]);
  useEffect(() => {
    if (["running", "completed", "failed", "cancelled"].includes(runStatus)) reload();
  }, [runStatus, currentExecId, reload]);

  const statusIcon = (s: string) => {
    if (s === "completed") return <CheckCircle2 className="h-3 w-3 text-emerald-400" />;
    if (s === "failed") return <XCircle className="h-3 w-3 text-destructive" />;
    if (s === "cancelled") return <MinusCircle className="h-3 w-3 text-amber-400" />;
    if (s === "running") return <Loader2 className="h-3 w-3 animate-spin text-blue-400" />;
    return <Clock className="h-3 w-3 text-muted-foreground" />;
  };

  async function openRun(runId: string) {
    try {
      const full = await executions.get(runId);
      const trace: TraceEvent[] = [];
      let topology: GraphTopology | null = null;
      const artifacts: ArtifactEvent[] = [];
      const visibleLogs: ExecutionLog[] = [];
      for (const l of full.logs) {
        if (l.level === "_trace" && l.data) {
          trace.push(l.data as TraceEvent);
        } else if (l.level === "_graph" && l.data) {
          topology = l.data as GraphTopology;
        } else if (l.level === "_artifact" && l.data) {
          artifacts.push(l.data as ArtifactEvent);
        } else {
          visibleLogs.push({ ...l });
        }
      }
      onSelect({
        id: full.id,
        status: full.status,
        logs: visibleLogs,
        output_data: full.output_data,
        trace,
        topology,
        artifacts,
      });
    } catch (e) { toast.error(String(e)); }
  }

  return (
    <ScrollArea className="h-full">
      <div className="p-3 space-y-1">
        {(items.length > 0 || hasFilter) && (
          <div className="pb-2 space-y-1.5">
            <div className="relative">
              <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-muted-foreground/60 pointer-events-none" />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={t("runs.searchPlaceholder")}
                className="w-full h-7 pl-7 pr-6 rounded-md bg-secondary/40 border border-border/60 text-[11px] focus:outline-none focus:border-primary/50 transition-colors"
              />
              {search && (
                <button
                  onClick={() => setSearch("")}
                  className="absolute right-1.5 top-1/2 -translate-y-1/2 text-muted-foreground/60 hover:text-foreground"
                  title={t("runs.clearSearch")}
                >
                  <X className="h-3 w-3" />
                </button>
              )}
            </div>
            <div className="flex items-center gap-1 flex-wrap">
              {RUN_STATUS_FILTERS.map((sf) => {
                const active = (statusFilter || "all") === sf;
                return (
                  <button
                    key={sf}
                    onClick={() => setStatusFilter(sf === "all" ? "" : sf)}
                    className={`text-[10px] px-1.5 py-0.5 rounded border transition-colors ${
                      active
                        ? "bg-primary/15 border-primary/40 text-primary"
                        : "bg-secondary/30 border-border/50 text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    {sf === "all" ? t("runs.filterAll") : t(`status.${sf}`, { defaultValue: sf })}
                  </button>
                );
              })}
            </div>
          </div>
        )}
        {items.length > 0 && (
          <div className="flex items-center justify-between pb-1">
            <span className="text-[10px] text-muted-foreground/70 tabular-nums">{t("runs.recordCount", { count: items.length })}</span>
            {confirmClear ? (
              <span className="flex items-center gap-1 text-[10px]">
                <span className="text-muted-foreground">{t("runs.clearConfirm.question")}</span>
                <button onClick={clearAll} className="text-destructive hover:underline">{t("runs.clearConfirm.confirm")}</button>
                <button onClick={() => setConfirmClear(false)} className="text-muted-foreground hover:underline">{t("runs.clearConfirm.cancel")}</button>
              </span>
            ) : (
              <button
                onClick={() => setConfirmClear(true)}
                className="flex items-center gap-1 text-[10px] text-muted-foreground hover:text-destructive transition-colors"
                title={t("runs.clearTitle")}
              >
                <Trash2 className="h-3 w-3" />{t("runs.clearButton")}
              </button>
            )}
          </div>
        )}
        {loadingRuns && items.length === 0 && <div className="text-xs text-muted-foreground">{t("runs.loading")}</div>}
        {!loadingRuns && items.length === 0 && (
          <div className="text-xs text-muted-foreground">{hasFilter ? t("runs.noMatches") : t("runs.empty")}</div>
        )}
        {items.map(e => {
          const inFlight = ["running", "queued", "pending"].includes(e.status);
          return (
            <div
              key={e.id}
              className={`group flex items-center gap-2 text-xs px-2 py-1.5 rounded hover:bg-secondary/40 transition-colors ${
                currentExecId === e.id ? "bg-secondary/40" : ""
              }`}
            >
              <button onClick={() => openRun(e.id)} className="flex items-center gap-2 flex-1 min-w-0 text-left">
                {statusIcon(e.status)}
                <span className="font-mono text-muted-foreground">{e.id.slice(0, 8)}</span>
                <span className="text-muted-foreground">{t(`status.${e.status}`, { defaultValue: e.status })}</span>
                {!!e.total_tokens && (
                  <span
                    className="flex items-center gap-0.5 text-muted-foreground/70 tabular-nums shrink-0"
                    title={t("runs.tokensTitle", { calls: e.llm_calls ?? 0 })}
                  >
                    <Coins className="h-2.5 w-2.5" />{compactNumber(e.total_tokens)}
                  </span>
                )}
                <span className="ml-auto text-muted-foreground shrink-0">{formatDate(e.created_at)}</span>
              </button>
              {confirmDelId === e.id ? (
                <span className="flex items-center gap-1 shrink-0">
                  <button onClick={() => delOne(e.id)} className="text-destructive" title={t("runs.confirmDeleteTitle")}><Check className="h-3 w-3" /></button>
                  <button onClick={() => setConfirmDelId(null)} className="text-muted-foreground" title={t("runs.cancelTitle")}><XCircle className="h-3 w-3" /></button>
                </span>
              ) : (
                !inFlight && (
                  <button
                    onClick={() => setConfirmDelId(e.id)}
                    className="shrink-0 text-muted-foreground/50 hover:text-destructive opacity-0 group-hover:opacity-100 transition-opacity"
                    title={t("runs.deleteRecordTitle")}
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                )
              )}
            </div>
          );
        })}
      </div>
    </ScrollArea>
  );
}
