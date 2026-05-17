"use client";
import { Suspense, useEffect, useRef, useState, useCallback } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  ArrowLeft, Send, Loader2, MessageSquare, Trash2, User, Bot,
  Plus, Settings2, ExternalLink, ChevronDown, ChevronUp, Link2, Check,
} from "lucide-react";
import { toast } from "sonner";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { scripts as scriptsApi, conversations as convsApi } from "@/lib/api";
import type { ScriptSummary, ConversationSummary, ConversationMessage, WsEvent } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";

// ── Markdown renderer ─────────────────────────────────────────────────────────

function MarkdownContent({ text }: { text: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        p: ({ children }) => <p className="mb-2 last:mb-0 leading-relaxed">{children}</p>,
        h1: ({ children }) => <h1 className="text-lg font-bold mb-2 mt-3 first:mt-0">{children}</h1>,
        h2: ({ children }) => <h2 className="text-base font-bold mb-2 mt-3 first:mt-0">{children}</h2>,
        h3: ({ children }) => <h3 className="text-sm font-semibold mb-1 mt-2 first:mt-0">{children}</h3>,
        ul: ({ children }) => <ul className="list-disc pl-5 mb-2 space-y-0.5">{children}</ul>,
        ol: ({ children }) => <ol className="list-decimal pl-5 mb-2 space-y-0.5">{children}</ol>,
        li: ({ children }) => <li className="leading-relaxed">{children}</li>,
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        code: ({ inline, children, ...props }: any) =>
          inline ? (
            <code className="bg-muted px-1 py-0.5 rounded text-[0.85em] font-mono" {...props}>{children}</code>
          ) : (
            <code className="block font-mono text-xs" {...props}>{children}</code>
          ),
        pre: ({ children }) => (
          <pre className="bg-muted rounded-lg p-3 mb-2 overflow-x-auto text-xs font-mono">{children}</pre>
        ),
        blockquote: ({ children }) => (
          <blockquote className="border-l-2 border-primary/50 pl-3 italic text-muted-foreground mb-2">{children}</blockquote>
        ),
        a: ({ href, children }) => (
          <a href={href} target="_blank" rel="noopener noreferrer" className="text-primary underline underline-offset-2">{children}</a>
        ),
        strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
        em: ({ children }) => <em className="italic">{children}</em>,
        hr: () => <hr className="border-border my-3" />,
        table: ({ children }) => (
          <div className="overflow-x-auto mb-2">
            <table className="border-collapse w-full text-xs">{children}</table>
          </div>
        ),
        th: ({ children }) => <th className="border border-border px-2 py-1 bg-muted font-medium text-left">{children}</th>,
        td: ({ children }) => <td className="border border-border px-2 py-1">{children}</td>,
      }}
    >
      {text}
    </ReactMarkdown>
  );
}

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

// ── Log strip ─────────────────────────────────────────────────────────────────

const LEVEL_COLORS: Record<string, string> = {
  info: "text-muted-foreground",
  debug: "text-muted-foreground/60",
  warning: "text-yellow-500",
  error: "text-destructive",
  raw: "text-muted-foreground/70",
};

function LogStrip({ logs }: { logs: WsEvent[] }) {
  const logEvents = logs.filter((e): e is Extract<WsEvent, { type: "log" }> => e.type === "log");
  if (logEvents.length === 0) return null;
  return (
    <div className="mt-1 ml-10 rounded border border-border/50 bg-muted/30 p-2 space-y-0.5 max-h-32 overflow-y-auto">
      {logEvents.map((e, i) => (
        <div key={i} className={`text-[11px] font-mono ${LEVEL_COLORS[e.level] ?? "text-muted-foreground"}`}>
          {e.step && <span className="mr-1 opacity-60">[{e.step}]</span>}
          {e.message}
        </div>
      ))}
    </div>
  );
}

// ── Message row ───────────────────────────────────────────────────────────────

interface UiMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  error?: string;
  streaming?: boolean;   // actively receiving tokens
  animating?: boolean;   // playing typewriter after confirm
  logs?: WsEvent[];
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
  const canDelete = onDelete && !msg.streaming && !msg.animating && !msg.id.startsWith("tmp-");
  return (
    <div className={`group flex gap-3 ${isUser ? "flex-row-reverse" : ""}`}>
      <div className={`h-7 w-7 rounded-full flex items-center justify-center shrink-0 ${
        isUser ? "bg-primary/20 text-primary" : "bg-secondary text-foreground"
      }`}>
        {isUser ? <User className="h-3.5 w-3.5" /> : <Bot className="h-3.5 w-3.5" />}
      </div>
      <div className={`flex flex-col gap-1 max-w-[80%] ${isUser ? "items-end" : "items-start"}`}>
        <div className={`rounded-2xl px-4 py-2.5 text-sm ${
          isUser
            ? "bg-primary/15 text-foreground whitespace-pre-wrap break-words"
            : "bg-secondary/50 text-foreground"
        } ${msg.error ? "border border-destructive/40" : ""}`}>
          {msg.error ? (
            <span className="text-destructive text-xs font-mono">{msg.error}</span>
          ) : msg.animating && onAnimDone ? (
            <TypewriterText text={msg.content} onDone={onAnimDone} />
          ) : msg.streaming && !msg.content ? (
            <span className="flex items-center gap-1.5 text-muted-foreground">
              <Loader2 className="h-3 w-3 animate-spin" />
              <span className="text-xs">Thinking…</span>
            </span>
          ) : isUser ? (
            msg.content
          ) : (
            <MarkdownContent text={msg.content} />
          )}
        </div>
        {msg.logs && msg.logs.length > 0 && <LogStrip logs={msg.logs} />}
        {canDelete && (
          <button
            onClick={onDelete}
            className="opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground/50 hover:text-destructive text-[10px] flex items-center gap-1 px-1"
          >
            <Trash2 className="h-2.5 w-2.5" />
            Delete
          </button>
        )}
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
  const [hover, setHover] = useState(false);
  return (
    <div
      className={`group flex items-center gap-2 px-3 py-2 rounded-lg cursor-pointer text-sm transition-colors ${
        active ? "bg-primary/10 text-primary" : "hover:bg-muted/60 text-foreground"
      }`}
      onClick={onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
    >
      <MessageSquare className="h-3.5 w-3.5 shrink-0 opacity-60" />
      <span className="flex-1 truncate text-xs">{conv.title}</span>
      {hover && (
        <button
          onClick={(e) => { e.stopPropagation(); onDelete(); }}
          className="text-muted-foreground hover:text-destructive shrink-0"
        >
          <Trash2 className="h-3 w-3" />
        </button>
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
            How many recent exchange pairs to include as history.
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
      title="Copy standalone chat link (no navigation)"
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
  const [messages, setMessages] = useState<UiMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [animatingId, setAnimatingId] = useState<string | null>(null);

  const scrollRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  // Track whether any streaming tokens arrived for the current assistant turn.
  // Used to decide whether to run the typewriter animation after confirm —
  // if tokens already streamed in, the content is already visible so we skip it.
  const tokenReceivedRef = useRef(false);
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
          convsApi.create({ script_id: scriptId, context_turns: contextTurns })
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
    convsApi.get(activeConvId).then((conv) => {
      setContextTurns(conv.context_turns);
      setMessages(conv.messages.map((m) => ({
        id: m.id,
        role: m.role,
        content: m.content,
        error: m.error ?? undefined,
      })));
    }).catch(() => toast.error("Failed to load conversation"));
  }, [activeConvId]);

  // Auto-scroll
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  const currentScript = allScripts.find((s) => s.id === scriptId);

  async function createNewConversation() {
    if (!scriptId) return;
    try {
      const conv = await convsApi.create({ script_id: scriptId, context_turns: contextTurns });
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

  const openWebSocket = useCallback((executionId: string, assistantMsgId: string, convId: string) => {
    if (wsRef.current) wsRef.current.close();
    tokenReceivedRef.current = false;

    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${window.location.host}/ws/executions/${executionId}`);
    wsRef.current = ws;

    ws.onmessage = (e) => {
      let evt: WsEvent;
      try { evt = JSON.parse(e.data); } catch { return; }

      if (evt.type === "token") {
        tokenReceivedRef.current = true;
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
      } else if (evt.type === "status") {
        const done = evt.status === "completed" || evt.status === "failed" || evt.status === "cancelled";
        if (done) {
          ws.close();
          wsRef.current = null;
          convsApi.confirm(convId, executionId).then((saved) => {
            const wasStreamed = tokenReceivedRef.current;
            const shouldAnimate = !wasStreamed && !saved.error && !!saved.content;
            setMessages((prev) => prev.map((m) =>
              m.id === assistantMsgId
                ? {
                    ...m,
                    content: saved.content,
                    error: saved.error ?? undefined,
                    streaming: false,
                    animating: shouldAnimate,
                  }
                : m
            ));
            if (shouldAnimate) {
              setAnimatingId(assistantMsgId);
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
      toast.error("WebSocket error");
    };
  }, []);

  async function send() {
    const msg = input.trim();
    if (!msg || !scriptId || sending) return;

    // Ensure there's an active conversation
    let convId = activeConvId;
    if (!convId) {
      try {
        const conv = await convsApi.create({ script_id: scriptId, context_turns: contextTurns });
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

    // Optimistic user message (temp id)
    const tempUserId = `tmp-user-${Date.now()}`;
    const assistantId = `tmp-asst-${Date.now()}`;
    setMessages((prev) => [
      ...prev,
      { id: tempUserId, role: "user", content: msg },
      { id: assistantId, role: "assistant", content: "", streaming: true, logs: [] },
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

  // ── Shared message area + input ──────────────────────────────────────────────

  const messageArea = (
    <div ref={scrollRef} className="flex-1 overflow-y-auto">
      <div className="max-w-3xl mx-auto px-4 py-6 space-y-4">
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
  );

  const inputArea = (
    <div className="border-t border-border p-3 shrink-0">
      <div className="max-w-3xl mx-auto flex gap-2 items-end">
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
              ? "Send a message to start…"
              : "Message… (Enter to send, Shift+Enter for newline)"
          }
          className="min-h-[44px] max-h-40 text-sm resize-none"
          disabled={!scriptId || (sending && animatingId !== null)}
        />
        <Button
          onClick={send}
          disabled={!input.trim() || !scriptId || sending}
          size="icon"
          className="h-11 w-11 shrink-0"
        >
          {sending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
        </Button>
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
          <ContextTurnsControl value={contextTurns} onChange={updateContextTurns} />
        </header>
        {messageArea}
        {inputArea}
      </div>
    );
  }

  // ── Full layout (with sidebar) ────────────────────────────────────────────────

  return (
    <div className="h-screen flex overflow-hidden">
      <aside className="w-64 border-r border-border flex flex-col shrink-0 bg-background">
        <div className="p-3 border-b border-border space-y-2">
          <Link href="/">
            <Button variant="ghost" size="sm" className="w-full justify-start gap-2 h-8 text-xs">
              <ArrowLeft className="h-3.5 w-3.5" />
              Home
            </Button>
          </Link>
          <div>
            <Label className="text-xs text-muted-foreground mb-1 block">Script</Label>
            <Select value={scriptId} onValueChange={(v) => { setScriptId(v); }}>
              <SelectTrigger className="h-8 text-xs">
                <SelectValue placeholder="Select script" />
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
        </div>

        <ScrollArea className="flex-1 p-2">
          {convList.length === 0 && (
            <p className="text-xs text-muted-foreground text-center py-6">No conversations yet</p>
          )}
          {convList.map((conv) => (
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

      <div className="flex-1 flex flex-col min-w-0">
        <header className="border-b border-border px-4 py-2 flex items-center gap-3 shrink-0">
          <MessageSquare className="h-4 w-4 text-primary shrink-0" />
          <span className="text-sm font-medium truncate">
            {currentScript?.name ?? "Converse"}
          </span>
          <div className="ml-auto flex items-center gap-2">
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
        {inputArea}
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
      <MessageSquare className="h-12 w-12 text-muted-foreground/30 mb-4" />
      {hasScript ? (
        <>
          <p className="text-sm mb-1">
            {scriptName ? `Start chatting with "${scriptName}"` : "Select a script to start"}
          </p>
          <p className="text-xs mb-4 max-w-sm">
            Conversations are saved and history is sent to the script on each turn.
          </p>
          <Button size="sm" onClick={onNew} className="gap-1.5">
            <Plus className="h-3.5 w-3.5" />
            New Conversation
          </Button>
        </>
      ) : (
        <p className="text-sm">Pick a script from the sidebar to get started.</p>
      )}
    </div>
  );
}
