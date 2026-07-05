"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  Sparkles, Send, Square, Loader2, X, RotateCcw, FileDiff, Check,
  AlertTriangle, PackagePlus, Eraser, Brain,
} from "lucide-react";
import { toast } from "sonner";
import { DiffEditor } from "@monaco-editor/react";
import {
  assistant as assistantApi, executions as executionsApi, channels as channelsApi,
} from "@/lib/api";
import type { WsEvent } from "@/lib/types";
import AgentTimeline, {
  reduceEvent, answerFromBlocks, type Block,
} from "@/components/AgentTimeline";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

export interface ChangedFile { filename: string; before: string; after: string; }

interface Msg {
  id: string;
  role: "user" | "assistant";
  content: string;        // user text; assistant non-streaming fallback
  blocks: Block[];        // assistant chronological timeline
  error?: string;
  streaming?: boolean;
}

interface Props {
  /** Full context object handed to the assistant each turn (kind, target id, active file, selection…). */
  buildContext: () => Record<string, unknown>;
  onBeforeTurn: () => Promise<void>;
  onAfterTurn: () => Promise<ChangedFile[]>;
  onRevert: (filenames: string[]) => Promise<void>;
  onOpenFile: (filename: string) => void;
  onClose: () => void;
  targetLabel?: string;   // "script" | "skill"
}

const HISTORY_LIMIT = 16;
const REASONING_LEVELS = ["off", "low", "medium", "high"] as const;
const REASONING_LABEL: Record<string, string> = { off: "off", low: "low", medium: "med", high: "high" };

function uid() { return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`; }

function diffLang(filename: string): string {
  if (filename.endsWith(".py")) return "python";
  if (filename.endsWith(".json")) return "json";
  if (filename.endsWith(".md")) return "markdown";
  if (filename.endsWith(".ts") || filename.endsWith(".tsx")) return "typescript";
  if (filename.endsWith(".js")) return "javascript";
  if (filename.endsWith(".yaml") || filename.endsWith(".yml")) return "yaml";
  return "plaintext";
}

function answerText(m: Msg): string {
  return m.blocks.length ? answerFromBlocks(m.blocks) : m.content;
}

export default function AssistantPanel({
  buildContext, onBeforeTurn, onAfterTurn, onRevert, onOpenFile, onClose, targetLabel = "script",
}: Props) {
  const [info, setInfo] = useState<{ script_id: string; venv_ready: boolean } | null>(null);
  const [infoError, setInfoError] = useState<string | null>(null);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [execId, setExecId] = useState<string | null>(null);

  // model + reasoning
  const [models, setModels] = useState<string[]>([]);
  const [model, setModel] = useState<string>("");
  const [reasoning, setReasoning] = useState<string>("off");

  // post-turn diff review
  const [diff, setDiff] = useState<ChangedFile[]>([]);
  const [diffOpen, setDiffOpen] = useState(false);
  const [diffFile, setDiffFile] = useState<string | null>(null);
  const [reverting, setReverting] = useState(false);

  // first-run venv setup
  const [venvBusy, setVenvBusy] = useState(false);
  const [venvLines, setVenvLines] = useState<string[]>([]);

  const wsRef = useRef<WebSocket | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const tokenSeenRef = useRef(false);

  useEffect(() => {
    assistantApi.info().then(setInfo).catch((e) => setInfoError(String(e)));
    channelsApi.list().then((chs) => {
      const enabled = chs.filter((c) => c.enabled);
      const list = Array.from(new Set(enabled.flatMap((c) => c.models ?? [])));
      const def = enabled.find((c) => c.is_default)?.default_model || list[0] || "";
      setModels(list);
      setModel(def);
    }).catch(() => { /* model list is best-effort; falls back to default */ });
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, diff]);

  useEffect(() => () => { wsRef.current?.close(); }, []);

  // ── venv setup (reuses the install WS) ──────────────────────────────────────
  const initVenv = useCallback(() => {
    if (!info || venvBusy) return;
    setVenvBusy(true);
    setVenvLines([]);
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${window.location.host}/ws/install/${info.script_id}?action=venv`);
    ws.onmessage = (e) => {
      let evt: { type: string; text?: string; done?: boolean; message?: string };
      try { evt = JSON.parse(e.data); } catch { return; }
      if (evt.type === "error") { toast.error(evt.message || "Initialization failed"); return; }
      if (evt.text) setVenvLines((prev) => [...prev.slice(-80), evt.text!]);
      if (evt.done) {
        ws.close();
        setVenvBusy(false);
        const ok = evt.text === "DONE" || !(evt.text || "").startsWith("ERROR:");
        if (ok) { setInfo((p) => p ? { ...p, venv_ready: true } : p); toast.success("Assistant environment ready"); }
        else toast.error("Environment setup failed — see the log");
      }
    };
    ws.onerror = () => { setVenvBusy(false); toast.error("Environment setup connection failed"); };
  }, [info, venvBusy]);

  // ── turn lifecycle ──────────────────────────────────────────────────────────
  const finalize = useCallback(async (asstId: string, executionId: string) => {
    if (!tokenSeenRef.current) {
      try {
        const exc = await executionsApi.get(executionId);
        const reply = ((): string => {
          const od = exc.output_data as unknown;
          if (od && typeof od === "object" && "reply" in od) return String((od as Record<string, unknown>).reply ?? "");
          if (typeof od === "string") return od;
          return "";
        })();
        setMessages((prev) => prev.map((m) => m.id === asstId
          ? { ...m, content: reply, blocks: reply ? [{ type: "text", content: reply }] : m.blocks, error: exc.error ?? m.error, streaming: false }
          : m));
      } catch {
        setMessages((prev) => prev.map((m) => m.id === asstId ? { ...m, streaming: false } : m));
      }
    } else {
      setMessages((prev) => prev.map((m) => m.id === asstId ? { ...m, streaming: false } : m));
    }
    try {
      const changed = await onAfterTurn();
      if (changed.length) { setDiff(changed); setDiffFile(changed[0].filename); }
    } catch { /* editor refetch best-effort */ }
    setSending(false);
    setExecId(null);
  }, [onAfterTurn]);

  const openWs = useCallback((executionId: string, asstId: string) => {
    tokenSeenRef.current = false;
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${window.location.host}/ws/executions/${executionId}`);
    wsRef.current = ws;
    ws.onmessage = (e) => {
      let evt: WsEvent;
      try { evt = JSON.parse(e.data); } catch { return; }
      if (evt.type === "token") tokenSeenRef.current = true;
      if (evt.type === "token" || evt.type === "trace") {
        setMessages((prev) => prev.map((m) => m.id === asstId
          ? { ...m, blocks: reduceEvent(m.blocks, evt), streaming: true } : m));
      } else if (evt.type === "status") {
        const done = ["completed", "failed", "cancelled"].includes(evt.status);
        if (done) {
          ws.close();
          wsRef.current = null;
          if (evt.status === "failed" && evt.error) {
            setMessages((prev) => prev.map((m) => m.id === asstId ? { ...m, error: evt.error, streaming: false } : m));
          }
          finalize(asstId, executionId);
        }
      }
    };
    ws.onerror = () => {
      setMessages((prev) => prev.map((m) => m.id === asstId ? { ...m, error: "WebSocket connection error", streaming: false } : m));
      setSending(false);
      setExecId(null);
    };
  }, [finalize]);

  const send = useCallback(async () => {
    const msg = input.trim();
    if (!msg || sending || !info) return;
    if (!info.venv_ready) { toast.error("Please initialize the assistant environment first"); return; }

    const history = messages
      .filter((m) => !m.error)
      .map((m) => ({ role: m.role, content: m.role === "assistant" ? answerText(m) : m.content }))
      .filter((h) => h.content.trim())
      .slice(-HISTORY_LIMIT);

    const userMsg: Msg = { id: uid(), role: "user", content: msg, blocks: [] };
    const asstId = uid();
    setMessages((prev) => [...prev, userMsg, { id: asstId, role: "assistant", content: "", blocks: [], streaming: true }]);
    setInput("");
    setDiff([]);
    setSending(true);

    try {
      await onBeforeTurn();
      const exc = await executionsApi.create(info.script_id, {
        message: msg,
        history,
        model: model || "default",
        reasoning,
        context: buildContext(),
      });
      setExecId(exc.id);
      openWs(exc.id, asstId);
    } catch (e) {
      setMessages((prev) => prev.map((m) => m.id === asstId ? { ...m, error: String(e), streaming: false } : m));
      setSending(false);
    }
  }, [input, sending, info, messages, model, reasoning, onBeforeTurn, buildContext, openWs]);

  const stop = useCallback(async () => {
    if (!execId) return;
    try { await executionsApi.stop(execId); } catch { /* ignore */ }
    wsRef.current?.close();
  }, [execId]);

  const doRevert = useCallback(async (filenames: string[]) => {
    setReverting(true);
    try {
      await onRevert(filenames);
      setDiff((prev) => prev.filter((d) => !filenames.includes(d.filename)));
      toast.success(filenames.length > 1 ? "Reverted this turn" : `Reverted ${filenames[0]}`);
    } catch (e) {
      toast.error(`Revert failed: ${e}`);
    } finally {
      setReverting(false);
    }
  }, [onRevert]);

  const selected = diff.find((d) => d.filename === diffFile) ?? diff[0];
  const cycleReasoning = () => setReasoning((r) => REASONING_LEVELS[(REASONING_LEVELS.indexOf(r as typeof REASONING_LEVELS[number]) + 1) % REASONING_LEVELS.length]);

  return (
    <div className="h-full flex flex-col bg-[#1e1e1e] text-foreground">
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-border shrink-0">
        <Sparkles className="h-4 w-4 text-primary" />
        <span className="text-sm font-medium">AI Assistant</span>
        <div className="ml-auto flex items-center gap-1">
          {messages.length > 0 && (
            <button title="Clear chat" onClick={() => { setMessages([]); setDiff([]); }} className="p-1 text-muted-foreground hover:text-foreground">
              <Eraser className="h-3.5 w-3.5" />
            </button>
          )}
          <button title="Collapse" onClick={onClose} className="p-1 text-muted-foreground hover:text-foreground">
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Body */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-3 py-3 space-y-4 min-h-0">
        {infoError && (
          <div className="text-xs text-destructive flex items-start gap-1.5">
            <AlertTriangle className="h-3.5 w-3.5 mt-0.5 shrink-0" />Failed to load assistant: {infoError}
          </div>
        )}

        {info && !info.venv_ready && (
          <div className="rounded-lg border border-amber-500/30 bg-amber-500/[0.06] p-3 text-xs space-y-2">
            <div className="flex items-center gap-1.5 font-medium text-amber-500">
              <PackagePlus className="h-3.5 w-3.5" />First-time setup
            </div>
            <p className="text-muted-foreground leading-relaxed">Installs baseline packages (langchain / langgraph, ~1–3 min, one time).</p>
            <Button size="sm" onClick={initVenv} disabled={venvBusy} className="h-7 text-xs">
              {venvBusy ? <Loader2 className="h-3 w-3 animate-spin" /> : <PackagePlus className="h-3 w-3" />}
              {venvBusy ? "Initializing…" : "Initialize environment"}
            </Button>
            {venvLines.length > 0 && (
              <pre className="mt-1 max-h-32 overflow-auto rounded bg-black/40 p-2 font-mono text-[10px] text-muted-foreground/80 whitespace-pre-wrap">{venvLines.join("\n")}</pre>
            )}
          </div>
        )}

        {info?.venv_ready && messages.length === 0 && (
          <div className="text-xs text-muted-foreground/70 leading-relaxed space-y-2 pt-2">
            <p>Let me write, edit and debug this <b className="text-foreground">{targetLabel}</b> with you. Try:</p>
            <ul className="space-y-1 pl-1">
              {targetLabel === "skill" ? (
                <>
                  <li>· “Make SKILL.md clear: when to use this skill and how”</li>
                  <li>· “Add references/examples.md with a few usage examples”</li>
                </>
              ) : (
                <>
                  <li>· “Add a `city` input, look up its weather via web_search, and return it”</li>
                  <li>· “This script is failing — find the bug and fix it”</li>
                  <li>· “Render the result as a table with markdown()”</li>
                </>
              )}
            </ul>
            <p className="text-muted-foreground/50">Changes are applied first, then you review or revert them in the diff below.</p>
          </div>
        )}

        {messages.map((m) => {
          if (m.role === "user") {
            return (
              <div key={m.id} className="flex justify-end">
                <div className="max-w-[85%] rounded-lg bg-primary/10 border border-primary/20 px-3 py-1.5 text-sm whitespace-pre-wrap break-words">{m.content}</div>
              </div>
            );
          }
          return (
            <div key={m.id} className="space-y-2">
              <AgentTimeline blocks={m.blocks} streaming={m.streaming} />
              {m.error && (
                <div className="text-xs text-destructive flex items-start gap-1.5">
                  <AlertTriangle className="h-3.5 w-3.5 mt-0.5 shrink-0" />{m.error}
                </div>
              )}
            </div>
          );
        })}

        {/* Post-turn diff review */}
        {diff.length > 0 && (
          <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/[0.05] p-3 text-xs space-y-2">
            <div className="flex items-center gap-1.5 font-medium text-emerald-500">
              <FileDiff className="h-3.5 w-3.5 shrink-0" />{diff.length} file{diff.length === 1 ? "" : "s"} changed this turn
            </div>
            <div className="space-y-1">
              {diff.map((d) => (
                <div key={d.filename} className="flex items-center gap-1.5">
                  <button onClick={() => onOpenFile(d.filename)} title="Open in editor"
                    className="font-mono text-[11px] px-2 py-0.5 rounded bg-background/60 border border-border/60 hover:border-border text-foreground/90 truncate flex-1 text-left">
                    {d.filename}
                  </button>
                  <button onClick={() => { setDiffFile(d.filename); setDiffOpen(true); }} title="View diff" className="p-1 text-muted-foreground hover:text-foreground">
                    <FileDiff className="h-3 w-3" />
                  </button>
                  <button onClick={() => doRevert([d.filename])} disabled={reverting} title="Revert this file" className="p-1 text-muted-foreground hover:text-destructive">
                    <RotateCcw className="h-3 w-3" />
                  </button>
                </div>
              ))}
            </div>
            <div className="flex items-center gap-2 pt-0.5">
              <Button size="sm" variant="ghost" className="h-7 text-xs text-muted-foreground hover:text-foreground" onClick={() => setDiff([])}>
                <Check className="h-3 w-3" />Accept all
              </Button>
              <Button size="sm" variant="ghost" className="h-7 text-xs text-destructive hover:text-destructive"
                onClick={() => doRevert(diff.map((d) => d.filename))} disabled={reverting}>
                {reverting ? <Loader2 className="h-3 w-3 animate-spin" /> : <RotateCcw className="h-3 w-3" />}Revert all
              </Button>
            </div>
          </div>
        )}
      </div>

      {/* Input + controls */}
      <div className="border-t border-border p-2 shrink-0 space-y-1.5">
        <div className="flex items-center gap-1.5">
          <select
            value={model}
            onChange={(e) => setModel(e.target.value)}
            title="Model"
            className="min-w-0 flex-1 h-6 rounded bg-secondary/40 border border-border/60 px-1.5 text-[11px] font-mono text-muted-foreground focus:outline-none"
          >
            {models.length === 0 && <option value="">Default model</option>}
            {models.map((mm) => <option key={mm} value={mm}>{mm}</option>)}
          </select>
          <button onClick={cycleReasoning} title="Thinking (chain-of-thought) level"
            className={cn("shrink-0 h-6 px-2 rounded border text-[11px] flex items-center gap-1",
              reasoning === "off" ? "border-border/60 text-muted-foreground" : "border-primary/40 text-primary bg-primary/10")}>
            <Brain className="h-3 w-3" />Think: {REASONING_LABEL[reasoning]}
          </button>
        </div>
        <div className="relative">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
            placeholder={info?.venv_ready ? `Ask the assistant to write / edit / debug this ${targetLabel}…  (Enter to send)` : "Initialize the environment to begin…"}
            disabled={!info?.venv_ready || sending}
            rows={2}
            className="w-full resize-none rounded-lg bg-secondary/30 border border-border/60 px-3 py-2 pr-11 text-sm focus:outline-none focus:border-primary/50 disabled:opacity-50 placeholder:text-muted-foreground/50"
          />
          {sending ? (
            <button onClick={stop} title="Stop" className="absolute right-2 bottom-2 p-1.5 rounded-md bg-destructive/90 text-destructive-foreground hover:bg-destructive">
              <Square className="h-3.5 w-3.5" />
            </button>
          ) : (
            <button onClick={send} disabled={!input.trim() || !info?.venv_ready} title="Send (Enter)"
              className="absolute right-2 bottom-2 p-1.5 rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-40">
              <Send className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* Diff modal */}
      <Dialog open={diffOpen} onOpenChange={setDiffOpen}>
        <DialogContent className="max-w-4xl w-[92vw]">
          <DialogHeader>
            <DialogTitle className="text-sm flex items-center gap-2"><FileDiff className="h-4 w-4" />This turn’s changes · before → after</DialogTitle>
          </DialogHeader>
          {diff.length > 1 && (
            <div className="flex flex-wrap gap-1.5">
              {diff.map((d) => (
                <button key={d.filename} onClick={() => setDiffFile(d.filename)}
                  className={cn("font-mono text-[11px] px-2 py-0.5 rounded border",
                    selected?.filename === d.filename ? "bg-primary/10 border-primary/40 text-primary" : "bg-secondary/30 border-border/60 text-muted-foreground hover:text-foreground")}>
                  {d.filename}
                </button>
              ))}
            </div>
          )}
          {selected && (
            <div className="h-[60vh] rounded-md overflow-hidden border border-border">
              <DiffEditor height="100%" theme="vs-dark" language={diffLang(selected.filename)}
                original={selected.before} modified={selected.after}
                options={{ readOnly: true, renderSideBySide: true, minimap: { enabled: false }, fontSize: 12 }} />
            </div>
          )}
          {selected && (
            <div className="flex justify-end gap-2 pt-1">
              <Button variant="ghost" size="sm" className="text-destructive hover:text-destructive" onClick={() => doRevert([selected.filename])} disabled={reverting}>
                {reverting ? <Loader2 className="h-3 w-3 animate-spin" /> : <RotateCcw className="h-3 w-3" />}Revert this file
              </Button>
              <Button size="sm" onClick={() => setDiffOpen(false)}><Check className="h-3 w-3" />Close</Button>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
