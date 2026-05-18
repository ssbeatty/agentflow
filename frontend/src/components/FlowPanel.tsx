"use client";
import { useMemo, useState } from "react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { ChevronDown, ChevronRight, Wrench, Box, Bot, Flag, Brain } from "lucide-react";
import type { TraceEvent, GraphTopology } from "@/lib/types";
import { cn } from "@/lib/utils";
import MermaidView from "@/components/MermaidView";

interface Props {
  trace: TraceEvent[];
  topology: GraphTopology | null;
}

// Pair start/end events by run_id for compact rendering.
interface TraceRow {
  key: string;
  kind: TraceEvent["kind"];
  name: string;
  step?: number;
  durationMs?: number | null;
  input?: unknown;
  output?: unknown;
  error?: string;
  isOpen: boolean;       // true if start without end yet
  log?: unknown;
}

function buildRows(events: TraceEvent[]): TraceRow[] {
  const byRun = new Map<string, TraceRow>();
  const order: TraceRow[] = [];
  for (const ev of events) {
    if (ev.kind === "agent_action" || ev.kind === "agent_finish") {
      const row: TraceRow = {
        key: `${ev.run_id}-${ev.ts}`,
        kind: ev.kind,
        name: ev.name,
        input: ev.input,
        output: ev.output,
        log: ev.log,
        isOpen: false,
      };
      order.push(row);
      continue;
    }
    if (ev.phase === "start") {
      const row: TraceRow = {
        key: ev.run_id,
        kind: ev.kind,
        name: ev.name,
        step: ev.step,
        input: ev.input,
        isOpen: true,
      };
      byRun.set(ev.run_id, row);
      order.push(row);
    } else {
      const row = byRun.get(ev.run_id);
      if (row) {
        row.output = ev.output;
        row.error = ev.error;
        row.durationMs = ev.duration_ms ?? null;
        row.isOpen = false;
      } else {
        // stray end without start — render as standalone
        order.push({
          key: `${ev.run_id}-end`,
          kind: ev.kind,
          name: ev.name,
          output: ev.output,
          error: ev.error,
          durationMs: ev.duration_ms ?? null,
          isOpen: false,
        });
      }
    }
  }
  return order;
}

function visitedNodeCounts(events: TraceEvent[]): Map<string, number> {
  const m = new Map<string, number>();
  for (const ev of events) {
    if (ev.kind === "node" && ev.phase === "start") {
      m.set(ev.name, (m.get(ev.name) ?? 0) + 1);
    }
  }
  return m;
}

function escapeRegex(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

// For nodes hit more than once (e.g. a `critic` re-entered in a loop), inject
// a `×N` badge into the mermaid node label so the user can see the count.
function annotateVisitCounts(src: string, counts: Map<string, number>): string {
  if (!src) return src;
  const lines = src.split("\n");
  for (let i = 0; i < lines.length; i++) {
    for (const [name, count] of counts) {
      if (count <= 1 || !name || name === "__start__" || name === "__end__") continue;
      // Node-definition lines look like `  name(label)`, `  name([label]):::cls`,
      // `  name{label}` etc. We require an opening bracket right after the name
      // so we don't accidentally rewrite edge lines like `name --> other`.
      const m = lines[i].match(new RegExp(`^(\\s*)${escapeRegex(name)}\\s*([(\\[{])`));
      if (!m) continue;
      const head = m[0];
      const rest = lines[i].slice(head.length);
      const clsIdx = rest.indexOf(":::");
      const segment = clsIdx >= 0 ? rest.slice(0, clsIdx) : rest;
      const suffix = clsIdx >= 0 ? rest.slice(clsIdx) : "";
      const closeIdx = Math.max(
        segment.lastIndexOf(")"),
        segment.lastIndexOf("]"),
        segment.lastIndexOf("}"),
      );
      if (closeIdx < 0) continue;
      const before = segment.slice(0, closeIdx);
      const closing = segment.slice(closeIdx);
      // Avoid double-annotating if the source already contains our badge.
      if (before.includes(`×${count}`)) break;
      lines[i] = head + before + `<br/>×${count}` + closing + suffix;
      break;
    }
  }
  return lines.join("\n");
}

// Append `:::visited` class assignments so traversed nodes are highlighted,
// then layer the count annotations on top.
function highlightMermaid(src: string, counts: Map<string, number>): string {
  if (!src || counts.size === 0) return src;
  const annotated = annotateVisitCounts(src, counts);
  const lines = annotated.split("\n");
  const visitedList = [...counts.keys()].filter(n => n && n !== "__start__" && n !== "__end__");
  if (visitedList.length === 0) return annotated;
  lines.push("classDef visited fill:#1d4ed8,stroke:#60a5fa,color:#f8fafc,stroke-width:2px;");
  lines.push(`class ${visitedList.join(",")} visited;`);
  return lines.join("\n");
}

export default function FlowPanel({ trace, topology }: Props) {
  const rows = useMemo(() => buildRows(trace), [trace]);
  const counts = useMemo(() => visitedNodeCounts(trace), [trace]);
  const hasContent = rows.length > 0 || !!topology;

  return (
    <div className="h-full flex flex-col">
      {topology && (
        <div className="border-b border-border shrink-0 max-h-[40%] overflow-auto">
          <MermaidView source={highlightMermaid(topology.mermaid, counts)} />
        </div>
      )}
      <ScrollArea className="flex-1">
        <div className="p-2 space-y-1">
          {!hasContent && (
            <p className="text-muted-foreground text-xs py-4 text-center">
              Trace events will appear here while the script runs.
            </p>
          )}
          {rows.map(row => <TraceRowView key={row.key} row={row} />)}
        </div>
      </ScrollArea>
    </div>
  );
}


// ── Single trace row ────────────────────────────────────────────────────────

function TraceRowView({ row }: { row: TraceRow }) {
  const [expanded, setExpanded] = useState(false);
  const hasDetails = Boolean(
    row.input !== undefined || row.output !== undefined || row.error || (row.log !== undefined && row.log !== null)
  );

  const Icon = ICONS[row.kind] ?? Box;
  const color = COLORS[row.kind] ?? "text-foreground";

  return (
    <div className="rounded border border-border/50 bg-secondary/10 hover:bg-secondary/20 transition-colors">
      <button
        onClick={() => hasDetails && setExpanded(v => !v)}
        className={cn(
          "w-full flex items-center gap-2 px-2 py-1.5 text-left text-xs",
          hasDetails && "cursor-pointer",
        )}
      >
        {hasDetails ? (
          expanded ? <ChevronDown className="h-3 w-3 shrink-0 text-muted-foreground" />
                   : <ChevronRight className="h-3 w-3 shrink-0 text-muted-foreground" />
        ) : <span className="w-3" />}
        <Icon className={cn("h-3 w-3 shrink-0", color)} />
        {row.step !== undefined && (
          <span className="text-muted-foreground/60 tabular-nums text-[10px]">#{row.step}</span>
        )}
        <span className={cn("font-mono font-medium", color)}>{row.name}</span>
        <span className="text-muted-foreground/60 text-[10px]">{KIND_LABEL[row.kind]}</span>
        {row.isOpen && (
          <span className="text-blue-400 text-[10px] animate-pulse">running…</span>
        )}
        {row.error && (
          <span className="text-destructive text-[10px]">error</span>
        )}
        <span className="ml-auto text-muted-foreground/60 text-[10px] tabular-nums">
          {row.durationMs != null ? `${row.durationMs} ms` : ""}
        </span>
      </button>

      {expanded && hasDetails && (
        <div className="px-2 pb-2 pt-0 space-y-1.5 text-[11px]">
          {row.input !== undefined && <JsonBlock label="input"  value={row.input} />}
          {row.output !== undefined && <JsonBlock label="output" value={row.output} />}
          {row.log !== undefined && row.log !== null && <JsonBlock label="log" value={row.log} />}
          {row.error && (
            <div>
              <div className="text-destructive font-semibold text-[10px] mb-0.5">error</div>
              <pre className="bg-destructive/10 rounded px-2 py-1 text-destructive whitespace-pre-wrap break-words">
                {row.error}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

interface ChatMessage { role: string; content: unknown }

function isChatMessageArray(v: unknown): v is ChatMessage[] {
  return Array.isArray(v)
    && v.length > 0
    && v.every(m => m && typeof m === "object" && "role" in m && "content" in m);
}

const ROLE_TONE: Record<string, string> = {
  human: "text-emerald-300",
  user: "text-emerald-300",
  ai: "text-blue-300",
  assistant: "text-blue-300",
  system: "text-amber-300",
  tool: "text-violet-300",
};

function ChatView({ messages }: { messages: ChatMessage[] }) {
  return (
    <div className="space-y-1.5">
      {messages.map((m, i) => {
        const tone = ROLE_TONE[m.role.toLowerCase()] ?? "text-muted-foreground";
        const text = typeof m.content === "string" ? m.content : JSON.stringify(m.content, null, 2);
        return (
          <div key={i} className="bg-secondary/40 rounded px-2 py-1">
            <div className={cn("text-[10px] uppercase tracking-wide mb-0.5", tone)}>{m.role}</div>
            <div className="text-foreground/85 whitespace-pre-wrap break-words font-mono">{text}</div>
          </div>
        );
      })}
    </div>
  );
}

function JsonBlock({ label, value }: { label: string; value: unknown }) {
  const [expanded, setExpanded] = useState(false);

  // Chat-message arrays get a friendlier rendering.
  const chatMsgs = isChatMessageArray(value) ? (value as ChatMessage[]) : null;
  const text = !chatMsgs && (typeof value === "string" ? value : JSON.stringify(value, null, 2));
  const charCount = chatMsgs
    ? chatMsgs.reduce((n, m) => n + (typeof m.content === "string" ? m.content.length : JSON.stringify(m.content).length), 0)
    : (text || "").length;

  // Detect truncated payload from the backend so we can surface it.
  const truncated = Boolean(value && typeof value === "object" && (value as { __truncated__?: boolean }).__truncated__);

  // Heuristic: collapse anything tall or > ~400 chars by default.
  const lineCount = text ? text.split("\n").length : (chatMsgs?.length ?? 0) * 4;
  const isLarge = charCount > 400 || lineCount > 8;

  return (
    <div>
      <div className="flex items-center gap-2 mb-0.5">
        <span className="text-muted-foreground/60 text-[10px] uppercase tracking-wide">{label}</span>
        <span className="text-muted-foreground/40 text-[10px] tabular-nums">{charCount.toLocaleString()} chars</span>
        {truncated && (
          <span className="text-amber-400/80 text-[10px]">truncated</span>
        )}
        {isLarge && (
          <button onClick={() => setExpanded(v => !v)}
            className="ml-auto text-[10px] text-muted-foreground hover:text-foreground inline-flex items-center gap-0.5">
            {expanded ? <><ChevronDown className="h-3 w-3" />collapse</> : <><ChevronRight className="h-3 w-3" />expand</>}
          </button>
        )}
      </div>
      <div
        className={cn(
          "relative rounded text-[11px]",
          isLarge && !expanded && "max-h-32 overflow-hidden",
          isLarge && expanded && "max-h-[60vh] overflow-auto",
        )}
      >
        {chatMsgs
          ? <ChatView messages={chatMsgs} />
          : <pre className="bg-secondary/40 rounded px-2 py-1 text-muted-foreground whitespace-pre-wrap break-words font-mono">{text}</pre>
        }
        {isLarge && !expanded && (
          <div className="pointer-events-none absolute inset-x-0 bottom-0 h-6 bg-gradient-to-t from-background to-transparent" />
        )}
      </div>
    </div>
  );
}

const ICONS = {
  node: Box,
  tool: Wrench,
  agent_action: Bot,
  agent_finish: Flag,
  llm: Brain,
} as const;

const COLORS = {
  node: "text-violet-400",
  tool: "text-emerald-400",
  agent_action: "text-amber-400",
  agent_finish: "text-blue-400",
  llm: "text-sky-400",
} as const;

const KIND_LABEL = {
  node: "node",
  tool: "tool",
  agent_action: "agent",
  agent_finish: "finish",
  llm: "llm",
} as const;
