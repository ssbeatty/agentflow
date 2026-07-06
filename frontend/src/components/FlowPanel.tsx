"use client";
import { useMemo, useState, type MouseEvent } from "react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { ChevronDown, ChevronRight, Wrench, Box, Bot, Flag, Brain, Copy, Check, BookOpen } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { TraceEvent, GraphTopology } from "@/lib/types";
import { cn } from "@/lib/utils";
import MermaidView from "@/components/MermaidView";

interface Props {
  trace: TraceEvent[];
  topology: GraphTopology | null;
}

// Pair start/end events by run_id for compact rendering.
export interface TraceRow {
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

export function buildRows(events: TraceEvent[]): TraceRow[] {
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

// LangGraph's `draw_mermaid()` bakes in its own light classDefs
// (`classDef default fill:#f2f0ff`, `last fill:#bfb6fc`, `first fill-opacity:0`).
// Those near-white fills collide with our dark theme's light node text
// (`#e5e7eb` → light-on-near-white = invisible). Rewrite each to a high-contrast
// dark fill so un-visited nodes read clearly regardless of panel background.
const _NODE_CLASSDEFS: Record<string, string> = {
  default: "classDef default fill:#1e293b,stroke:#64748b,color:#e5e7eb,line-height:1.2;",
  first:   "classDef first fill:#0f172a,stroke:#64748b,color:#e5e7eb;",
  last:    "classDef last fill:#334155,stroke:#94a3b8,color:#f8fafc;",
};

function themeMermaid(src: string): string {
  if (!src) return src;
  let lines = src.split("\n");
  for (const [name, repl] of Object.entries(_NODE_CLASSDEFS)) {
    const re = new RegExp(`^\\s*classDef\\s+${name}\\b.*$`);
    let replaced = false;
    lines = lines.map(l => {
      if (!replaced && re.test(l)) { replaced = true; return repl; }
      return l;
    });
    if (!replaced) lines.push(repl);
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
  const { t } = useTranslation("scriptPanels");
  const rows = useMemo(() => buildRows(trace), [trace]);
  const counts = useMemo(() => visitedNodeCounts(trace), [trace]);
  const hasContent = rows.length > 0 || !!topology;

  return (
    <div className="h-full flex flex-col">
      {topology && (
        <div className="border-b border-border shrink-0 max-h-[40%] overflow-auto">
          <MermaidView source={highlightMermaid(themeMermaid(topology.mermaid), counts)} />
        </div>
      )}
      <ScrollArea className="flex-1">
        <div className="p-2 space-y-1">
          {!hasContent && (
            <p className="text-muted-foreground text-xs py-4 text-center">
              {t("flowPanel.empty")}
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
  const { t } = useTranslation("scriptPanels");
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
        <span className="text-muted-foreground/60 text-[10px]">{t(`flowPanel.kindLabels.${row.kind}`)}</span>
        {row.isOpen && (
          <span className="text-blue-400 text-[10px] animate-pulse">{t("flowPanel.row.running")}</span>
        )}
        {row.error && (
          <span className="text-destructive text-[10px]">{t("flowPanel.row.error")}</span>
        )}
        <span className="ml-auto text-muted-foreground/60 text-[10px] tabular-nums">
          {row.durationMs != null ? t("flowPanel.row.durationMs", { ms: row.durationMs }) : ""}
        </span>
      </button>

      {expanded && hasDetails && (
        <div className="px-2 pb-2 pt-0 space-y-1.5 text-[11px]">
          {row.input !== undefined && <JsonBlock label="input"  value={row.input} />}
          {row.output !== undefined && <JsonBlock label="output" value={row.output} />}
          {row.log !== undefined && row.log !== null && <JsonBlock label="log" value={row.log} />}
          {row.error && (
            <div>
              <div className="text-destructive font-semibold text-[10px] mb-0.5">{t("flowPanel.row.error")}</div>
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

// The backend caps oversized node/tool payloads (see agentflow/_tracer.py::_truncate)
// into this shape. `preview` is the *already-serialized* head of the JSON string —
// it must be rendered verbatim, never JSON.stringify'd again (that double-escapes
// every quote/newline into unreadable `\"` / `\\n` soup).
interface TruncMarker { __truncated__?: boolean; preview?: string; original_bytes?: number }

function JsonBlock({ label, value }: { label: string; value: unknown }) {
  const { t } = useTranslation("scriptPanels");
  const [expanded, setExpanded] = useState(false);
  const [copied, setCopied] = useState(false);

  const trunc = (value && typeof value === "object" && (value as TruncMarker).__truncated__)
    ? (value as TruncMarker) : null;

  // Chat-message arrays get a friendlier rendering.
  const chatMsgs = !trunc && isChatMessageArray(value) ? (value as ChatMessage[]) : null;

  // For truncated payloads show the raw preview text as-is (cut-off but readable JSON).
  const text = trunc
    ? (trunc.preview ?? "")
    : (!chatMsgs ? (typeof value === "string" ? value : JSON.stringify(value, null, 2)) : "");

  const shownChars = chatMsgs
    ? chatMsgs.reduce((n, m) => n + (typeof m.content === "string" ? m.content.length : JSON.stringify(m.content).length), 0)
    : (text || "").length;
  // For truncated blobs the chip shows the *real* size; otherwise the shown size.
  const totalChars = trunc?.original_bytes ?? shownChars;

  // Heuristic: collapse anything tall or > ~400 chars by default; truncated is always large.
  const lineCount = text ? text.split("\n").length : (chatMsgs?.length ?? 0) * 4;
  const isLarge = Boolean(trunc) || shownChars > 400 || lineCount > 8;

  const copyText = chatMsgs ? JSON.stringify(value, null, 2) : text;
  const onCopy = (e: MouseEvent) => {
    e.stopPropagation();
    navigator.clipboard?.writeText(copyText)
      .then(() => { setCopied(true); setTimeout(() => setCopied(false), 1200); })
      .catch(() => {});
  };

  return (
    <div>
      {/* Controls sit just after the label — NOT ml-auto'd to the far right —
          so the panel's scrollbar / right column can never overlap them. That
          right-edge overlap was the "expand button disappears" report: the button
          was there, just hidden under the right-side bar. */}
      <div className="flex items-center gap-2 mb-0.5">
        <span className="text-muted-foreground/60 text-[10px] uppercase tracking-wide">{label}</span>
        <span className="text-muted-foreground/40 text-[10px] tabular-nums">{t("flowPanel.jsonBlock.chars", { count: totalChars.toLocaleString() })}</span>
        <button onClick={onCopy} title={t("flowPanel.jsonBlock.copyTitle")}
          className="text-[10px] text-muted-foreground hover:text-foreground inline-flex items-center gap-0.5">
          {copied ? <Check className="h-3 w-3 text-emerald-400" /> : <Copy className="h-3 w-3" />}
        </button>
        {isLarge && (
          <button onClick={() => setExpanded(v => !v)}
            className="text-[10px] text-muted-foreground hover:text-foreground inline-flex items-center gap-0.5">
            {expanded ? <><ChevronDown className="h-3 w-3" />{t("flowPanel.jsonBlock.collapse")}</> : <><ChevronRight className="h-3 w-3" />{t("flowPanel.jsonBlock.expand")}</>}
          </button>
        )}
        {trunc && (
          <span className="text-amber-400/80 text-[10px]">{t("flowPanel.jsonBlock.truncated", { shown: shownChars.toLocaleString() })}</span>
        )}
      </div>
      <div
        onClick={() => { if (isLarge && !expanded) setExpanded(true); }}
        className={cn(
          "relative rounded text-[11px]",
          isLarge && !expanded && "max-h-32 overflow-hidden cursor-pointer",
          isLarge && expanded && "max-h-[60vh] overflow-auto",
        )}
      >
        {chatMsgs
          ? <ChatView messages={chatMsgs} />
          : <pre className="bg-secondary/40 rounded px-2 py-1 text-muted-foreground whitespace-pre-wrap break-words font-mono">{text}</pre>
        }
        {isLarge && !expanded && (
          <div className="pointer-events-none absolute inset-x-0 bottom-0 h-8 bg-gradient-to-t from-background to-transparent flex items-end justify-center">
            <span className="text-[10px] text-muted-foreground/70 pb-0.5">{t("flowPanel.jsonBlock.clickToExpand")}</span>
          </div>
        )}
      </div>
    </div>
  );
}

const ICONS = {
  node: Box,
  tool: Wrench,
  skill: BookOpen,
  agent_action: Bot,
  agent_finish: Flag,
  llm: Brain,
} as const;

const COLORS = {
  node: "text-violet-400",
  tool: "text-emerald-400",
  skill: "text-fuchsia-400",
  agent_action: "text-amber-400",
  agent_finish: "text-blue-400",
  llm: "text-sky-400",
} as const;
