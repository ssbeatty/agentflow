"use client";
import { useMemo, useState } from "react";
import {
  Wrench, Brain, Box, Bot, Flag, ChevronRight, ChevronDown, Loader2, Check, AlertCircle,
} from "lucide-react";
import type { TraceEvent } from "@/lib/types";
import { buildRows, type TraceRow } from "@/components/FlowPanel";
import { cn } from "@/lib/utils";

// Compact, chat-friendly view of an agent's internal steps (tool calls, LLM
// turns, graph nodes). Tool calls are shown by default — like Cherry Studio —
// with model/node steps tucked behind a toggle. Reuses FlowPanel's start/end
// folding so behaviour matches the script-run Flow tab.

const ICONS = { node: Box, tool: Wrench, agent_action: Bot, agent_finish: Flag, llm: Brain } as const;
const COLORS = {
  node: "text-violet-400",
  tool: "text-emerald-400",
  agent_action: "text-amber-400",
  agent_finish: "text-blue-400",
  llm: "text-sky-400",
} as const;

function fmt(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "string") return v;
  try { return JSON.stringify(v, null, 2); } catch { return String(v); }
}

function DetailBlock({ label, value, error }: { label: string; value: unknown; error?: boolean }) {
  const text = fmt(value);
  if (!text) return null;
  return (
    <div>
      <div className="text-muted-foreground/60 text-[10px] uppercase tracking-wide mb-0.5">{label}</div>
      <pre className={cn(
        "rounded px-2 py-1 whitespace-pre-wrap break-words font-mono text-[11px] max-h-48 overflow-auto",
        error ? "bg-destructive/10 text-destructive" : "bg-secondary/40 text-muted-foreground",
      )}>{text}</pre>
    </div>
  );
}

function Row({ row }: { row: TraceRow }) {
  const [open, setOpen] = useState(false);
  const Icon = ICONS[row.kind] ?? Box;
  const color = COLORS[row.kind] ?? "text-foreground";
  const hasDetails = row.input !== undefined || row.output !== undefined || !!row.error;

  return (
    <div className="rounded border border-border/40 bg-secondary/15">
      <button
        onClick={() => hasDetails && setOpen(o => !o)}
        className={cn("w-full flex items-center gap-1.5 px-2 py-1 text-left text-[11px]", hasDetails && "cursor-pointer")}
      >
        {hasDetails
          ? (open ? <ChevronDown className="h-3 w-3 shrink-0 text-muted-foreground" />
                  : <ChevronRight className="h-3 w-3 shrink-0 text-muted-foreground" />)
          : <span className="w-3 shrink-0" />}
        <Icon className={cn("h-3 w-3 shrink-0", color)} />
        <span className={cn("font-mono font-medium truncate", color)}>{row.name}</span>
        {row.isOpen
          ? <Loader2 className="h-3 w-3 shrink-0 text-blue-400 animate-spin" />
          : row.error
            ? <AlertCircle className="h-3 w-3 shrink-0 text-destructive" />
            : <Check className="h-3 w-3 shrink-0 text-emerald-500/80" />}
        <span className="ml-auto text-muted-foreground/50 text-[10px] tabular-nums shrink-0">
          {row.durationMs != null ? `${row.durationMs} ms` : ""}
        </span>
      </button>
      {open && hasDetails && (
        <div className="px-2 pb-1.5 space-y-1">
          <DetailBlock label="input" value={row.input} />
          <DetailBlock label="output" value={row.output} />
          {row.error && <DetailBlock label="error" value={row.error} error />}
        </div>
      )}
    </div>
  );
}

export default function AgentTraceInline({ traces }: { traces: TraceEvent[] }) {
  const rows = useMemo(() => buildRows(traces), [traces]);
  const [showAll, setShowAll] = useState(false);

  if (rows.length === 0) return null;

  const isTool = (r: TraceRow) => r.kind === "tool" || r.kind === "agent_action";
  const toolRows = rows.filter(isTool);
  const otherRows = rows.filter(r => !isTool(r));
  const running = rows.some(r => r.isOpen);
  // If there are no tool calls at all, just show every step (it's an LLM-only turn).
  const visible = showAll || toolRows.length === 0 ? rows : toolRows;

  return (
    <div className="mt-1 w-full max-w-[680px] space-y-1">
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-muted-foreground/70">
        <Wrench className="h-3 w-3" />
        <span>Agent steps</span>
        <span className="text-muted-foreground/50 normal-case tracking-normal">
          · {toolRows.length} tool{toolRows.length !== 1 ? "s" : ""}
        </span>
        {running && <Loader2 className="h-3 w-3 animate-spin text-blue-400" />}
      </div>
      {visible.map(row => <Row key={row.key} row={row} />)}
      {toolRows.length > 0 && otherRows.length > 0 && (
        <button
          onClick={() => setShowAll(s => !s)}
          className="text-[10px] text-muted-foreground hover:text-foreground inline-flex items-center gap-0.5"
        >
          {showAll
            ? <><ChevronDown className="h-3 w-3" />Hide model/node steps</>
            : <><ChevronRight className="h-3 w-3" />Show {otherRows.length} model/node step{otherRows.length !== 1 ? "s" : ""}</>}
        </button>
      )}
    </div>
  );
}
