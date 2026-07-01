"use client";
import { useState } from "react";
import {
  Wrench, Brain, Box, Bot, Flag, ChevronRight, ChevronDown,
  Loader2, Check, AlertCircle, Sparkles, BookOpen,
} from "lucide-react";
import type { TraceEvent } from "@/lib/types";
import { buildRows, type TraceRow } from "@/components/FlowPanel";
import { cn } from "@/lib/utils";

// Cherry-Studio-style inline timeline of an agent's internal steps.
//
// Instead of dumping every tool below the answer, we render one collapsible
// block placed ABOVE the answer: a summary header (· N 工具 · M 思考) that folds
// the whole thing, and a chronological list of cards — LLM turns shown as
// "深度思考", tool/node calls shown by name with a status + duration. Each card
// expands to its input/output. Order comes from buildRows() (same start/end
// folding the Flow tab uses), so it reads top-to-bottom as it happened.

const ICONS = { node: Box, tool: Wrench, skill: BookOpen, agent_action: Bot, agent_finish: Flag, llm: Brain } as const;
const COLORS = {
  node: "text-violet-400",
  tool: "text-emerald-400",
  skill: "text-fuchsia-400",
  agent_action: "text-amber-400",
  agent_finish: "text-blue-400",
  llm: "text-sky-400",
} as const;

function fmt(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "string") return v;
  try { return JSON.stringify(v, null, 2); } catch { return String(v); }
}

function durationLabel(ms?: number | null): string {
  if (ms == null) return "";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
}

function titleFor(row: TraceRow): string {
  if (row.kind === "llm") {
    if (row.isOpen) return "思考中…";
    const d = durationLabel(row.durationMs);
    return d ? `深度思考 · 用时 ${d}` : "深度思考";
  }
  if (row.kind === "agent_finish") return row.name || "完成";
  return row.name;
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
  const isTool = row.kind === "tool" || row.kind === "skill" || row.kind === "agent_action";

  return (
    <div className="rounded-lg border border-border/40 bg-secondary/15">
      <button
        onClick={() => hasDetails && setOpen((o) => !o)}
        className={cn(
          "w-full flex items-center gap-2 px-2.5 py-1.5 text-left text-xs",
          hasDetails && "cursor-pointer",
        )}
      >
        {hasDetails
          ? (open ? <ChevronDown className="h-3 w-3 shrink-0 text-muted-foreground" />
                  : <ChevronRight className="h-3 w-3 shrink-0 text-muted-foreground" />)
          : <span className="w-3 shrink-0" />}
        <Icon className={cn("h-3.5 w-3.5 shrink-0", color)} />
        <span className="truncate font-medium text-foreground/90">{titleFor(row)}</span>
        {isTool && <span className="text-[10px] text-muted-foreground/50 shrink-0">工具</span>}
        {row.kind === "node" && <span className="text-[10px] text-muted-foreground/50 shrink-0">节点</span>}

        <span className="ml-auto flex items-center gap-1.5 shrink-0">
          {row.durationMs != null && row.kind !== "llm" && (
            <span className="text-muted-foreground/50 text-[10px] tabular-nums">{durationLabel(row.durationMs)}</span>
          )}
          {row.isOpen
            ? <Loader2 className="h-3 w-3 text-blue-400 animate-spin" />
            : row.error
              ? <span className="flex items-center gap-0.5 text-destructive text-[10px]"><AlertCircle className="h-3 w-3" />失败</span>
              : <Check className="h-3 w-3 text-emerald-500/80" />}
        </span>
      </button>
      {open && hasDetails && (
        <div className="px-2.5 pb-2 space-y-1">
          <DetailBlock label="input" value={row.input} />
          <DetailBlock label="output" value={row.output} />
          {row.error && <DetailBlock label="error" value={row.error} error />}
        </div>
      )}
    </div>
  );
}

export default function AgentTraceInline({ traces }: { traces: TraceEvent[] }) {
  const rows = buildRows(traces);
  const running = rows.some((r) => r.isOpen);
  const [collapsed, setCollapsed] = useState(false);

  if (rows.length === 0) return null;

  const toolCount = rows.filter((r) => r.kind === "tool" || r.kind === "agent_action").length;
  const thinkCount = rows.filter((r) => r.kind === "llm").length;

  return (
    <div className="w-full max-w-[680px] rounded-xl border border-border/50 bg-secondary/10 overflow-hidden">
      <button
        onClick={() => setCollapsed((c) => !c)}
        className="w-full flex items-center gap-1.5 px-3 py-2 text-[11px] hover:bg-secondary/20 transition-colors"
      >
        {running
          ? <Loader2 className="h-3.5 w-3.5 text-blue-400 animate-spin" />
          : <Sparkles className="h-3.5 w-3.5 text-primary/70" />}
        <span className="font-medium text-foreground/80">{running ? "正在思考…" : "Agent 过程"}</span>
        <span className="text-muted-foreground/60">
          {toolCount > 0 && <> · {toolCount} 个工具调用</>}
          {thinkCount > 0 && <> · {thinkCount} 次思考</>}
        </span>
        {collapsed
          ? <ChevronRight className="h-3.5 w-3.5 ml-auto text-muted-foreground" />
          : <ChevronDown className="h-3.5 w-3.5 ml-auto text-muted-foreground" />}
      </button>
      {!collapsed && (
        <div className="px-2 pb-2 space-y-1">
          {rows.map((row) => <Row key={row.key} row={row} />)}
        </div>
      )}
    </div>
  );
}
