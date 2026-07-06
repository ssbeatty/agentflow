"use client";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Wrench, ChevronRight, ChevronDown, Loader2, Check, AlertCircle, Sparkles, BookOpen,
} from "lucide-react";
import type { TraceEvent } from "@/lib/types";
import { buildRows, type TraceRow } from "@/components/FlowPanel";
import { MarkdownContent } from "@/components/Markdown";
import { cn } from "@/lib/utils";

// One collapsible "Agent trace" block under an assistant message. Collapsed by
// default to a single summary line; expanded it shows the readable story of the
// turn, reconstructed from the trace in chronological order:
//   * the agent's intermediate text returns → rendered as markdown
//   * each tool call → a card showing args + result + status
// The final answer is rendered separately by the chat (authoritative `content`),
// so `excludeLastLlmText` drops the last LLM turn's text to avoid duplicating it.

function fmt(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "string") return v;
  try { return JSON.stringify(v, null, 2); } catch { return String(v); }
}

function durationLabel(ms?: number | null): string {
  if (ms == null) return "";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
}

// Pull the agent's spoken text out of an LLM end event's output.
function llmText(output: unknown): string {
  if (!output) return "";
  if (typeof output === "string") return output;
  if (typeof output === "object") {
    const o = output as Record<string, unknown>;
    if (typeof o.text === "string") return o.text;
    if (o.__truncated__ && typeof o.preview === "string") return o.preview;
  }
  return "";
}

function DetailBlock({ label, value, error }: { label: string; value: unknown; error?: boolean }) {
  const text = fmt(value);
  if (!text) return null;
  return (
    <div>
      <div className="text-muted-foreground/60 text-[10px] uppercase tracking-wide mb-0.5">{label}</div>
      <pre className={cn(
        "rounded px-2 py-1 whitespace-pre-wrap break-words font-mono text-[11px] max-h-56 overflow-auto",
        error ? "bg-destructive/10 text-destructive" : "bg-background/60 text-muted-foreground",
      )}>{text}</pre>
    </div>
  );
}

function ToolCallBox({ row }: { row: TraceRow }) {
  const { t } = useTranslation("assistant");
  const [open, setOpen] = useState(false);
  const isSkill = row.kind === "skill";
  const a = isSkill
    ? { border: "border-fuchsia-500/25", bg: "bg-fuchsia-500/[0.04]", divider: "border-fuchsia-500/15",
        icon: "text-fuchsia-400", Icon: BookOpen, label: t("agentNarrative.label.skill") }
    : { border: "border-emerald-500/25", bg: "bg-emerald-500/[0.04]", divider: "border-emerald-500/15",
        icon: "text-emerald-400", Icon: Wrench, label: t("agentNarrative.label.tool") };
  return (
    <div className={cn("rounded-lg border", a.border, a.bg)}>
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-2 px-3 py-2 text-xs text-left"
      >
        <a.Icon className={cn("h-3.5 w-3.5 shrink-0", a.icon)} />
        <span className="font-mono font-medium text-foreground/90 truncate">{row.name}</span>
        <span className="text-[10px] text-muted-foreground/50 shrink-0">{a.label}</span>
        <span className="ml-auto flex items-center gap-1.5 shrink-0">
          {row.durationMs != null && (
            <span className="text-[10px] text-muted-foreground/50 tabular-nums">{durationLabel(row.durationMs)}</span>
          )}
          {row.isOpen
            ? <Loader2 className="h-3 w-3 text-blue-400 animate-spin" />
            : row.error
              ? <AlertCircle className="h-3 w-3 text-destructive" />
              : <Check className={cn("h-3 w-3", isSkill ? "text-fuchsia-500/80" : "text-emerald-500/80")} />}
          {open ? <ChevronDown className="h-3 w-3 text-muted-foreground" /> : <ChevronRight className="h-3 w-3 text-muted-foreground" />}
        </span>
      </button>
      {open && (
        <div className={cn("px-3 pb-2.5 pt-2 space-y-1.5 border-t", a.divider)}>
          <DetailBlock label={t("agentNarrative.detail.arguments")} value={row.input} />
          <DetailBlock label={t("agentNarrative.detail.result")} value={row.output} />
          {row.error && <DetailBlock label={t("agentNarrative.detail.error")} value={row.error} error />}
        </div>
      )}
    </div>
  );
}

export default function AgentNarrative({
  traces,
  excludeLastLlmText = true,
}: {
  traces: TraceEvent[];
  excludeLastLlmText?: boolean;
}) {
  const { t } = useTranslation("assistant");
  const [expanded, setExpanded] = useState(false);
  const rows = buildRows(traces);

  // Index of the final LLM turn — its text is the answer, rendered elsewhere.
  let lastLlm = -1;
  rows.forEach((r, i) => { if (r.kind === "llm") lastLlm = i; });

  const segments: React.ReactNode[] = [];
  rows.forEach((row, i) => {
    if (row.kind === "tool" || row.kind === "skill" || row.kind === "agent_action") {
      segments.push(<ToolCallBox key={row.key} row={row} />);
    } else if (row.kind === "llm") {
      if (excludeLastLlmText && i === lastLlm) return;
      const text = llmText(row.output).trim();
      if (text) {
        segments.push(
          <div key={row.key} className="text-sm text-muted-foreground px-0.5">
            <MarkdownContent text={text} />
          </div>,
        );
      }
    }
    // node / agent_finish are internal — they don't add to the readable story.
  });

  if (segments.length === 0) return null;

  const toolCount = rows.filter((r) => r.kind === "tool" || r.kind === "agent_action").length;
  const skillCount = rows.filter((r) => r.kind === "skill").length;
  const thinkCount = rows.filter((r) => r.kind === "llm").length;
  const running = rows.some((r) => r.isOpen);

  return (
    <div className="w-full max-w-[680px] rounded-xl border border-border/50 bg-secondary/10 overflow-hidden">
      <button
        onClick={() => setExpanded((e) => !e)}
        className="w-full flex items-center gap-1.5 px-3 py-2 text-[11px] hover:bg-secondary/20 transition-colors"
      >
        {running
          ? <Loader2 className="h-3.5 w-3.5 text-blue-400 animate-spin" />
          : <Sparkles className="h-3.5 w-3.5 text-primary/70" />}
        <span className="font-medium text-foreground/80">{running ? t("agentNarrative.header.running") : t("agentNarrative.header.trace")}</span>
        <span className="text-muted-foreground/60">
          {skillCount > 0 && <> · {t("agentNarrative.summary.skillCount", { count: skillCount })}</>}
          {toolCount > 0 && <> · {t("agentNarrative.summary.toolCount", { count: toolCount })}</>}
          {thinkCount > 0 && <> · {t("agentNarrative.summary.thoughtCount", { count: thinkCount })}</>}
        </span>
        {expanded
          ? <ChevronDown className="h-3.5 w-3.5 ml-auto text-muted-foreground" />
          : <ChevronRight className="h-3.5 w-3.5 ml-auto text-muted-foreground" />}
      </button>
      {expanded && (
        <div className="px-2.5 pb-2.5 pt-1 space-y-2 border-t border-border/40">
          {segments}
        </div>
      )}
    </div>
  );
}
