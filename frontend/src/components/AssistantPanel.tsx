"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import {
  Sparkles, Send, Square, Loader2, X, RotateCcw, FileDiff, Check,
  AlertTriangle, PackagePlus, Eraser, Brain, Plus, History, Trash2,
} from "lucide-react";
import { toast } from "sonner";
import { DiffEditor } from "@monaco-editor/react";
import {
  assistant as assistantApi, executions as executionsApi, channels as channelsApi,
} from "@/lib/api";
import type { Channel, WsEvent } from "@/lib/types";
import type { ChangedFile } from "@/components/assistant/AssistantProvider";
import AgentTimeline, {
  reduceEvent, answerFromBlocks, type Block,
} from "@/components/AgentTimeline";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";

export type { ChangedFile };

interface Msg {
  id: string;
  role: "user" | "assistant";
  content: string;        // user text; assistant non-streaming fallback
  blocks: Block[];        // assistant chronological timeline
  error?: string;
  streaming?: boolean;
}

interface Props {
  /** "bound" = editing a specific script/skill (diff + revert); "global" = free-floating (create/edit anything, no diff). */
  mode: "bound" | "global";
  /** Bound-only: which kind + a display label + stable id (id gates cross-target diff). */
  boundKind?: "script" | "skill";
  boundLabel?: string;
  boundId?: string;
  /** Full context object handed to the assistant each turn. */
  buildContext: () => Record<string, unknown>;
  /** Bound-only lifecycle hooks (absent in global mode → the diff/revert flow is skipped). */
  onBeforeTurn?: () => Promise<void>;
  onAfterTurn?: () => Promise<ChangedFile[]>;
  onRevert?: (filenames: string[]) => Promise<void>;
  onOpenFile?: (filename: string) => void;
  /** Collapse the widget back to its bubble. */
  onClose: () => void;
  /** Report streaming state up so the collapsed bubble can show activity. */
  onBusyChange?: (busy: boolean) => void;
}

const HISTORY_LIMIT = 16;
const HISTORY_STORAGE_LIMIT = 60;
const MAX_SESSIONS = 20;
const REASONING_LEVELS = ["off", "low", "medium", "high"] as const;
const DEFAULT_MODEL_VALUE = "__agentflow_default_model__";

/** One archived chat thread for the current target (see the History dialog). */
interface Session { id: string; title: string; updatedAt: number; messages: Msg[]; }

function sessionTitle(msgs: Msg[], t: TFunction): string {
  const text = (msgs.find((m) => m.role === "user")?.content || "").trim().replace(/\s+/g, " ");
  if (!text) return t("assistantPanel.newChat");
  return text.length > 48 ? `${text.slice(0, 48)}…` : text;
}

function relativeTime(ts: number, t: TFunction): string {
  const min = Math.round((Date.now() - ts) / 60000);
  if (min < 1) return t("assistantPanel.relativeTime.justNow");
  if (min < 60) return t("assistantPanel.relativeTime.minutesAgo", { count: min });
  const hr = Math.round(min / 60);
  if (hr < 24) return t("assistantPanel.relativeTime.hoursAgo", { count: hr });
  return t("assistantPanel.relativeTime.daysAgo", { count: Math.round(hr / 24) });
}

interface ModelGroup {
  provider: string;
  models: string[];
}

function uid() { return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`; }

function providerLabel(provider: string): string {
  const clean = (provider || "provider").replace(/[-_]+/g, " ").trim();
  return clean ? clean.replace(/\b\w/g, (c) => c.toUpperCase()) : "Provider";
}

function groupModelsByProvider(channels: Channel[]): ModelGroup[] {
  const groups = new Map<string, string[]>();
  const seen = new Set<string>();
  for (const ch of channels) {
    const provider = ch.provider || "provider";
    for (const model of ch.models ?? []) {
      if (!model || seen.has(model)) continue;
      seen.add(model);
      groups.set(provider, [...(groups.get(provider) ?? []), model]);
    }
  }
  return Array.from(groups, ([provider, models]) => ({ provider, models }));
}

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
  mode, boundKind, boundLabel, boundId,
  buildContext, onBeforeTurn, onAfterTurn, onRevert, onOpenFile, onClose, onBusyChange,
}: Props) {
  const { t } = useTranslation("assistant");
  const [info, setInfo] = useState<{ script_id: string; venv_ready: boolean } | null>(null);
  const [infoError, setInfoError] = useState<string | null>(null);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [execId, setExecId] = useState<string | null>(null);

  // model + reasoning
  const [modelGroups, setModelGroups] = useState<ModelGroup[]>([]);
  const [model, setModel] = useState<string>("");
  const [reasoning, setReasoning] = useState<string>("off");

  // post-turn diff review (bound mode only). diffForId gates it to the target
  // the turn actually ran against, so a diff never shows on a different page.
  const [diff, setDiff] = useState<ChangedFile[]>([]);
  const [diffForId, setDiffForId] = useState<string | null>(null);
  const [diffOpen, setDiffOpen] = useState(false);
  const [diffFile, setDiffFile] = useState<string | null>(null);
  const [reverting, setReverting] = useState(false);
  const turnBoundIdRef = useRef<string | null>(null);

  // Archived past chats for the current target, browsable via the History dialog.
  const [sessions, setSessions] = useState<Session[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);

  // first-run venv setup
  const [venvBusy, setVenvBusy] = useState(false);
  const [venvLines, setVenvLines] = useState<string[]>([]);

  const wsRef = useRef<WebSocket | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  // Mirrors the streaming assistant message's blocks, so finalize() can check
  // whether a visible answer actually arrived without waiting on React state.
  const liveBlocksRef = useRef<Block[]>([]);
  // Whether the message list should auto-scroll to bottom on new content. Turns
  // false the moment the user scrolls away from the bottom, and true again once
  // they scroll back down — so reading scrollback never gets yanked away.
  const stickToBottomRef = useRef(true);

  // Per-target chat history key: separate threads per bound script/skill, one
  // shared thread while unbound (global mode).
  const historyKey = mode === "bound" && boundId ? `${boundKind}:${boundId}` : "global";

  useEffect(() => {
    assistantApi.info().then(setInfo).catch((e) => setInfoError(String(e)));
    channelsApi.list().then((chs) => {
      const enabled = chs.filter((c) => c.enabled);
      const groups = groupModelsByProvider(enabled);
      const list = groups.flatMap((g) => g.models);
      const def = enabled.find((c) => c.is_default)?.default_model || list[0] || "";
      setModelGroups(groups);
      setModel(def);
    }).catch(() => { /* model list is best-effort; falls back to default */ });
  }, []);

  useEffect(() => {
    if (stickToBottomRef.current) {
      scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
    }
  }, [messages, diff]);

  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    stickToBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
  }, []);

  useEffect(() => () => { wsRef.current?.close(); }, []);

  // Report streaming state to the shell on transitions (for the bubble's pulse).
  const prevSendingRef = useRef(false);
  useEffect(() => {
    if (prevSendingRef.current !== sending) {
      prevSendingRef.current = sending;
      onBusyChange?.(sending);
    }
  }, [sending, onBusyChange]);

  // Switching bound target (navigating between pages) drops any stale diff and
  // loads that target's persisted chat + archived sessions (see the save effects below).
  useEffect(() => {
    setDiff([]);
    setDiffForId(null);
    stickToBottomRef.current = true;
    let restored: Msg[] = [];
    try {
      const raw = localStorage.getItem(`ag.assistantHistory.${historyKey}`);
      const parsed = raw ? JSON.parse(raw) : [];
      if (Array.isArray(parsed)) restored = parsed.map((m: Msg) => ({ ...m, streaming: false }));
    } catch { /* corrupt/unavailable storage — start fresh */ }
    setMessages(restored);
    let restoredSessions: Session[] = [];
    try {
      const raw = localStorage.getItem(`ag.assistantSessions.${historyKey}`);
      const parsed = raw ? JSON.parse(raw) : [];
      if (Array.isArray(parsed)) restoredSessions = parsed;
    } catch { /* corrupt/unavailable storage — start fresh */ }
    setSessions(restoredSessions);
  }, [historyKey]);

  // Persist the current target's chat history / archived sessions on every change.
  useEffect(() => {
    try {
      localStorage.setItem(`ag.assistantHistory.${historyKey}`, JSON.stringify(messages.slice(-HISTORY_STORAGE_LIMIT)));
    } catch { /* storage full/unavailable — best effort */ }
  }, [messages, historyKey]);

  useEffect(() => {
    try {
      localStorage.setItem(`ag.assistantSessions.${historyKey}`, JSON.stringify(sessions.slice(0, MAX_SESSIONS)));
    } catch { /* storage full/unavailable — best effort */ }
  }, [sessions, historyKey]);

  // Start a fresh thread for this target, archiving the current one (if any).
  const newChat = useCallback(() => {
    if (sending || messages.length === 0) return;
    const snapshot = messages.slice(-HISTORY_STORAGE_LIMIT);
    setSessions((prev) => [{ id: uid(), title: sessionTitle(snapshot, t), updatedAt: Date.now(), messages: snapshot }, ...prev].slice(0, MAX_SESSIONS));
    setMessages([]);
    setDiff([]);
    setDiffForId(null);
  }, [sending, messages, t]);

  // Swap in an archived session as the current thread, archiving the outgoing one first.
  const openSession = useCallback((session: Session) => {
    if (sending) return;
    setSessions((prev) => {
      let next = prev.filter((s) => s.id !== session.id);
      if (messages.length > 0) {
        const snapshot = messages.slice(-HISTORY_STORAGE_LIMIT);
        next = [{ id: uid(), title: sessionTitle(snapshot, t), updatedAt: Date.now(), messages: snapshot }, ...next];
      }
      return next.slice(0, MAX_SESSIONS);
    });
    setMessages(session.messages.map((m) => ({ ...m, streaming: false })));
    setDiff([]);
    setDiffForId(null);
    setHistoryOpen(false);
  }, [sending, messages, t]);

  const deleteSession = useCallback((id: string) => {
    setSessions((prev) => prev.filter((s) => s.id !== id));
  }, []);

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
      if (evt.type === "error") { toast.error(evt.message || t("assistantPanel.toast.initializationFailed")); return; }
      if (evt.text) setVenvLines((prev) => [...prev.slice(-80), evt.text!]);
      if (evt.done) {
        ws.close();
        setVenvBusy(false);
        const ok = evt.text === "DONE" || !(evt.text || "").startsWith("ERROR:");
        if (ok) { setInfo((p) => p ? { ...p, venv_ready: true } : p); toast.success(t("assistantPanel.toast.envReady")); }
        else toast.error(t("assistantPanel.toast.envSetupFailed"));
      }
    };
    ws.onerror = () => { setVenvBusy(false); toast.error(t("assistantPanel.toast.envConnectionFailed")); };
  }, [info, venvBusy, t]);

  // ── turn lifecycle ──────────────────────────────────────────────────────────
  // A turn can stream reasoning (<think>…</think>) and still end with no visible
  // answer — e.g. a reasoning model that runs out of output length while still
  // "thinking". Trusting "some token arrived" isn't enough; check whether the
  // streamed blocks actually contain a non-empty answer before skipping the
  // authoritative-reply fetch, so the user is never left staring at silence.
  const finalize = useCallback(async (asstId: string, executionId: string) => {
    const hasAnswer = answerFromBlocks(liveBlocksRef.current).trim().length > 0;
    if (!hasAnswer) {
      try {
        const exc = await executionsApi.get(executionId);
        const reply = ((): string => {
          const od = exc.output_data as unknown;
          if (od && typeof od === "object" && "reply" in od) return String((od as Record<string, unknown>).reply ?? "");
          if (typeof od === "string") return od;
          return "";
        })();
        setMessages((prev) => prev.map((m) => {
          if (m.id !== asstId) return m;
          if (reply.trim()) {
            // Keep any reasoning we already rendered; append the authoritative answer.
            return { ...m, blocks: [...m.blocks, { type: "text", content: reply }], error: exc.error ?? m.error, streaming: false };
          }
          return {
            ...m,
            error: exc.error ?? m.error ?? (m.blocks.length
              ? t("assistantPanel.error.noAnswer")
              : undefined),
            streaming: false,
          };
        }));
      } catch {
        setMessages((prev) => prev.map((m) => m.id === asstId ? { ...m, streaming: false } : m));
      }
    } else {
      setMessages((prev) => prev.map((m) => m.id === asstId ? { ...m, streaming: false } : m));
    }
    // Bound mode: diff the turn's changes against the pre-turn baseline. The
    // captured turnBoundIdRef keeps this correct even if the user navigated
    // away mid-turn (the diff then simply won't render for the new page).
    try {
      const changed = (await onAfterTurn?.()) ?? [];
      if (changed.length) {
        setDiff(changed);
        setDiffFile(changed[0].filename);
        setDiffForId(turnBoundIdRef.current);
      }
    } catch { /* editor refetch best-effort */ }
    setSending(false);
    setExecId(null);
  }, [onAfterTurn, t]);

  const openWs = useCallback((executionId: string, asstId: string) => {
    liveBlocksRef.current = [];
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${window.location.host}/ws/executions/${executionId}`);
    wsRef.current = ws;
    ws.onmessage = (e) => {
      let evt: WsEvent;
      try { evt = JSON.parse(e.data); } catch { return; }
      if (evt.type === "token" || evt.type === "trace") {
        setMessages((prev) => prev.map((m) => {
          if (m.id !== asstId) return m;
          const blocks = reduceEvent(m.blocks, evt);
          liveBlocksRef.current = blocks;
          return { ...m, blocks, streaming: true };
        }));
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
      setMessages((prev) => prev.map((m) => m.id === asstId ? { ...m, error: t("assistantPanel.error.wsError"), streaming: false } : m));
      setSending(false);
      setExecId(null);
    };
  }, [finalize, t]);

  const send = useCallback(async () => {
    const msg = input.trim();
    if (!msg || sending || !info) return;
    if (!info.venv_ready) { toast.error(t("assistantPanel.toast.initEnvFirst")); return; }

    const history = messages
      .filter((m) => !m.error)
      .map((m) => ({ role: m.role, content: m.role === "assistant" ? answerText(m) : m.content }))
      .filter((h) => h.content.trim())
      .slice(-HISTORY_LIMIT);

    const userMsg: Msg = { id: uid(), role: "user", content: msg, blocks: [] };
    const asstId = uid();
    stickToBottomRef.current = true;   // sending a message always jumps the view to it
    setMessages((prev) => [...prev, userMsg, { id: asstId, role: "assistant", content: "", blocks: [], streaming: true }]);
    setInput("");
    setDiff([]);
    setDiffForId(null);
    turnBoundIdRef.current = boundId ?? null;   // snapshot the target for this turn
    setSending(true);

    try {
      await onBeforeTurn?.();
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
  }, [input, sending, info, messages, model, reasoning, boundId, onBeforeTurn, buildContext, openWs, t]);

  const stop = useCallback(async () => {
    if (!execId) return;
    try { await executionsApi.stop(execId); } catch { /* ignore */ }
    wsRef.current?.close();
  }, [execId]);

  const doRevert = useCallback(async (filenames: string[]) => {
    setReverting(true);
    try {
      await onRevert?.(filenames);
      setDiff((prev) => prev.filter((d) => !filenames.includes(d.filename)));
      toast.success(filenames.length > 1
        ? t("assistantPanel.toast.revertedTurn")
        : t("assistantPanel.toast.revertedFile", { filename: filenames[0] }));
    } catch (e) {
      toast.error(t("assistantPanel.toast.revertFailed", { error: String(e) }));
    } finally {
      setReverting(false);
    }
  }, [onRevert, t]);

  const selected = diff.find((d) => d.filename === diffFile) ?? diff[0];
  const cycleReasoning = () => setReasoning((r) => REASONING_LEVELS[(REASONING_LEVELS.indexOf(r as typeof REASONING_LEVELS[number]) + 1) % REASONING_LEVELS.length]);
  // Only show the diff card for the target the turn ran against.
  const showDiff = mode === "bound" && diff.length > 0 && diffForId === (boundId ?? null);

  return (
    <div className="h-full flex flex-col bg-[#1e1e1e] text-foreground">
      {/* Header — context-aware (bound target vs global) */}
      <div className="flex items-center gap-2 pl-5 pr-3 py-2 border-b border-border shrink-0">
        <Sparkles className="h-4 w-4 text-primary shrink-0" />
        <div className="min-w-0 leading-tight">
          <div className="text-sm font-medium">{t("assistantPanel.header.title")}</div>
          <div className="text-[10px] text-muted-foreground truncate">
            {mode === "bound"
              ? <>{t("assistantPanel.header.editing")} · <span className="text-foreground/80">{boundLabel || t(`assistantPanel.kind.${boundKind ?? "script"}`)}</span> · {t(`assistantPanel.kind.${boundKind ?? "script"}`)}</>
              : t("assistantPanel.header.global")}
          </div>
        </div>
        <div className="ml-auto flex items-center gap-1 shrink-0">
          {sessions.length > 0 && (
            <button title={t("assistantPanel.title.chatHistory")} onClick={() => setHistoryOpen(true)} className="p-1 text-muted-foreground hover:text-foreground">
              <History className="h-3.5 w-3.5" />
            </button>
          )}
          {messages.length > 0 && (
            <button title={t("assistantPanel.newChat")} onClick={newChat} className="p-1 text-muted-foreground hover:text-foreground">
              <Plus className="h-3.5 w-3.5" />
            </button>
          )}
          {messages.length > 0 && (
            <button title={t("assistantPanel.title.clearChat")} onClick={() => { setMessages([]); setDiff([]); setDiffForId(null); }} className="p-1 text-muted-foreground hover:text-foreground">
              <Eraser className="h-3.5 w-3.5" />
            </button>
          )}
          <button title={t("assistantPanel.title.collapse")} onClick={onClose} className="p-1 text-muted-foreground hover:text-foreground">
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Body */}
      <div ref={scrollRef} onScroll={handleScroll} className="flex-1 overflow-y-auto px-3 py-3 space-y-4 min-h-0">
        {infoError && (
          <div className="text-xs text-destructive flex items-start gap-1.5">
            <AlertTriangle className="h-3.5 w-3.5 mt-0.5 shrink-0" />{t("assistantPanel.error.loadFailed", { error: infoError })}
          </div>
        )}

        {info && !info.venv_ready && (
          <div className="rounded-lg border border-amber-500/30 bg-amber-500/[0.06] p-3 text-xs space-y-2">
            <div className="flex items-center gap-1.5 font-medium text-amber-500">
              <PackagePlus className="h-3.5 w-3.5" />{t("assistantPanel.setup.title")}
            </div>
            <p className="text-muted-foreground leading-relaxed">{t("assistantPanel.setup.description")}</p>
            <Button size="sm" onClick={initVenv} disabled={venvBusy} className="h-7 text-xs">
              {venvBusy ? <Loader2 className="h-3 w-3 animate-spin" /> : <PackagePlus className="h-3 w-3" />}
              {venvBusy ? t("assistantPanel.setup.initializing") : t("assistantPanel.setup.initialize")}
            </Button>
            {venvLines.length > 0 && (
              <pre className="mt-1 max-h-32 overflow-auto rounded bg-black/40 p-2 font-mono text-[10px] text-muted-foreground/80 whitespace-pre-wrap">{venvLines.join("\n")}</pre>
            )}
          </div>
        )}

        {info?.venv_ready && messages.length === 0 && (
          <div className="text-xs text-muted-foreground/70 leading-relaxed space-y-2 pt-2">
            {mode === "global" ? (
              <>
                <p>{t("assistantPanel.empty.global.prefix")}<b className="text-foreground">{t("assistantPanel.empty.global.notBound")}</b>{t("assistantPanel.empty.global.suffix")}</p>
                <ul className="space-y-1 pl-1">
                  <li>· {t("assistantPanel.empty.global.example1")}</li>
                  <li>· {t("assistantPanel.empty.global.example2")}</li>
                </ul>
                <p className="text-muted-foreground/50">{t("assistantPanel.empty.global.hint")}</p>
              </>
            ) : (
              <>
                <p>{t("assistantPanel.empty.bound.prefix")}<b className="text-foreground">{t(`assistantPanel.kind.${boundKind ?? "script"}`)}</b>{t("assistantPanel.empty.bound.suffix")}</p>
                <ul className="space-y-1 pl-1">
                  {boundKind === "skill" ? (
                    <>
                      <li>· {t("assistantPanel.empty.bound.skillExample1")}</li>
                      <li>· {t("assistantPanel.empty.bound.skillExample2")}</li>
                    </>
                  ) : (
                    <>
                      <li>· {t("assistantPanel.empty.bound.scriptExample1")}</li>
                      <li>· {t("assistantPanel.empty.bound.scriptExample2")}</li>
                      <li>· {t("assistantPanel.empty.bound.scriptExample3")}</li>
                    </>
                  )}
                </ul>
                <p className="text-muted-foreground/50">{t("assistantPanel.empty.bound.hint")}</p>
              </>
            )}
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

        {/* Post-turn diff review (bound mode, matching target) */}
        {showDiff && (
          <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/[0.05] p-3 text-xs space-y-2">
            <div className="flex items-center gap-1.5 font-medium text-emerald-500">
              <FileDiff className="h-3.5 w-3.5 shrink-0" />{t("assistantPanel.diff.filesChanged", { count: diff.length })}
            </div>
            <div className="space-y-1">
              {diff.map((d) => (
                <div key={d.filename} className="flex items-center gap-1.5">
                  <button onClick={() => onOpenFile?.(d.filename)} title={t("assistantPanel.diff.openInEditor")}
                    className="font-mono text-[11px] px-2 py-0.5 rounded bg-background/60 border border-border/60 hover:border-border text-foreground/90 truncate flex-1 text-left">
                    {d.filename}
                  </button>
                  <button onClick={() => { setDiffFile(d.filename); setDiffOpen(true); }} title={t("assistantPanel.diff.viewDiff")} className="p-1 text-muted-foreground hover:text-foreground">
                    <FileDiff className="h-3 w-3" />
                  </button>
                  <button onClick={() => doRevert([d.filename])} disabled={reverting} title={t("assistantPanel.diff.revertFile")} className="p-1 text-muted-foreground hover:text-destructive">
                    <RotateCcw className="h-3 w-3" />
                  </button>
                </div>
              ))}
            </div>
            <div className="flex items-center gap-2 pt-0.5">
              <Button size="sm" variant="ghost" className="h-7 text-xs text-muted-foreground hover:text-foreground" onClick={() => { setDiff([]); setDiffForId(null); }}>
                <Check className="h-3 w-3" />{t("assistantPanel.diff.acceptAll")}
              </Button>
              <Button size="sm" variant="ghost" className="h-7 text-xs text-destructive hover:text-destructive"
                onClick={() => doRevert(diff.map((d) => d.filename))} disabled={reverting}>
                {reverting ? <Loader2 className="h-3 w-3 animate-spin" /> : <RotateCcw className="h-3 w-3" />}{t("assistantPanel.diff.revertAll")}
              </Button>
            </div>
          </div>
        )}
      </div>

      {/* Input + controls */}
      <div className="border-t border-border p-2 shrink-0 space-y-1.5">
        <div className="flex items-center gap-1.5">
          <Select
            value={model || DEFAULT_MODEL_VALUE}
            onValueChange={(v) => setModel(v === DEFAULT_MODEL_VALUE ? "" : v)}
          >
            <SelectTrigger
              title={t("assistantPanel.input.modelTitle")}
              className="min-w-0 flex-1 h-7 rounded-md bg-background/50 border-border/70 px-2 text-[11px] font-mono text-foreground/80 shadow-none hover:bg-muted/40 focus:ring-0 focus:border-primary/45 [&>span]:truncate"
            >
              <SelectValue placeholder={t("assistantPanel.input.defaultModel")} />
            </SelectTrigger>
            <SelectContent align="start" className="max-h-72 w-[var(--radix-select-trigger-width)] bg-popover border-border/70">
              <SelectItem value={DEFAULT_MODEL_VALUE} className="text-xs text-muted-foreground">
                {t("assistantPanel.input.defaultModel")}
              </SelectItem>
              {modelGroups.map((group) => (
                <SelectGroup key={group.provider}>
                  <SelectLabel className="px-2 py-1.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground/70">
                    {providerLabel(group.provider)}
                  </SelectLabel>
                  {group.models.map((mm) => (
                    <SelectItem
                      key={`${group.provider}:${mm}`}
                      value={mm}
                      className="pl-7 pr-2 text-xs font-mono text-foreground/85 focus:bg-muted/70 focus:text-foreground truncate"
                    >
                      {mm}
                    </SelectItem>
                  ))}
                </SelectGroup>
              ))}
            </SelectContent>
          </Select>
          <button onClick={cycleReasoning} title={t("assistantPanel.input.thinkingLevelTitle")}
            className={cn("shrink-0 h-7 px-2 rounded-md border text-[11px] flex items-center gap-1",
              reasoning === "off" ? "border-border/60 text-muted-foreground" : "border-primary/40 text-primary bg-primary/10")}>
            <Brain className="h-3 w-3" />{t("assistantPanel.input.think", { level: t(`assistantPanel.reasoning.${reasoning}`) })}
          </button>
        </div>
        <div className="relative">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
            placeholder={info?.venv_ready
              ? (mode === "global"
                  ? t("assistantPanel.input.placeholderGlobal")
                  : t("assistantPanel.input.placeholderBound", { kind: t(`assistantPanel.kind.${boundKind ?? "script"}`) }))
              : t("assistantPanel.input.placeholderNotReady")}
            disabled={!info?.venv_ready || sending}
            rows={2}
            className="w-full resize-none rounded-lg bg-secondary/30 border border-border/60 px-3 py-2 pr-11 text-sm focus:outline-none focus:border-primary/50 disabled:opacity-50 placeholder:text-muted-foreground/50"
          />
          {sending ? (
            <button onClick={stop} title={t("assistantPanel.input.stop")} className="absolute right-2 bottom-2 p-1.5 rounded-md bg-destructive/90 text-destructive-foreground hover:bg-destructive">
              <Square className="h-3.5 w-3.5" />
            </button>
          ) : (
            <button onClick={send} disabled={!input.trim() || !info?.venv_ready} title={t("assistantPanel.input.send")}
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
            <DialogTitle className="text-sm flex items-center gap-2"><FileDiff className="h-4 w-4" />{t("assistantPanel.diff.dialogTitle")}</DialogTitle>
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
                {reverting ? <Loader2 className="h-3 w-3 animate-spin" /> : <RotateCcw className="h-3 w-3" />}{t("assistantPanel.diff.revertFile")}
              </Button>
              <Button size="sm" onClick={() => setDiffOpen(false)}><Check className="h-3 w-3" />{t("assistantPanel.diff.close")}</Button>
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* Chat history: past threads for this target, reopen or delete */}
      <Dialog open={historyOpen} onOpenChange={setHistoryOpen}>
        <DialogContent className="max-w-sm w-[90vw]">
          <DialogHeader>
            <DialogTitle className="text-sm flex items-center gap-2"><History className="h-4 w-4" />{t("assistantPanel.title.chatHistory")}</DialogTitle>
          </DialogHeader>
          {sessions.length === 0 ? (
            <p className="text-xs text-muted-foreground py-4 text-center">{t("assistantPanel.history.empty")}</p>
          ) : (
            <div className="max-h-80 overflow-y-auto space-y-1">
              {sessions.map((s) => (
                <div key={s.id} className="flex items-center gap-2 rounded-md border border-border/50 px-2.5 py-1.5 hover:border-border">
                  <button onClick={() => openSession(s)} className="min-w-0 flex-1 text-left">
                    <div className="text-xs text-foreground/90 truncate">{s.title}</div>
                    <div className="text-[10px] text-muted-foreground/60">{relativeTime(s.updatedAt, t)}</div>
                  </button>
                  <button onClick={() => deleteSession(s.id)} title={t("assistantPanel.history.delete")} className="p-1 text-muted-foreground hover:text-destructive shrink-0">
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
