"use client";
import { useEffect, useRef, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  ArrowLeft, Play, Square, Save, Terminal, Settings2,
  Clock, ChevronRight, Loader2, Package, FileCode, CalendarClock,
} from "lucide-react";
import { toast } from "sonner";
import { scripts, executions } from "@/lib/api";
import type { Script, ExecutionLog, WsEvent } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import ScriptEditor from "@/components/ScriptEditor";
import LogPanel from "@/components/LogPanel";
import DependencyManager from "@/components/DependencyManager";

type RunStatus = "idle" | "running" | "completed" | "failed" | "cancelled";

const STATUS_COLORS: Record<RunStatus, string> = {
  idle: "text-muted-foreground",
  running: "text-blue-400",
  completed: "text-emerald-400",
  failed: "text-destructive",
  cancelled: "text-amber-400",
};

export default function ScriptPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();

  const [script, setScript] = useState<Script | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);

  // editing states
  const [name, setName] = useState("");
  const [entryFn, setEntryFn] = useState("run");
  const [mainContent, setMainContent] = useState("");
  const [requirements, setRequirements] = useState("");
  const [inputJson, setInputJson] = useState("{}");
  const [inputError, setInputError] = useState("");

  // execution
  const [runStatus, setRunStatus] = useState<RunStatus>("idle");
  const [currentExecId, setCurrentExecId] = useState<string | null>(null);
  const [logs, setLogs] = useState<ExecutionLog[]>([]);
  const [output, setOutput] = useState<unknown>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    scripts.get(id)
      .then((s) => {
        setScript(s);
        setName(s.name);
        setEntryFn(s.entry_function);
        setRequirements(s.requirements || "");
        const main = s.files.find((f) => f.is_main) ?? s.files[0];
        if (main) setMainContent(main.content);
      })
      .catch(() => { toast.error("Script not found"); router.push("/"); })
      .finally(() => setLoading(false));
  }, [id, router]);

  // WebSocket for live logs
  const connectWs = useCallback((execId: string) => {
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://localhost:8000/ws/executions/${execId}`);
    wsRef.current = ws;

    ws.onmessage = (e) => {
      const msg: WsEvent = JSON.parse(e.data);
      if (msg.type === "log") {
        setLogs((prev) => [
          ...prev,
          {
            id: `${Date.now()}-${Math.random()}`,
            timestamp: msg.timestamp,
            level: msg.level as ExecutionLog["level"],
            message: msg.message,
            data: msg.data,
            step: msg.step,
          },
        ]);
      } else if (msg.type === "status") {
        setRunStatus(msg.status as RunStatus);
        if (msg.output !== undefined) setOutput(msg.output);
        if (msg.status !== "running") {
          ws.close();
          if (msg.status === "failed" && msg.error) toast.error(`Failed: ${msg.error}`);
          if (msg.status === "completed") toast.success("Execution completed");
        }
      }
    };

    ws.onerror = () => setRunStatus("failed");
  }, []);

  async function handleRun() {
    // validate JSON
    try {
      const parsed = JSON.parse(inputJson || "{}");
      setInputError("");
      // save first if dirty
      if (dirty) await handleSave();

      setLogs([]);
      setOutput(null);
      setRunStatus("running");

      const exec = await executions.create(id, parsed);
      setCurrentExecId(exec.id);
      connectWs(exec.id);
    } catch (e: unknown) {
      if (e instanceof SyntaxError) {
        setInputError("Invalid JSON");
        return;
      }
      toast.error(String(e));
      setRunStatus("failed");
    }
  }

  async function handleStop() {
    if (!currentExecId) return;
    await executions.stop(currentExecId);
    wsRef.current?.close();
    setRunStatus("cancelled");
  }

  async function handleSave() {
    if (!script) return;
    setSaving(true);
    try {
      await Promise.all([
        scripts.update(id, { name, entry_function: entryFn, requirements }),
        scripts.upsertFile(id, {
          filename: "main.py",
          content: mainContent,
          is_main: true,
        }),
      ]);
      setDirty(false);
      setScript((prev) => prev ? { ...prev, name, entry_function: entryFn, requirements } : prev);
      toast.success("Saved");
    } catch (e: unknown) {
      toast.error(String(e));
    } finally {
      setSaving(false);
    }
  }

  function markDirty() { setDirty(true); }

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="h-screen flex flex-col overflow-hidden">
      {/* Top bar */}
      <header className="border-b border-border px-4 py-2.5 flex items-center gap-3 shrink-0">
        <Link href="/">
          <Button variant="ghost" size="icon" className="h-8 w-8">
            <ArrowLeft className="h-4 w-4" />
          </Button>
        </Link>
        <input
          value={name}
          onChange={(e) => { setName(e.target.value); markDirty(); }}
          className="bg-transparent text-sm font-medium focus:outline-none border-b border-transparent focus:border-border w-48"
        />
        {dirty && <span className="text-xs text-muted-foreground">unsaved</span>}

        <div className="ml-auto flex items-center gap-2">
          {/* Status indicator */}
          {runStatus !== "idle" && (
            <span className={`text-xs font-medium flex items-center gap-1.5 ${STATUS_COLORS[runStatus]}`}>
              {runStatus === "running" && <Loader2 className="h-3 w-3 animate-spin" />}
              {runStatus}
            </span>
          )}

          <Button variant="outline" size="sm" onClick={handleSave} disabled={saving || !dirty}>
            {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />}
            Save
          </Button>

          {runStatus === "running" ? (
            <Button variant="destructive" size="sm" onClick={handleStop}>
              <Square className="h-3 w-3" />
              Stop
            </Button>
          ) : (
            <Button size="sm" onClick={handleRun}>
              <Play className="h-3 w-3" />
              Run
            </Button>
          )}
        </div>
      </header>

      {/* Body: editor (left) + panel (right) */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left: Editor + bottom tabs */}
        <div className="flex flex-col flex-1 min-w-0 border-r border-border">
          {/* Monaco Editor */}
          <div className="flex-1 min-h-0">
            <ScriptEditor
              value={mainContent}
              onChange={(v) => { setMainContent(v ?? ""); markDirty(); }}
            />
          </div>

          {/* Bottom tabs */}
          <div className="shrink-0 border-t border-border" style={{ height: "200px" }}>
            <Tabs defaultValue="deps" className="h-full flex flex-col">
              <TabsList className="rounded-none border-b border-border bg-transparent px-4 h-9 justify-start gap-1">
                <TabsTrigger value="deps" className="text-xs gap-1.5">
                  <Package className="h-3 w-3" />Dependencies
                </TabsTrigger>
                <TabsTrigger value="files" className="text-xs gap-1.5">
                  <FileCode className="h-3 w-3" />Files
                </TabsTrigger>
                <TabsTrigger value="schedule" className="text-xs gap-1.5">
                  <CalendarClock className="h-3 w-3" />Schedule
                </TabsTrigger>
              </TabsList>
              <div className="flex-1 overflow-hidden">
                <TabsContent value="deps" className="h-full m-0">
                  <DependencyManager
                    scriptId={id}
                    requirements={requirements}
                    onRequirementsChange={(v) => { setRequirements(v); markDirty(); }}
                  />
                </TabsContent>
                <TabsContent value="files" className="h-full m-0 p-3">
                  <ScrollArea className="h-full">
                    {script?.files.map((f) => (
                      <div key={f.id} className="flex items-center gap-2 py-1 text-sm">
                        <FileCode className="h-3 w-3 text-muted-foreground" />
                        <span className="font-mono text-xs">{f.filename}</span>
                        {f.is_main && <Badge variant="outline" className="text-xs py-0">main</Badge>}
                      </div>
                    ))}
                  </ScrollArea>
                </TabsContent>
                <TabsContent value="schedule" className="h-full m-0">
                  <ScheduleTab scriptId={id} />
                </TabsContent>
              </div>
            </Tabs>
          </div>
        </div>

        {/* Right: Config + Logs */}
        <div className="w-96 shrink-0 flex flex-col overflow-hidden">
          {/* Entry fn + Input */}
          <div className="p-4 space-y-3 border-b border-border shrink-0">
            <div className="flex items-center gap-3">
              <div className="flex-1 space-y-1">
                <Label className="text-xs">Entry function</Label>
                <div className="relative">
                  <Settings2 className="absolute left-2.5 top-2 h-3.5 w-3.5 text-muted-foreground" />
                  <Input
                    value={entryFn}
                    onChange={(e) => { setEntryFn(e.target.value); markDirty(); }}
                    className="pl-8 h-8 text-xs font-mono"
                    placeholder="run"
                  />
                </div>
              </div>
            </div>
            <div className="space-y-1">
              <Label className="text-xs flex items-center justify-between">
                Input JSON
                {inputError && <span className="text-destructive text-xs">{inputError}</span>}
              </Label>
              <Textarea
                value={inputJson}
                onChange={(e) => { setInputJson(e.target.value); setInputError(""); }}
                className="h-20 text-xs font-mono"
                placeholder="{}"
                spellCheck={false}
              />
            </div>
          </div>

          {/* Logs panel */}
          <div className="flex-1 min-h-0">
            <Tabs defaultValue="logs" className="h-full flex flex-col">
              <TabsList className="rounded-none border-b border-border bg-transparent px-4 h-9 justify-start gap-1 shrink-0">
                <TabsTrigger value="logs" className="text-xs gap-1.5">
                  <Terminal className="h-3 w-3" />Logs
                </TabsTrigger>
                <TabsTrigger value="output" className="text-xs gap-1.5">
                  <ChevronRight className="h-3 w-3" />Output
                </TabsTrigger>
              </TabsList>
              <div className="flex-1 min-h-0">
                <TabsContent value="logs" className="h-full m-0">
                  <LogPanel logs={logs} />
                </TabsContent>
                <TabsContent value="output" className="h-full m-0 p-3">
                  <ScrollArea className="h-full">
                    {output !== null ? (
                      <pre className="text-xs font-mono text-muted-foreground whitespace-pre-wrap">
                        {JSON.stringify(output, null, 2)}
                      </pre>
                    ) : (
                      <p className="text-xs text-muted-foreground">No output yet</p>
                    )}
                  </ScrollArea>
                </TabsContent>
              </div>
            </Tabs>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Schedule tab ────────────────────────────────────────────────────────────

import { cronJobs } from "@/lib/api";
import type { CronJob } from "@/lib/types";
import { Trash2 } from "lucide-react";

function ScheduleTab({ scriptId }: { scriptId: string }) {
  const [jobs, setJobs] = useState<CronJob[]>([]);
  const [expr, setExpr] = useState("0 * * * *");
  const [label, setLabel] = useState("");
  const [adding, setAdding] = useState(false);

  useEffect(() => {
    cronJobs.list(scriptId).then(setJobs).catch(() => null);
  }, [scriptId]);

  async function add() {
    setAdding(true);
    try {
      const j = await cronJobs.create({
        script_id: scriptId, label, cron_expression: expr,
        input_data: {}, enabled: true,
      });
      setJobs((p) => [...p, j]);
      setExpr("0 * * * *");
      setLabel("");
    } catch (e: unknown) {
      toast.error(String(e));
    } finally {
      setAdding(false);
    }
  }

  async function remove(jobId: string) {
    await cronJobs.delete(jobId);
    setJobs((p) => p.filter((j) => j.id !== jobId));
  }

  async function toggle(job: CronJob) {
    const updated = await cronJobs.update(job.id, { enabled: !job.enabled });
    setJobs((p) => p.map((j) => (j.id === updated.id ? updated : j)));
  }

  return (
    <ScrollArea className="h-full">
      <div className="p-3 space-y-3">
        {jobs.map((j) => (
          <div key={j.id} className="flex items-center gap-2 text-xs border border-border rounded p-2">
            <button onClick={() => toggle(j)} className={j.enabled ? "text-emerald-400" : "text-muted-foreground"}>
              <Clock className="h-3 w-3" />
            </button>
            <span className="font-mono">{j.cron_expression}</span>
            {j.label && <span className="text-muted-foreground">{j.label}</span>}
            <button onClick={() => remove(j.id)} className="ml-auto text-muted-foreground hover:text-destructive">
              <Trash2 className="h-3 w-3" />
            </button>
          </div>
        ))}
        <Separator />
        <div className="flex gap-2">
          <Input
            value={expr}
            onChange={(e) => setExpr(e.target.value)}
            placeholder="0 * * * *"
            className="h-7 text-xs font-mono flex-1"
          />
          <Input
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="label"
            className="h-7 text-xs w-20"
          />
          <Button size="sm" className="h-7 text-xs" onClick={add} disabled={adding}>
            <Plus className="h-3 w-3" />
          </Button>
        </div>
      </div>
    </ScrollArea>
  );
}

import { Plus } from "lucide-react";
