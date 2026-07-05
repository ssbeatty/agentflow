"use client";
import { Suspense, useEffect, useRef, useState, useCallback } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  ArrowLeft, Send, Loader2, MessageSquare, Trash2, Bot,
  Plus, Settings2, ExternalLink, ChevronDown, ChevronUp, ChevronRight, Link2, Check,
  Copy, Square, Search, ArrowDown, PanelLeftClose, PanelLeftOpen, Brain,
} from "lucide-react";
import { toast } from "sonner";
import {
  scripts as scriptsApi, conversations as convsApi, executions as executionsApi,
} from "@/lib/api";
import type { ScriptSummary, ConversationSummary, ArtifactEvent, ExecutionLog, TraceEvent, WsEvent } from "@/lib/types";
import { ArtifactCard } from "@/components/ArtifactsPanel";
import AgentNarrative from "@/components/AgentNarrative";
import { MarkdownContent } from "@/components/Markdown";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";

// ── Typewriter ────────────────────────────────────────────────────────────────

function TypewriterText({ text, onDone }: { text: string; onDone: () => void }) {
  const [displayed, setDisplayed] = useState("");
  useEffect(() => {
    let i = 0;
    setDisplayed("");
    const id = setInterval(() => {
      i++;
      setDisplayed(text.slice(0, i));
      if (i >= text.length) {
        clearInterval(id);
        onDone();
      }
    }, 12);
    return () => clearInterval(id);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text]);
  return <MarkdownContent text={displayed} />;
}

// ── Reasoning (chain-of-thought) ──────────────────────────────────────────────

// Split a reasoning model's chain-of-thought (<think>…</think>, some models emit
// <thinking>) out of the visible answer. Without this, react-markdown silently
// drops the unknown <think> HTML tag AND its contents, so the thinking is invisible.
//
// Deliberately tolerant of how a script emits the tags, because that correctness
// must NOT be each script's burden to get right — the platform owns it here:
//   • one block  <think>…all reasoning…</think>answer   (the clean form)
//   • per chunk  <think>a</think><think>b</think>answer  (naive streaming loop —
//     reasoning_content arrives token-by-token; a script that wraps each chunk
//     individually is stitched back into one block instead of showing only "a")
//   • unclosed   <think>partial            (still streaming → thinking:true)
// Every <think> block's contents are concatenated into one reasoning string; all
// non-think text is the answer.
function splitThink(content: string): { reasoning: string; answer: string; thinking: boolean } {
  const openRe = /<think(?:ing)?>/gi;
  const reasoningParts: string[] = [];
  let answer = "";
  let thinking = false;
  let cursor = 0;
  while (cursor < content.length) {
    openRe.lastIndex = cursor;
    const om = openRe.exec(content);
    if (!om) {
      answer += content.slice(cursor);
      break;
    }
    answer += content.slice(cursor, om.index); // text before this block is answer
    const afterOpen = om.index + om[0].length;
    const cm = content.slice(afterOpen).match(/<\/think(?:ing)?>/i);
    if (!cm || cm.index === undefined) {
      // Open tag with no close yet → the rest is reasoning, still streaming.
      reasoningParts.push(content.slice(afterOpen));
      thinking = true;
      break;
    }
    reasoningParts.push(content.slice(afterOpen, afterOpen + cm.index));
    cursor = afterOpen + cm.index + cm[0].length;
  }
  const reasoning = reasoningParts.join("");
  return { reasoning: thinking ? reasoning : reasoning.trim(), answer: answer.trim(), thinking };
}

// Collapsible "thought process" block shown above an assistant answer. Auto-
// expands while the model is actively thinking, then collapses (unless the user
// toggled it) once the answer starts.
function ThinkBlock({ reasoning, thinking }: { reasoning: string; thinking: boolean }) {
  const [userOpen, setUserOpen] = useState<boolean | null>(null);
  const open = userOpen ?? thinking;
  if (!reasoning.trim()) return null;
  return (
    <div className="w-full max-w-[680px] rounded-xl border border-border/50 bg-secondary/10 overflow-hidden">
      <button
        onClick={() => setUserOpen(!open)}
        className="w-full flex items-center gap-1.5 px-3 py-2 text-[11px] hover:bg-secondary/20 transition-colors"
      >
        {thinking
          ? <Loader2 className="h-3.5 w-3.5 text-blue-400 animate-spin" />
          : <Brain className="h-3.5 w-3.5 text-primary/70" />}
        <span className="font-medium text-foreground/80">{thinking ? "Thinking…" : "Thought process"}</span>
        {open
          ? <ChevronDown className="h-3.5 w-3.5 ml-auto text-muted-foreground" />
          : <ChevronRight className="h-3.5 w-3.5 ml-auto text-muted-foreground" />}
      </button>
      {open && (
        <div className="px-3 pb-2.5 pt-1 border-t border-border/40 text-xs text-muted-foreground/90 whitespace-pre-wrap break-words max-h-72 overflow-auto leading-relaxed">
          {reasoning}
        </div>
      )}
    </div>
  );
}

// ── Log strip ─────────────────────────────────────────────────────────────────

const LEVEL_COLORS: Record<string, string> = {
  info: "text-muted-foreground",
  debug: "text-muted-foreground/60",
  warning: "text-yellow-500",
  error: "text-destructive",
  raw: "text-muted-foreground/70",
};

function LogStrip({ logs }: { logs: WsEvent[] }) {
  const [open, setOpen] = useState(false);
  const logEvents = logs.filter((e): e is Extract<WsEvent, { type: "log" }> => e.type === "log");
  if (logEvents.length === 0) return null;
  return (
    <div className="w-full max-w-[680px]">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1 text-[10px] text-muted-foreground/70 hover:text-foreground"
      >
        {open ? <ChevronDown className="h-3 w-3" /> : <ChevronUp className="h-3 w-3" />}
        {logEvents.length} log{logEvents.length === 1 ? "" : "s"}
      </button>
      {open && (
        <div className="mt-1 rounded-lg border border-border/50 bg-muted/30 p-2 space-y-0.5 max-h-40 overflow-y-auto">
          {logEvents.map((e, i) => (
            <div key={i} className={`text-[11px] font-mono ${LEVEL_COLORS[e.level] ?? "text-muted-foreground"}`}>
              {e.step && <span className="mr-1 opacity-60">[{e.step}]</span>}
              {e.message}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Message row (Open WebUI style) ────────────────────────────────────────────

interface UiMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  error?: string;
  streaming?: boolean;   // actively receiving tokens
  animating?: boolean;   // playing typewriter after confirm
  logs?: WsEvent[];
  artifacts?: ArtifactEvent[];
  traces?: TraceEvent[]; // agent internals: tool calls, LLM turns, graph nodes
  execution_id?: string;
}

function ActionButton({
  onClick, title, danger, children,
}: { onClick: () => void; title: string; danger?: boolean; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      title={title}
      className={`p-1 rounded text-muted-foreground/50 hover:bg-muted/60 transition-colors ${
        danger ? "hover:text-destructive" : "hover:text-foreground"
      }`}
    >
      {children}
    </button>
  );
}

function MessageRow({
  msg,
  onAnimDone,
  onDelete,
}: {
  msg: UiMessage;
  onAnimDone?: () => void;
  onDelete?: () => void;
}) {
  const isUser = msg.role === "user";
  const { reasoning, answer, thinking } = isUser
    ? { reasoning: "", answer: msg.content, thinking: false }
    : splitThink(msg.content);
  const [copied, setCopied] = useState(false);
  const canDelete = onDelete && !msg.streaming && !msg.animating && !msg.id.startsWith("tmp-");
  const showActions = !msg.streaming && !msg.animating && !msg.error;

  function copy() {
    navigator.clipboard.writeText(answer).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }

  const actions = (
    <div className={`flex gap-0.5 ${isUser ? "justify-end pr-1" : ""} opacity-0 group-hover:opacity-100 transition-opacity`}>
      {showActions && answer && (
        <ActionButton onClick={copy} title="Copy">
          {copied ? <Check className="h-3.5 w-3.5 text-green-500" /> : <Copy className="h-3.5 w-3.5" />}
        </ActionButton>
      )}
      {canDelete && (
        <ActionButton onClick={onDelete!} title="Delete" danger>
          <Trash2 className="h-3.5 w-3.5" />
        </ActionButton>
      )}
    </div>
  );

  // User → right-aligned soft bubble
  if (isUser) {
    return (
      <div className="group flex flex-col items-end gap-1">
        <div className="rounded-2xl rounded-br-md bg-primary/15 text-foreground px-4 py-2.5 text-sm whitespace-pre-wrap break-words max-w-[85%]">
          {msg.content}
        </div>
        {actions}
      </div>
    );
  }

  // Assistant → flat full-width, avatar on the left, trace above the answer
  return (
    <div className="group flex gap-3">
      <div className="h-7 w-7 rounded-full bg-secondary text-foreground flex items-center justify-center shrink-0 mt-0.5">
        <Bot className="h-4 w-4" />
      </div>
      <div className="min-w-0 flex-1 space-y-2">
        {msg.traces && msg.traces.length > 0 && (
          <AgentNarrative traces={msg.traces} excludeLastLlmText={!!answer && !msg.error} />
        )}
        {reasoning && <ThinkBlock reasoning={reasoning} thinking={thinking} />}

        <div className={`text-sm ${msg.error ? "rounded-xl border border-destructive/40 bg-destructive/5 px-3 py-2" : ""}`}>
          {msg.error ? (
            <span className="text-destructive text-xs font-mono">{msg.error}</span>
          ) : msg.animating && onAnimDone ? (
            <TypewriterText text={answer} onDone={onAnimDone} />
          ) : msg.streaming && !answer ? (
            // While the model is still emitting reasoning, the ThinkBlock above
            // shows "Thinking…", so skip the spinner; once reasoning closed but
            // the answer hasn't started, fall through to "Generating…".
            thinking ? null : (
              <span className="flex items-center gap-1.5 text-muted-foreground">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                <span className="text-xs">Generating…</span>
              </span>
            )
          ) : (
            <MarkdownContent text={answer} />
          )}
        </div>

        {msg.artifacts && msg.artifacts.length > 0 && (
          <div className="flex flex-col gap-2 w-full max-w-[680px]">
            {msg.artifacts.map((a, i) => <ArtifactCard key={i} a={a} />)}
          </div>
        )}
        {msg.logs && msg.logs.length > 0 && <LogStrip logs={msg.logs} />}
        {actions}
      </div>
    </div>
  );
}

// ── Conversation list item ────────────────────────────────────────────────────

function ConvItem({
  conv,
  active,
  onClick,
  onDelete,
}: {
  conv: ConversationSummary;
  active: boolean;
  onClick: () => void;
  onDelete: () => void;
}) {
  return (
    <div
      className={`group flex items-center gap-2 px-3 py-2 rounded-lg cursor-pointer text-sm transition-colors ${
        active ? "bg-primary/10 text-primary" : "hover:bg-muted/60 text-foreground"
      }`}
      onClick={onClick}
    >
      <MessageSquare className="h-3.5 w-3.5 shrink-0 opacity-60" />
      <span className="flex-1 truncate text-xs">{conv.title}</span>
      <button
        onClick={(e) => { e.stopPropagation(); onDelete(); }}
        className="opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive shrink-0"
      >
        <Trash2 className="h-3 w-3" />
      </button>
    </div>
  );
}

// ── Reasoning / think level (conversation-level) ──────────────────────────────

const REASONING_LEVELS = ["off", "low", "medium", "high"] as const;

// Conversation-level "how hard should the model think" control. The chosen level
// is saved on the conversation and threaded into each run's input as
// input["reasoning"]; a script turns it on via get_llm(reasoning=…). Only shows
// reasoning if the model supports it AND the script forwards the level.
function ReasoningControl({
  value,
  onChange,
}: {
  value: string;
  onChange: (v: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const active = !!value && value !== "off";
  return (
    <div className="relative">
      <button
        onClick={() => setOpen((p) => !p)}
        className={`flex items-center gap-1 text-xs px-2 py-1 rounded border border-transparent hover:border-border transition-colors ${
          active ? "text-primary" : "text-muted-foreground hover:text-foreground"
        }`}
        title="Reasoning / think level"
      >
        <Brain className="h-3 w-3" />
        <span className="capitalize">{active ? value : "Think"}</span>
        {open ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
      </button>
      {open && (
        <div className="absolute right-0 top-full mt-1 z-10 bg-popover border border-border rounded-lg shadow-md p-1 w-40">
          {REASONING_LEVELS.map((lvl) => (
            <button
              key={lvl}
              onClick={() => { onChange(lvl); setOpen(false); }}
              className={`w-full text-left text-xs px-2 py-1.5 rounded hover:bg-muted/60 capitalize ${
                value === lvl ? "text-primary font-medium" : "text-foreground"
              }`}
            >
              {lvl === "off" ? "Off" : lvl}
            </button>
          ))}
          <p className="text-[10px] text-muted-foreground px-2 py-1 leading-tight border-t border-border/50 mt-1">
            Needs a reasoning-capable model and a script that forwards it to <code className="font-mono">get_llm(reasoning=…)</code>.
          </p>
        </div>
      )}
    </div>
  );
}

// ── Context turns control ─────────────────────────────────────────────────────

function ContextTurnsControl({
  value,
  onChange,
}: {
  value: number;
  onChange: (n: number) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative">
      <button
        onClick={() => setOpen((p) => !p)}
        className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground px-2 py-1 rounded border border-transparent hover:border-border transition-colors"
        title="Context turns"
      >
        <Settings2 className="h-3 w-3" />
        {value} turns
        {open ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
      </button>
      {open && (
        <div className="absolute right-0 top-full mt-1 z-10 bg-popover border border-border rounded-lg shadow-md p-3 w-44">
          <Label className="text-xs mb-1.5 block">Context turns (1–50)</Label>
          <Input
            type="number"
            min={1}
            max={50}
            value={value}
            onChange={(e) => {
              const n = Math.max(1, Math.min(50, Number(e.target.value)));
              onChange(n);
            }}
            onBlur={() => setOpen(false)}
            className="h-7 text-xs"
            autoFocus
          />
          <p className="text-[10px] text-muted-foreground mt-1.5">
            How many recent turns are sent as history with each message.
          </p>
        </div>
      )}
    </div>
  );
}

// ── Copy link button (copies standalone embed URL) ────────────────────────────

function CopyLinkButton({ scriptId }: { scriptId: string }) {
  const [copied, setCopied] = useState(false);
  function copy() {
    const url = `${window.location.origin}/converse?id=${scriptId}&embed=1`;
    navigator.clipboard.writeText(url).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }
  return (
    <button
      onClick={copy}
      className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground px-2 py-1 rounded border border-transparent hover:border-border transition-colors"
      title="Copy standalone chat link"
    >
      {copied ? <Check className="h-3 w-3 text-green-500" /> : <Link2 className="h-3 w-3" />}
      {copied ? "Copied" : "Copy link"}
    </button>
  );
}

// ── Embed history dropdown ────────────────────────────────────────────────────

function EmbedHistoryDropdown({
  convList,
  activeConvId,
  onSelect,
  onDelete,
}: {
  convList: ConversationSummary[];
  activeConvId: string | null;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const active = convList.find((c) => c.id === activeConvId);
  if (convList.length === 0) return null;
  return (
    <div className="relative">
      <button
        onClick={() => setOpen((p) => !p)}
        className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground px-2 py-1 rounded border border-transparent hover:border-border transition-colors max-w-[140px]"
      >
        <MessageSquare className="h-3 w-3 shrink-0" />
        <span className="truncate">{active?.title ?? "History"}</span>
        <ChevronDown className="h-3 w-3 shrink-0" />
      </button>
      {open && (
        <div
          className="absolute right-0 top-full mt-1 z-20 bg-popover border border-border rounded-lg shadow-lg w-56 py-1 max-h-64 overflow-y-auto"
          onMouseLeave={() => setOpen(false)}
        >
          {convList.map((conv) => (
            <div
              key={conv.id}
              className={`group flex items-center gap-2 px-3 py-2 text-xs cursor-pointer hover:bg-muted/60 ${
                conv.id === activeConvId ? "text-primary" : "text-foreground"
              }`}
              onClick={() => { onSelect(conv.id); setOpen(false); }}
            >
              <span className="flex-1 truncate">{conv.title}</span>
              <button
                onClick={(e) => { e.stopPropagation(); onDelete(conv.id); }}
                className="opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive"
              >
                <Trash2 className="h-3 w-3" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function ConversePage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin" />
      </div>
    }>
      <ConverseInner />
    </Suspense>
  );
}

function ConverseInner() {
  const params = useSearchParams();
  const embed = params.get("embed") === "1";

  const [allScripts, setAllScripts] = useState<ScriptSummary[]>([]);
  const [scriptId, setScriptId] = useState(params.get("id") || "");
  const [convList, setConvList] = useState<ConversationSummary[]>([]);
  const [activeConvId, setActiveConvId] = useState<string | null>(null);
  const [contextTurns, setContextTurns] = useState(10);
  const [reasoningEffort, setReasoningEffort] = useState("off");
  const [messages, setMessages] = useState<UiMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [animatingId, setAnimatingId] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [search, setSearch] = useState("");
  const [showScrollBtn, setShowScrollBtn] = useState(false);

  const scrollRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const currentExecIdRef = useRef<string | null>(null);
  const atBottomRef = useRef(true);
  // Track whether any streaming tokens arrived for the current assistant turn.
  // Used to decide whether to run the typewriter animation after confirm —
  // if tokens already streamed in, the content is already visible so we skip it.
  const tokenReceivedRef = useRef(false);
  // Accumulated streamed content for the current assistant turn, so on completion
  // we can extract the <think> reasoning (absent from the persisted reply) and
  // both persist it (confirm) and stitch it back onto the finalized content.
  const streamedContentRef = useRef("");
  // When send() auto-creates a conversation, setActiveConvId triggers the
  // message-load effect which would wipe the optimistic messages. This ref
  // tells the effect to skip one load cycle.
  const skipNextMsgReloadRef = useRef(false);

  // Load scripts on mount
  useEffect(() => {
    scriptsApi.list()
      .then((list) => {
        setAllScripts(list);
        if (!scriptId && list.length > 0) setScriptId(list[0].id);
      })
      .catch(() => toast.error("Failed to load scripts"));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Keep URL in sync
  useEffect(() => {
    if (!scriptId) return;
    const u = new URL(window.location.href);
    u.searchParams.set("id", scriptId);
    window.history.replaceState({}, "", u.toString());
  }, [scriptId]);

  // Load conversations when script changes
  useEffect(() => {
    if (!scriptId) return;
    setActiveConvId(null);
    setMessages([]);
    convsApi.list(scriptId)
      .then((list) => {
        setConvList(list);
        // In embed mode, auto-create a fresh conversation so the page is ready to chat
        if (embed && list.length === 0) {
          convsApi.create({ script_id: scriptId, context_turns: contextTurns, reasoning_effort: reasoningEffort })
            .then((conv) => {
              setConvList([conv]);
              setActiveConvId(conv.id);
            })
            .catch(() => {});
        } else if (embed && list.length > 0) {
          // In embed mode, resume the most recent conversation automatically
          setActiveConvId(list[0].id);
        }
      })
      .catch(() => toast.error("Failed to load conversations"));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scriptId]);

  // Load messages when conversation changes
  useEffect(() => {
    if (!activeConvId) return;
    if (skipNextMsgReloadRef.current) {
      skipNextMsgReloadRef.current = false;
      return;
    }
    convsApi.get(activeConvId).then(async (conv) => {
      setContextTurns(conv.context_turns);
      setReasoningEffort(conv.reasoning_effort ?? "off");
      const base: UiMessage[] = conv.messages.map((m) => ({
        id: m.id,
        role: m.role,
        // Reasoning is persisted separately from content (so it stays out of
        // model history); re-attach it as the <think> block splitThink expects,
        // so the thought-process survives reload.
        content: m.reasoning ? `<think>${m.reasoning}</think>${m.content}` : m.content,
        error: m.error ?? undefined,
        execution_id: m.execution_id ?? undefined,
      }));
      setMessages(base);

      // Hydrate artifacts + agent traces for assistant messages that had a run.
      const targets = base.filter((m) => m.role === "assistant" && m.execution_id);
      if (!targets.length) return;
      const results = await Promise.allSettled(
        targets.map((m) => executionsApi.get(m.execution_id!))
      );
      const artsByMsg = new Map<string, ArtifactEvent[]>();
      const tracesByMsg = new Map<string, TraceEvent[]>();
      results.forEach((r, i) => {
        if (r.status !== "fulfilled") return;
        const logs = r.value.logs as ExecutionLog[];
        const arts = logs
          .filter((l) => l.level === "_artifact" && l.data)
          .map((l) => l.data as ArtifactEvent);
        if (arts.length) artsByMsg.set(targets[i].id, arts);
        const trcs = logs
          .filter((l) => l.level === "_trace" && l.data)
          .map((l) => l.data as TraceEvent);
        if (trcs.length) tracesByMsg.set(targets[i].id, trcs);
      });
      if (artsByMsg.size || tracesByMsg.size) {
        setMessages((prev) => prev.map((m) => ({
          ...m,
          ...(artsByMsg.has(m.id) ? { artifacts: artsByMsg.get(m.id) } : {}),
          ...(tracesByMsg.has(m.id) ? { traces: tracesByMsg.get(m.id) } : {}),
        })));
      }
    }).catch(() => toast.error("Failed to load conversation"));
  }, [activeConvId]);

  // Auto-scroll — only when the user is already near the bottom.
  useEffect(() => {
    if (atBottomRef.current) {
      scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
    }
  }, [messages]);

  function onScroll() {
    const el = scrollRef.current;
    if (!el) return;
    const dist = el.scrollHeight - el.scrollTop - el.clientHeight;
    atBottomRef.current = dist < 80;
    setShowScrollBtn(dist > 200);
  }

  function scrollToBottom() {
    atBottomRef.current = true;
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }

  const currentScript = allScripts.find((s) => s.id === scriptId);
  const filteredConvs = search.trim()
    ? convList.filter((c) => c.title.toLowerCase().includes(search.trim().toLowerCase()))
    : convList;

  async function createNewConversation() {
    if (!scriptId) return;
    try {
      const conv = await convsApi.create({ script_id: scriptId, context_turns: contextTurns, reasoning_effort: reasoningEffort });
      setConvList((prev) => [conv, ...prev]);
      setActiveConvId(conv.id);
      setMessages([]);
    } catch {
      toast.error("Failed to create conversation");
    }
  }

  async function deleteConversation(id: string) {
    try {
      await convsApi.delete(id);
      setConvList((prev) => prev.filter((c) => c.id !== id));
      if (activeConvId === id) {
        setActiveConvId(null);
        setMessages([]);
      }
    } catch {
      toast.error("Failed to delete conversation");
    }
  }

  async function updateContextTurns(n: number) {
    setContextTurns(n);
    if (activeConvId) {
      convsApi.update(activeConvId, { context_turns: n }).catch(() => {});
    }
  }

  async function updateReasoning(v: string) {
    setReasoningEffort(v);
    if (activeConvId) {
      convsApi.update(activeConvId, { reasoning_effort: v }).catch(() => {});
    }
  }

  const openWebSocket = useCallback((executionId: string, assistantMsgId: string, convId: string) => {
    if (wsRef.current) wsRef.current.close();
    tokenReceivedRef.current = false;
    streamedContentRef.current = "";
    currentExecIdRef.current = executionId;

    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${window.location.host}/ws/executions/${executionId}`);
    wsRef.current = ws;

    ws.onmessage = (e) => {
      let evt: WsEvent;
      try { evt = JSON.parse(e.data); } catch { return; }

      if (evt.type === "token") {
        tokenReceivedRef.current = true;
        streamedContentRef.current += evt.content;
        setMessages((prev) => prev.map((m) =>
          m.id === assistantMsgId
            ? { ...m, content: m.content + evt.content, streaming: true }
            : m
        ));
      } else if (evt.type === "log") {
        setMessages((prev) => prev.map((m) =>
          m.id === assistantMsgId
            ? { ...m, logs: [...(m.logs ?? []), evt] }
            : m
        ));
      } else if (evt.type === "trace") {
        setMessages((prev) => prev.map((m) =>
          m.id === assistantMsgId
            ? { ...m, traces: [...(m.traces ?? []), evt as TraceEvent] }
            : m
        ));
      } else if (evt.type === "artifact") {
        setMessages((prev) => prev.map((m) =>
          m.id === assistantMsgId
            ? { ...m, artifacts: [...(m.artifacts ?? []), evt] }
            : m
        ));
      } else if (evt.type === "status") {
        const done = evt.status === "completed" || evt.status === "failed" || evt.status === "cancelled";
        if (done) {
          ws.close();
          wsRef.current = null;
          currentExecIdRef.current = null;
          // Carry the reasoning we streamed live: output_data (→ saved.content)
          // omits it, so hand it to confirm to persist for reload and stitch it
          // back onto the finalized content now (else the block would vanish the
          // instant the run completes).
          const streamedReasoning = splitThink(streamedContentRef.current).reasoning;
          convsApi.confirm(convId, executionId, streamedReasoning || undefined).then((saved) => {
            const wasStreamed = tokenReceivedRef.current;
            const shouldAnimate = !wasStreamed && !saved.error && !!saved.content;
            setMessages((prev) => prev.map((m) => {
              if (m.id !== assistantMsgId) return m;
              const content =
                streamedReasoning && !/<think(?:ing)?>/i.test(saved.content)
                  ? `<think>${streamedReasoning}</think>${saved.content}`
                  : saved.content;
              return {
                ...m,
                // Swap the client temp id for the real DB id, otherwise the
                // just-finished message keeps a `tmp-…` id and the delete
                // button (gated on `!id.startsWith("tmp-")`) never appears
                // until a reload.
                id: saved.id,
                execution_id: saved.execution_id ?? m.execution_id,
                content,
                error: saved.error ?? undefined,
                streaming: false,
                animating: shouldAnimate,
              };
            }));
            if (shouldAnimate) {
              // animatingId must match the new id so onAnimDone fires and clears
              // `animating` (which also gates the delete button).
              setAnimatingId(saved.id);
            }
            setSending(false);
            setConvList((prev) =>
              prev.map((c) =>
                c.id === convId ? { ...c, updated_at: new Date().toISOString() } : c
              ).sort((a, b) => b.updated_at.localeCompare(a.updated_at))
            );
          }).catch(() => {
            setSending(false);
            toast.error("Failed to save reply");
          });
        }
      }
    };

    ws.onerror = () => {
      setSending(false);
      toast.error("WebSocket connection error");
    };
  }, []);

  async function send() {
    const msg = input.trim();
    if (!msg || !scriptId || sending) return;

    // Ensure there's an active conversation
    let convId = activeConvId;
    if (!convId) {
      try {
        const conv = await convsApi.create({ script_id: scriptId, context_turns: contextTurns, reasoning_effort: reasoningEffort });
        skipNextMsgReloadRef.current = true;
        setConvList((prev) => [conv, ...prev]);
        setActiveConvId(conv.id);
        convId = conv.id;
      } catch {
        toast.error("Failed to create conversation");
        return;
      }
    }

    setInput("");
    setSending(true);
    atBottomRef.current = true;

    // Optimistic user message (temp id)
    const tempUserId = `tmp-user-${Date.now()}`;
    const assistantId = `tmp-asst-${Date.now()}`;
    setMessages((prev) => [
      ...prev,
      { id: tempUserId, role: "user", content: msg },
      { id: assistantId, role: "assistant", content: "", streaming: true, logs: [], traces: [] },
    ]);

    try {
      const { execution_id, user_msg_id } = await convsApi.chatStart(convId, msg);

      // Replace temp user id with real one
      setMessages((prev) => prev.map((m) =>
        m.id === tempUserId ? { ...m, id: user_msg_id } : m
      ));

      // Auto-title on first message (fire-and-forget)
      const isFirstMsg = messages.length === 0;
      if (isFirstMsg) {
        convsApi.update(convId, { title: msg.slice(0, 60) })
          .then((updated) => {
            setConvList((prev) => prev.map((c) => c.id === convId ? { ...c, title: updated.title } : c));
          })
          .catch(() => {});
      }

      openWebSocket(execution_id, assistantId, convId);
    } catch (err) {
      setSending(false);
      setMessages((prev) => prev.filter((m) => m.id !== assistantId).map((m) =>
        m.id === tempUserId ? { ...m } : m
      ));
      toast.error(String(err));
    }
  }

  async function stopGeneration() {
    const id = currentExecIdRef.current;
    if (!id) return;
    try {
      await executionsApi.stop(id);
      // The WS will deliver a `cancelled` status which runs confirm + cleanup.
    } catch {
      toast.error("Failed to stop");
    }
  }

  function handleAnimDone(msgId: string) {
    setAnimatingId(null);
    setMessages((prev) => prev.map((m) =>
      m.id === msgId ? { ...m, animating: false } : m
    ));
  }

  async function deleteMessage(msgId: string) {
    if (!activeConvId) return;
    try {
      await convsApi.deleteMessage(activeConvId, msgId);
      setMessages((prev) => prev.filter((m) => m.id !== msgId));
    } catch {
      toast.error("Failed to delete message");
    }
  }

  // ── Shared message area + composer ───────────────────────────────────────────

  const messageArea = (
    <div className="relative flex-1 min-h-0">
      <div ref={scrollRef} onScroll={onScroll} className="absolute inset-0 overflow-y-auto">
        <div className="max-w-3xl mx-auto px-4 py-6 space-y-6">
          {messages.length === 0 && !activeConvId && (
            <EmptyState scriptName={currentScript?.name} onNew={createNewConversation} hasScript={!!scriptId} />
          )}
          {messages.map((m) => (
            <MessageRow
              key={m.id}
              msg={m}
              onAnimDone={m.id === animatingId ? () => handleAnimDone(m.id) : undefined}
              onDelete={() => deleteMessage(m.id)}
            />
          ))}
        </div>
      </div>
      {showScrollBtn && (
        <button
          onClick={scrollToBottom}
          className="absolute bottom-4 left-1/2 -translate-x-1/2 h-8 w-8 rounded-full bg-popover border border-border shadow-md flex items-center justify-center text-muted-foreground hover:text-foreground transition-colors"
          title="Scroll to bottom"
        >
          <ArrowDown className="h-4 w-4" />
        </button>
      )}
    </div>
  );

  const composer = (
    <div className="px-4 pb-4 pt-2 shrink-0">
      <div className="max-w-3xl mx-auto">
        <div className="flex items-end gap-2 rounded-2xl border border-border bg-secondary/30 px-3 py-2 focus-within:border-primary/50 transition-colors">
          <Textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            placeholder={
              !scriptId
                ? "Select a script first"
                : !activeConvId
                ? "Send a message to start the conversation…"
                : "Type a message… (Enter to send, Shift+Enter for a new line)"
            }
            className="min-h-[40px] max-h-48 text-sm resize-none border-0 bg-transparent focus-visible:ring-0 px-1 py-1.5 shadow-none"
            disabled={!scriptId || sending}
          />
          {sending ? (
            <Button
              onClick={stopGeneration}
              size="icon"
              variant="secondary"
              className="h-9 w-9 shrink-0 rounded-xl"
              title="Stop generating"
            >
              <Square className="h-3.5 w-3.5 fill-current" />
            </Button>
          ) : (
            <Button
              onClick={send}
              disabled={!input.trim() || !scriptId}
              size="icon"
              className="h-9 w-9 shrink-0 rounded-xl"
              title="Send"
            >
              <Send className="h-4 w-4" />
            </Button>
          )}
        </div>
        <p className="text-[10px] text-muted-foreground/50 text-center mt-1.5">
          Content is generated by the script — use your own judgment.
        </p>
      </div>
    </div>
  );

  // ── Embed layout (standalone, no navigation) ─────────────────────────────────

  if (embed) {
    return (
      <div className="h-screen flex flex-col bg-background">
        <header className="border-b border-border px-3 py-2 flex items-center gap-2 shrink-0">
          <span className="text-sm font-medium truncate flex-1 min-w-0">
            {currentScript?.name ?? "Chat"}
          </span>
          <EmbedHistoryDropdown
            convList={convList}
            activeConvId={activeConvId}
            onSelect={setActiveConvId}
            onDelete={deleteConversation}
          />
          <button
            onClick={createNewConversation}
            disabled={!scriptId}
            className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground px-2 py-1 rounded hover:bg-muted/60 transition-colors disabled:opacity-40"
          >
            <Plus className="h-3.5 w-3.5" />
            New
          </button>
          <ReasoningControl value={reasoningEffort} onChange={updateReasoning} />
          <ContextTurnsControl value={contextTurns} onChange={updateContextTurns} />
        </header>
        {messageArea}
        {composer}
      </div>
    );
  }

  // ── Full layout (with collapsible sidebar) ───────────────────────────────────

  return (
    <div className="h-screen flex overflow-hidden">
      {sidebarOpen && (
        <aside className="w-64 border-r border-border flex flex-col shrink-0 bg-background">
          <div className="p-3 border-b border-border space-y-2">
            <Link href="/">
              <Button variant="ghost" size="sm" className="w-full justify-start gap-2 h-8 text-xs">
                <ArrowLeft className="h-3.5 w-3.5" />
                Back to Home
              </Button>
            </Link>
            <div>
              <Label className="text-xs text-muted-foreground mb-1 block">Script</Label>
              <Select value={scriptId} onValueChange={(v) => { setScriptId(v); }}>
                <SelectTrigger className="h-8 text-xs">
                  <SelectValue placeholder="Select a script" />
                </SelectTrigger>
                <SelectContent>
                  {allScripts.map((s) => (
                    <SelectItem key={s.id} value={s.id} className="text-xs">{s.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <Button
              size="sm"
              className="w-full h-8 text-xs gap-1.5"
              onClick={createNewConversation}
              disabled={!scriptId}
            >
              <Plus className="h-3.5 w-3.5" />
              New conversation
            </Button>
            <div className="relative">
              <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground/50" />
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search conversations"
                className="h-7 text-xs pl-7"
              />
            </div>
          </div>

          <ScrollArea className="flex-1 p-2">
            {filteredConvs.length === 0 && (
              <p className="text-xs text-muted-foreground text-center py-6">
                {search.trim() ? "No matching conversations" : "No conversations yet"}
              </p>
            )}
            {filteredConvs.map((conv) => (
              <ConvItem
                key={conv.id}
                conv={conv}
                active={conv.id === activeConvId}
                onClick={() => setActiveConvId(conv.id)}
                onDelete={() => deleteConversation(conv.id)}
              />
            ))}
          </ScrollArea>
        </aside>
      )}

      <div className="flex-1 flex flex-col min-w-0">
        <header className="border-b border-border px-4 py-2 flex items-center gap-2 shrink-0">
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 shrink-0"
            onClick={() => setSidebarOpen((o) => !o)}
            title={sidebarOpen ? "Collapse sidebar" : "Expand sidebar"}
          >
            {sidebarOpen ? <PanelLeftClose className="h-4 w-4" /> : <PanelLeftOpen className="h-4 w-4" />}
          </Button>
          <MessageSquare className="h-4 w-4 text-primary shrink-0" />
          <span className="text-sm font-medium truncate">
            {currentScript?.name ?? "Chat"}
          </span>
          <div className="ml-auto flex items-center gap-2">
            <ReasoningControl value={reasoningEffort} onChange={updateReasoning} />
            <ContextTurnsControl value={contextTurns} onChange={updateContextTurns} />
            {scriptId && <CopyLinkButton scriptId={scriptId} />}
            {currentScript && (
              <Link
                href={`/script/?id=${currentScript.id}`}
                className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1"
              >
                <ExternalLink className="h-3 w-3" />
                Edit script
              </Link>
            )}
            {activeConvId && (
              <Button
                variant="ghost"
                size="sm"
                className="h-7 text-xs gap-1 text-muted-foreground hover:text-destructive"
                onClick={() => deleteConversation(activeConvId)}
              >
                <Trash2 className="h-3 w-3" />
                Delete
              </Button>
            )}
          </div>
        </header>
        {messageArea}
        {composer}
      </div>
    </div>
  );
}

function EmptyState({
  scriptName,
  onNew,
  hasScript,
}: {
  scriptName?: string;
  onNew: () => void;
  hasScript: boolean;
}) {
  return (
    <div className="flex flex-col items-center justify-center text-center py-20 text-muted-foreground">
      <div className="h-14 w-14 rounded-2xl bg-primary/10 flex items-center justify-center mb-4">
        <MessageSquare className="h-7 w-7 text-primary/60" />
      </div>
      {hasScript ? (
        <>
          <p className="text-sm mb-1 text-foreground">
            {scriptName ? `Start a conversation with "${scriptName}"` : "Select a script to start"}
          </p>
          <p className="text-xs mb-4 max-w-sm">
            Conversations are saved; the history is sent to the script with each turn.
          </p>
          <Button size="sm" onClick={onNew} className="gap-1.5">
            <Plus className="h-3.5 w-3.5" />
            New conversation
          </Button>
        </>
      ) : (
        <p className="text-sm">Select a script from the sidebar to get started.</p>
      )}
    </div>
  );
}
