"use client";
import { Suspense, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowLeft, Send, Loader2, MessageSquare, Trash2, User, Bot } from "lucide-react";
import { toast } from "sonner";
import { scripts as scriptsApi } from "@/lib/api";
import type { ScriptSummary } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Label } from "@/components/ui/label";

interface ChatMsg {
  role: "user" | "assistant";
  content: string;
  raw?: unknown;     // full output_data for debugging
  error?: string;
}

export default function ChatPageWrapper() {
  return (
    <Suspense fallback={<div className="min-h-screen flex items-center justify-center"><Loader2 className="h-6 w-6 animate-spin" /></div>}>
      <ChatPage />
    </Suspense>
  );
}

function ChatPage() {
  const router = useRouter();
  const params = useSearchParams();

  const [allScripts, setAllScripts] = useState<ScriptSummary[]>([]);
  const [scriptId, setScriptId] = useState<string>(params.get("id") || "");
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scriptsApi.list()
      .then((list) => {
        setAllScripts(list);
        if (!scriptId && list.length > 0) setScriptId(list[0].id);
      })
      .catch(() => toast.error("Failed to load scripts"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // keep URL in sync so chats can be shared/refreshed
  useEffect(() => {
    if (scriptId) {
      const u = new URL(window.location.href);
      u.searchParams.set("id", scriptId);
      window.history.replaceState({}, "", u.toString());
    }
  }, [scriptId]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, sending]);

  async function send() {
    const msg = input.trim();
    if (!msg || !scriptId || sending) return;

    const history = messages.map((m) => ({ role: m.role, content: m.content }));
    const userMsg: ChatMsg = { role: "user", content: msg };
    setMessages((m) => [...m, userMsg]);
    setInput("");
    setSending(true);

    try {
      const res = await fetch("/api/executions/run?timeout=120", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          script_id: scriptId,
          input_data: { message: msg, history },
        }),
      });
      const data = await res.json();

      if (!res.ok || data.status !== "completed") {
        const err = data.error || data.detail || `HTTP ${res.status}`;
        setMessages((m) => [...m, { role: "assistant", content: "", error: err }]);
        return;
      }

      const out = data.output_data ?? {};
      // accept several common reply field names
      const reply = (typeof out === "string")
        ? out
        : (out.reply ?? out.message ?? out.response ?? out.result ?? JSON.stringify(out));

      setMessages((m) => [...m, {
        role: "assistant",
        content: String(reply),
        raw: out,
      }]);
    } catch (e: unknown) {
      setMessages((m) => [...m, {
        role: "assistant", content: "", error: String(e),
      }]);
    } finally {
      setSending(false);
    }
  }

  function clearChat() {
    if (messages.length === 0) return;
    if (!confirm("Clear conversation?")) return;
    setMessages([]);
  }

  const currentScript = allScripts.find((s) => s.id === scriptId);

  return (
    <div className="h-screen flex flex-col">
      {/* header */}
      <header className="border-b border-border px-4 py-2.5 flex items-center gap-3 shrink-0">
        <Link href="/">
          <Button variant="ghost" size="icon" className="h-8 w-8">
            <ArrowLeft className="h-4 w-4" />
          </Button>
        </Link>
        <MessageSquare className="h-4 w-4 text-primary" />
        <span className="text-sm font-medium">Chat</span>

        <div className="ml-4 flex items-center gap-2">
          <Label className="text-xs text-muted-foreground">Script:</Label>
          <Select value={scriptId} onValueChange={(v) => { setScriptId(v); setMessages([]); }}>
            <SelectTrigger className="h-8 w-64 text-xs">
              <SelectValue placeholder="Pick a script" />
            </SelectTrigger>
            <SelectContent>
              {allScripts.map((s) => (
                <SelectItem key={s.id} value={s.id} className="text-xs">
                  {s.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="ml-auto flex items-center gap-2">
          {currentScript && (
            <Link
              href={`/script/?id=${currentScript.id}`}
              className="text-xs text-muted-foreground hover:text-foreground"
            >
              edit script →
            </Link>
          )}
          <Button
            variant="ghost"
            size="sm"
            className="h-7 text-xs gap-1.5 text-muted-foreground hover:text-destructive"
            onClick={clearChat}
            disabled={messages.length === 0}
          >
            <Trash2 className="h-3 w-3" />
            Clear
          </Button>
        </div>
      </header>

      {/* messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto">
        <div className="max-w-3xl mx-auto px-4 py-6 space-y-4">
          {messages.length === 0 && (
            <EmptyState scriptName={currentScript?.name} />
          )}
          {messages.map((m, i) => <MessageRow key={i} msg={m} />)}
          {sending && (
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="h-3 w-3 animate-spin" />
              Running script…
            </div>
          )}
        </div>
      </div>

      {/* input */}
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
            placeholder={scriptId ? "Type a message… (Enter to send, Shift+Enter for newline)" : "Pick a script first"}
            className="min-h-[44px] max-h-40 text-sm resize-none"
            disabled={!scriptId || sending}
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
    </div>
  );
}

function MessageRow({ msg }: { msg: ChatMsg }) {
  const isUser = msg.role === "user";
  return (
    <div className={`flex gap-3 ${isUser ? "flex-row-reverse" : ""}`}>
      <div className={`h-7 w-7 rounded-full flex items-center justify-center shrink-0 ${
        isUser ? "bg-primary/20 text-primary" : "bg-secondary text-foreground"
      }`}>
        {isUser ? <User className="h-3.5 w-3.5" /> : <Bot className="h-3.5 w-3.5" />}
      </div>
      <div className={`max-w-[80%] rounded-2xl px-4 py-2.5 text-sm whitespace-pre-wrap break-words ${
        isUser ? "bg-primary/15 text-foreground" : "bg-secondary/50 text-foreground"
      } ${msg.error ? "border border-destructive/40" : ""}`}>
        {msg.error ? (
          <span className="text-destructive text-xs font-mono">{msg.error}</span>
        ) : (
          msg.content
        )}
      </div>
    </div>
  );
}

function EmptyState({ scriptName }: { scriptName?: string }) {
  return (
    <div className="flex flex-col items-center justify-center text-center py-20 text-muted-foreground">
      <MessageSquare className="h-12 w-12 text-muted-foreground/30 mb-4" />
      <p className="text-sm">
        {scriptName ? `Chat with "${scriptName}"` : "Select a script to start chatting"}
      </p>
      <p className="text-xs mt-2 max-w-md">
        The script receives <code className="font-mono text-foreground">{`{message, history}`}</code> as input
        and should return <code className="font-mono text-foreground">{`{reply}`}</code>.
      </p>
    </div>
  );
}
