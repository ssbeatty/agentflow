"use client";
import { Suspense, useEffect, useRef, useState, useCallback } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import {
  ArrowLeft, Play, Square, Save, Terminal, Settings2,
  Clock, ChevronRight, Loader2, CalendarClock,
  History, CheckCircle2, XCircle, MinusCircle, Copy, Trash2, Wrench, Check,
} from "lucide-react";
import { toast } from "sonner";
import { scripts, executions, mcpServers } from "@/lib/api";
import type { Script, ScriptFile, ExecutionLog, WsEvent, MCPServerConfig } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription,
} from "@/components/ui/dialog";
import ScriptEditor, { type LintIssue } from "@/components/ScriptEditor";
import LogPanel from "@/components/LogPanel";
import DependencyManager from "@/components/DependencyManager";
import FileTree, { type TreeFile } from "@/components/FileTree";
import { useResizable } from "@/components/Splitter";

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
  const [selectedMcpIds, setSelectedMcpIds] = useState<string[]>([]);
  const [availableMcpServers, setAvailableMcpServers] = useState<MCPServerConfig[]>([]);
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
  const wsRef = useRef<WebSocket | null>(null);

  const [lintIssues, setLintIssues] = useState<LintIssue[]>([]);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);

  // Lint: debounce on active .py file content
  useEffect(() => {
    if (!id || !activeFile.endsWith(".py")) { setLintIssues([]); return; }
    const content = fileContents.get(activeFile) ?? "";
    if (!content) { setLintIssues([]); return; }
    const t = setTimeout(() => {
      scripts.lint(id, content)
        .then(r => setLintIssues(r.issues))
        .catch(() => setLintIssues([]));
    }, 500);
    return () => clearTimeout(t);
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
  const [bottomHeight, bottomHandle] = useResizable({
    direction: "horizontal", initial: 200, min: 80, max: 500,
    storageKey: "ag.bottomHeight", side: "end",
  });
  const [rightWidth, rightHandle] = useResizable({
    direction: "vertical", initial: 360, min: 260, max: 720,
    storageKey: "ag.rightWidth", side: "end",
  });

  // Load script
  useEffect(() => {
    Promise.all([scripts.get(id), mcpServers.list()])
      .then(([s, servers]) => {
        setScript(s);
        setName(s.name);
        setEntryFn(s.entry_function);
        setSelectedMcpIds(s.mcp_server_ids || []);
        setAvailableMcpServers(servers.filter(srv => srv.enabled));

        const contents = new Map<string, string>();
        for (const f of s.files) contents.set(f.filename, f.content);
        contents.set("requirements.txt", s.requirements || "");
        setFileContents(contents);
        setScriptFiles(s.files);

        const main = s.files.find(f => f.is_main) ?? s.files[0];
        setActiveFile(main?.filename ?? "main.py");
      })
      .catch(() => { toast.error("Script not found"); router.push("/"); })
      .finally(() => setLoading(false));
  }, [id, router]);

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
      } else if (msg.type === "status") {
        setRunStatus(msg.status as RunStatus);
        if (msg.output !== undefined) setOutput(msg.output);
        const terminal = ["completed", "failed", "cancelled"].includes(msg.status);
        if (terminal) {
          ws.close();
          if (msg.status === "failed" && msg.error) toast.error(`Failed: ${msg.error}`);
          if (msg.status === "completed") toast.success("Execution completed");
        }
      }
    };
    ws.onerror = () => setRunStatus("failed");
  }, []);

  async function handleRun() {
    try {
      const parsed = JSON.parse(inputJson || "{}");
      setInputError("");
      if (dirty) await handleSave();
      setLogs([]);
      setOutput(null);
      setRunStatus("running");
      setActiveTab("logs");
      const exec = await executions.create(id, parsed);
      setCurrentExecId(exec.id);
      connectWs(exec.id);
    } catch (e: unknown) {
      if (e instanceof SyntaxError) { setInputError("Invalid JSON"); return; }
      toast.error(String(e));
      setRunStatus("failed");
    }
  }

  function formatJson() {
    try {
      setInputJson(JSON.stringify(JSON.parse(inputJson), null, 2));
      setInputError("");
    } catch {
      setInputError("Invalid JSON");
    }
  }

  async function handleStop() {
    if (!currentExecId) return;
    try {
      const r = await executions.stop(currentExecId);
      setRunStatus((r as { status?: RunStatus }).status ?? "cancelled");
    } catch (e) {
      toast.error(`Stop failed: ${e}`);
      setRunStatus("cancelled");
    } finally { wsRef.current?.close(); }
  }

  async function handleSave() {
    if (!script) return;
    setSaving(true);
    try {
      const reqContent = fileContents.get("requirements.txt") ?? "";
      const ops: Promise<unknown>[] = [
        scripts.update(id, { name, entry_function: entryFn, requirements: reqContent, mcp_server_ids: selectedMcpIds }),
      ];
      for (const filename of dirtyFiles) {
        if (filename === "requirements.txt" || filename === "__meta__") continue;
        const content = fileContents.get(filename) ?? "";
        const file = scriptFiles.find(f => f.filename === filename);
        ops.push(scripts.upsertFile(id, { filename, content, is_main: file?.is_main ?? false }));
      }
      await Promise.all(ops);
      setDirtyFiles(new Set());
      setScript(prev => prev ? { ...prev, name, entry_function: entryFn, requirements: reqContent, mcp_server_ids: selectedMcpIds } : prev);
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
      await scripts.delete(id);
      toast.success("Script deleted");
      router.push("/");
    } catch (e: unknown) {
      toast.error(String(e));
      setDeleting(false);
      setDeleteOpen(false);
    }
  }

  // ── File tree operations ──────────────────────────────────────────────────

  function markDirty(filename: string) {
    setDirtyFiles(prev => new Set(prev).add(filename));
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
          title="Copy script ID" onClick={() => { navigator.clipboard.writeText(id); toast.success("Script ID copied"); }}>
          <Copy className="h-3 w-3" />
        </Button>
        <Button variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground hover:text-destructive"
          title="Delete script" onClick={() => setDeleteOpen(true)}>
          <Trash2 className="h-3 w-3" />
        </Button>

        {dirty && <span className="text-xs text-muted-foreground">unsaved</span>}
        {lintForActive.length > 0 && (
          <span className={`text-xs flex items-center gap-1 ${
            lintForActive.some(i => i.severity === "error") ? "text-destructive" : "text-amber-400"
          }`}>
            ● {lintForActive.length} issue{lintForActive.length > 1 ? "s" : ""}
          </span>
        )}

        <div className="ml-auto flex items-center gap-2">
          {runStatus !== "idle" && (
            <span className={`text-xs font-medium flex items-center gap-1.5 ${STATUS_COLORS[runStatus]}`}>
              {(runStatus === "queued" || runStatus === "running") && <Loader2 className="h-3 w-3 animate-spin" />}
              {runStatus}
            </span>
          )}
          <Button variant="outline" size="sm" onClick={handleSave} disabled={saving || !dirty}>
            {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />}
            Save
          </Button>
          {(runStatus === "queued" || runStatus === "running") ? (
            <Button variant="destructive" size="sm" onClick={handleStop}>
              <Square className="h-3 w-3" />Stop
            </Button>
          ) : (
            <Button size="sm" onClick={handleRun}>
              <Play className="h-3 w-3" />Run
            </Button>
          )}
        </div>
      </header>

      {/* Body */}
      <div className="flex flex-1 overflow-hidden">

        {/* Left panel: File tree (top) + Packages (bottom) */}
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

        {/* Center: Editor + bottom tabs */}
        <div className="flex flex-col flex-1 min-w-0 border-r border-border">
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
              issues={lintForActive}
            />
          </div>

          {bottomHandle}
          {/* Bottom tabs: Logs, Output, Schedule, Runs */}
          <div className="shrink-0 border-t border-border" style={{ height: `${bottomHeight}px` }}>
            <Tabs value={activeTab} onValueChange={setActiveTab} className="h-full flex flex-col">
              <TabsList className="rounded-none border-b border-border bg-transparent px-4 h-9 justify-start gap-1 shrink-0">
                <TabsTrigger value="logs" className="text-xs gap-1.5">
                  <Terminal className="h-3 w-3" />Logs
                </TabsTrigger>
                <TabsTrigger value="output" className="text-xs gap-1.5">
                  <ChevronRight className="h-3 w-3" />Output
                </TabsTrigger>
                <TabsTrigger value="schedule" className="text-xs gap-1.5">
                  <CalendarClock className="h-3 w-3" />Schedule
                </TabsTrigger>
                <TabsTrigger value="runs" className="text-xs gap-1.5">
                  <History className="h-3 w-3" />Runs
                </TabsTrigger>
              </TabsList>
              <div className="flex-1 overflow-hidden">
                <TabsContent value="logs" className="h-full m-0">
                  <LogPanel logs={logs} />
                </TabsContent>
                <TabsContent value="output" className="h-full m-0 p-3">
                  <ScrollArea className="h-full">
                    {output !== null
                      ? <pre className="text-xs font-mono text-muted-foreground whitespace-pre-wrap">{JSON.stringify(output, null, 2)}</pre>
                      : <p className="text-xs text-muted-foreground">No output yet.</p>}
                  </ScrollArea>
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
                      setRunStatus(exec.status as RunStatus);
                      setActiveTab("logs");
                    }}
                  />
                </TabsContent>
              </div>
            </Tabs>
          </div>
        </div>

        {rightHandle}

        {/* Right: Config panel */}
        <div className="shrink-0 flex flex-col overflow-y-auto border-l border-border" style={{ width: `${rightWidth}px` }}>
          <div className="p-4 space-y-5">

            {/* Entry function */}
            <div className="space-y-1.5">
              <p className="text-[10px] uppercase tracking-wider font-semibold text-muted-foreground/70">Entry function</p>
              <div className="relative">
                <Settings2 className="absolute left-2.5 top-[9px] h-3.5 w-3.5 text-muted-foreground pointer-events-none" />
                <Input
                  value={entryFn}
                  onChange={e => { setEntryFn(e.target.value); markDirty("__meta__"); }}
                  className="pl-8 h-8 text-xs font-mono"
                  placeholder="run"
                />
              </div>
            </div>

            {/* MCP Servers */}
            {availableMcpServers.length > 0 && (
              <div className="space-y-2">
                <p className="text-[10px] uppercase tracking-wider font-semibold text-muted-foreground/70 flex items-center gap-1.5">
                  <Wrench className="h-3 w-3" />MCP Servers
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {availableMcpServers.map(srv => {
                    const active = selectedMcpIds.includes(srv.id);
                    return (
                      <button
                        key={srv.id}
                        onClick={() => {
                          setSelectedMcpIds(prev => active ? prev.filter(x => x !== srv.id) : [...prev, srv.id]);
                          markDirty("__meta__");
                        }}
                        title={srv.transport}
                        className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium border transition-all ${
                          active
                            ? "bg-primary/10 border-primary/40 text-primary"
                            : "bg-secondary/30 border-border/60 text-muted-foreground hover:border-border hover:text-foreground"
                        }`}
                      >
                        {active
                          ? <Check className="h-3 w-3 shrink-0" />
                          : <span className="h-3 w-3 shrink-0" />
                        }
                        {srv.name}
                      </button>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Input JSON */}
            <div className="space-y-1.5">
              <p className="text-[10px] uppercase tracking-wider font-semibold text-muted-foreground/70 flex items-center justify-between">
                <span className="flex items-center gap-2">
                  Input JSON
                  {inputError && <span className="text-destructive normal-case font-normal">{inputError}</span>}
                </span>
                <button onClick={formatJson}
                  className="text-[10px] normal-case font-normal text-muted-foreground hover:text-foreground transition-colors">
                  Format
                </button>
              </p>
              <Textarea
                value={inputJson}
                onChange={e => { setInputJson(e.target.value); setInputError(""); }}
                className="text-xs font-mono min-h-[100px] resize-y"
                placeholder="{}"
                spellCheck={false}
              />
            </div>

          </div>
        </div>
      </div>

      {/* Delete dialog */}
      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>Delete script?</DialogTitle>
            <DialogDescription>
              <span className="font-medium text-foreground">{name}</span> and all its runs will be permanently deleted.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteOpen(false)} disabled={deleting}>Cancel</Button>
            <Button variant="destructive" onClick={handleDelete} disabled={deleting}>
              {deleting ? <Loader2 className="h-3 w-3 animate-spin" /> : <Trash2 className="h-3 w-3" />}
              Delete
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
import { formatDate } from "@/lib/utils";
import { Plus } from "lucide-react";

const CRON_PRESETS = [
  { label: "Every 5m", value: "*/5 * * * *" },
  { label: "Hourly", value: "0 * * * *" },
  { label: "Daily", value: "0 0 * * *" },
  { label: "Weekly", value: "0 0 * * 0" },
  { label: "Monthly", value: "0 0 1 * *" },
] as const;

function ScheduleTab({ scriptId }: { scriptId: string }) {
  const [jobs, setJobs] = useState<CronJob[]>([]);
  const [expr, setExpr] = useState("0 * * * *");
  const [label, setLabel] = useState("");
  const [adding, setAdding] = useState(false);

  useEffect(() => {
    cronJobs.list(scriptId).then(setJobs).catch(() => null);
  }, [scriptId]);

  async function add() {
    if (!expr) return;
    setAdding(true);
    try {
      const j = await cronJobs.create({ script_id: scriptId, label, cron_expression: expr, input_data: {}, enabled: true });
      setJobs(p => [...p, j]);
      setLabel("");
    } catch (e: unknown) {
      toast.error(String(e));
    } finally { setAdding(false); }
  }

  async function remove(jobId: string) {
    await cronJobs.delete(jobId);
    setJobs(p => p.filter(j => j.id !== jobId));
  }

  async function toggle(job: CronJob) {
    const updated = await cronJobs.update(job.id, { enabled: !job.enabled });
    setJobs(p => p.map(j => j.id === updated.id ? updated : j));
  }

  return (
    <ScrollArea className="h-full">
      <div className="p-3 space-y-4">

        {/* Add form */}
        <div className="space-y-2">
          <p className="text-[10px] uppercase tracking-wider font-semibold text-muted-foreground/70">New schedule</p>
          <div className="flex flex-wrap gap-1">
            {CRON_PRESETS.map(p => (
              <button key={p.value} onClick={() => setExpr(p.value)}
                className={`text-[10px] px-2.5 py-1 rounded-full border transition-colors ${
                  expr === p.value
                    ? "bg-primary/10 border-primary/40 text-primary"
                    : "border-border/60 text-muted-foreground hover:border-border hover:text-foreground"
                }`}>
                {p.label}
              </button>
            ))}
          </div>
          <div className="flex gap-1.5">
            <Input value={expr} onChange={e => setExpr(e.target.value)} placeholder="0 * * * *"
              className="h-7 text-xs font-mono flex-1 min-w-0" />
            <Input value={label} onChange={e => setLabel(e.target.value)} placeholder="label"
              className="h-7 text-xs w-20 shrink-0" />
            <Button size="sm" className="h-7 px-2 shrink-0" onClick={add} disabled={adding || !expr}>
              {adding ? <Loader2 className="h-3 w-3 animate-spin" /> : <Plus className="h-3 w-3" />}
            </Button>
          </div>
        </div>

        {/* Job list */}
        {jobs.length > 0 && (
          <div className="space-y-1.5">
            <p className="text-[10px] uppercase tracking-wider font-semibold text-muted-foreground/70">Schedules</p>
            {jobs.map(j => (
              <div key={j.id}
                className="flex items-center gap-2.5 px-2.5 py-2 rounded-lg border border-border bg-secondary/10 group hover:bg-secondary/20 transition-colors">
                <button onClick={() => toggle(j)} title={j.enabled ? "Disable" : "Enable"} className="shrink-0">
                  <div className={`h-2 w-2 rounded-full transition-colors ${j.enabled ? "bg-emerald-400" : "bg-muted-foreground/30"}`} />
                </button>
                <div className="flex-1 min-w-0">
                  <div className="font-mono text-xs text-foreground">{j.cron_expression}</div>
                  {j.label && <div className="text-[10px] text-muted-foreground truncate mt-0.5">{j.label}</div>}
                </div>
                <button onClick={() => remove(j.id)}
                  className="opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive transition-all shrink-0">
                  <Trash2 className="h-3 w-3" />
                </button>
              </div>
            ))}
          </div>
        )}

        {jobs.length === 0 && (
          <p className="text-xs text-muted-foreground text-center py-6">No schedules yet</p>
        )}
      </div>
    </ScrollArea>
  );
}

// ── Runs Tab ────────────────────────────────────────────────────────────────

function RunsTab({
  scriptId, currentExecId, runStatus, onSelect,
}: {
  scriptId: string;
  currentExecId: string | null;
  runStatus: RunStatus;
  onSelect: (exec: { id: string; status: string; logs: ExecutionLog[]; output_data: unknown }) => void;
}) {
  const [items, setItems] = useState<ExecutionSummary[]>([]);
  const [loadingRuns, setLoadingRuns] = useState(false);

  const reload = useCallback(() => {
    setLoadingRuns(true);
    executions.list(scriptId).then(setItems).catch(() => null).finally(() => setLoadingRuns(false));
  }, [scriptId]);

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
      onSelect({ id: full.id, status: full.status, logs: full.logs, output_data: full.output_data });
    } catch (e) { toast.error(String(e)); }
  }

  return (
    <ScrollArea className="h-full">
      <div className="p-3 space-y-1">
        {loadingRuns && items.length === 0 && <div className="text-xs text-muted-foreground">Loading…</div>}
        {!loadingRuns && items.length === 0 && <div className="text-xs text-muted-foreground">No runs yet.</div>}
        {items.map(e => (
          <button
            key={e.id}
            onClick={() => openRun(e.id)}
            className={`w-full flex items-center gap-2 text-xs px-2 py-1.5 rounded hover:bg-secondary/40 transition-colors ${
              currentExecId === e.id ? "bg-secondary/40" : ""
            }`}
          >
            {statusIcon(e.status)}
            <span className="font-mono text-muted-foreground">{e.id.slice(0, 8)}</span>
            <span className="text-muted-foreground">{e.status}</span>
            <span className="ml-auto text-muted-foreground">{formatDate(e.created_at)}</span>
          </button>
        ))}
      </div>
    </ScrollArea>
  );
}
