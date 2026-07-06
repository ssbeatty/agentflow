"use client";
import { useState } from "react";
import { Wrench, BookOpen, ChevronRight, ChevronDown, Loader2, Check, AlertTriangle } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { TraceEvent, WsEvent } from "@/lib/types";
import { buildRows, type TraceRow } from "@/components/FlowPanel";
import { MarkdownContent } from "@/components/Markdown";
import { splitThink, ThinkBlock } from "@/components/ThinkBlock";
import { cn } from "@/lib/utils";

// A Claude-Code-style chronological transcript of one agent turn: reasoning →
// spoken text → tool call → more text → …, in the order it actually happened.
// Shared by the Chat page (/converse) and the in-editor AI assistant panel.

export interface TextBlock { type: "text"; content: string; }
export interface ToolBlock {
  type: "tool"; runId: string; name: string; kind: string;
  input?: unknown; output?: unknown; error?: string; done: boolean; durationMs?: number | null;
}
export type Block = TextBlock | ToolBlock;

let _rid = 0;
function nextRid() { return `rid-${_rid++}`; }

// ── Live construction from the WS event stream (token + tool traces, in order) ──
function pushToken(blocks: Block[], text: string): Block[] {
  const last = blocks[blocks.length - 1];
  if (last && last.type === "text") {
    return [...blocks.slice(0, -1), { ...last, content: last.content + text }];
  }
  return [...blocks, { type: "text", content: text }];
}
function startTool(blocks: Block[], t: TraceEvent): Block[] {
  return [
    ...blocks,
    { type: "tool", runId: String(t.run_id ?? nextRid()), name: t.name ?? "tool", kind: t.kind ?? "tool", input: t.input, done: false },
    { type: "text", content: "" },
  ];
}
function endTool(blocks: Block[], t: TraceEvent): Block[] {
  const rid = String(t.run_id ?? "");
  return blocks.map((b) =>
    b.type === "tool" && b.runId === rid
      ? { ...b, output: t.output, error: t.error, done: true, durationMs: t.duration_ms }
      : b
  );
}

/** Fold one WS event into the running block list (call in the WS onmessage handler). */
export function reduceEvent(blocks: Block[], evt: WsEvent): Block[] {
  if (evt.type === "token") return pushToken(blocks, evt.content);
  if (evt.type === "trace") {
    const t = evt as TraceEvent;
    if (!["tool", "skill"].includes(t.kind)) return blocks;
    if (t.phase === "start") return startTool(blocks, t);
    if (t.phase === "end" || t.phase === "error") return endTool(blocks, t);
  }
  return blocks;
}

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

/** Reconstruct the timeline from persisted trace events (reload / history). */
export function blocksFromTraces(traces: TraceEvent[]): Block[] {
  const rows: TraceRow[] = buildRows(traces);
  const out: Block[] = [];
  for (const row of rows) {
    if (row.kind === "tool" || row.kind === "skill") {
      out.push({
        type: "tool", runId: row.key, name: row.name, kind: row.kind,
        input: row.input, output: row.output, error: row.error,
        done: !row.isOpen, durationMs: row.durationMs,
      });
    } else if (row.kind === "llm") {
      const text = llmText(row.output).trim();
      if (text) out.push({ type: "text", content: text });
    }
    // node / agent_action / agent_finish → not part of the readable story
  }
  return out;
}

/** The agent's spoken answer (no <think>, no tool noise) — for history/copy. */
export function answerFromBlocks(blocks: Block[]): string {
  return blocks
    .filter((b): b is TextBlock => b.type === "text")
    .map((b) => splitThink(b.content).answer)
    .filter(Boolean)
    .join("\n\n");
}

function durationLabel(ms?: number | null): string {
  if (ms == null) return "";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
}
function fmt(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "string") return v;
  try { return JSON.stringify(v, null, 2); } catch { return String(v); }
}

function Detail({ label, value, error }: { label: string; value: unknown; error?: boolean }) {
  const text = fmt(value);
  if (!text) return null;
  return (
    <div>
      <div className="text-muted-foreground/60 text-[10px] uppercase tracking-wide mb-0.5">{label}</div>
      <pre className={cn("rounded px-2 py-1 whitespace-pre-wrap break-words font-mono text-[11px] max-h-40 overflow-auto",
        error ? "bg-destructive/10 text-destructive" : "bg-background/60 text-muted-foreground")}>{text}</pre>
    </div>
  );
}

export function ToolCard({ block }: { block: ToolBlock }) {
  const { t } = useTranslation("scriptPanels");
  const [open, setOpen] = useState(false);
  const isSkill = block.kind === "skill";
  const a = isSkill
    ? { border: "border-fuchsia-500/25", bg: "bg-fuchsia-500/[0.04]", icon: "text-fuchsia-400", Icon: BookOpen, label: t("agentTimeline.toolCard.skillLabel") }
    : { border: "border-emerald-500/25", bg: "bg-emerald-500/[0.04]", icon: "text-emerald-400", Icon: Wrench, label: t("agentTimeline.toolCard.toolLabel") };
  return (
    <div className={cn("rounded-lg border w-full max-w-[680px]", a.border, a.bg)}>
      <button onClick={() => setOpen((o) => !o)} className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-left">
        <a.Icon className={cn("h-3.5 w-3.5 shrink-0", a.icon)} />
        <span className="font-mono font-medium text-foreground/90 truncate">{block.name}</span>
        <span className="text-[10px] text-muted-foreground/50 shrink-0">{a.label}</span>
        <span className="ml-auto flex items-center gap-1.5 shrink-0">
          {block.durationMs != null && <span className="text-[10px] text-muted-foreground/50 tabular-nums">{durationLabel(block.durationMs)}</span>}
          {!block.done
            ? <Loader2 className="h-3 w-3 text-blue-400 animate-spin" />
            : block.error
              ? <AlertTriangle className="h-3 w-3 text-destructive" />
              : <Check className={cn("h-3 w-3", isSkill ? "text-fuchsia-500/80" : "text-emerald-500/80")} />}
          {open ? <ChevronDown className="h-3 w-3 text-muted-foreground" /> : <ChevronRight className="h-3 w-3 text-muted-foreground" />}
        </span>
      </button>
      {open && (
        <div className="px-3 pb-2 pt-1.5 space-y-1.5 border-t border-border/20">
          <Detail label={t("agentTimeline.toolCard.argumentsLabel")} value={block.input} />
          <Detail label={t("agentTimeline.toolCard.resultLabel")} value={block.output} />
          {block.error && <Detail label={t("agentTimeline.toolCard.errorLabel")} value={block.error} error />}
        </div>
      )}
    </div>
  );
}

export default function AgentTimeline({
  blocks, streaming = false, leadingReasoning,
}: {
  blocks: Block[];
  streaming?: boolean;
  /** Reasoning to show as a leading block (reload path, where it isn't inline). */
  leadingReasoning?: string;
}) {
  const { t } = useTranslation("scriptPanels");
  const visible = blocks.some((b) => b.type === "tool" || (b.type === "text" && b.content.trim()));
  return (
    <div className="space-y-2">
      {leadingReasoning && leadingReasoning.trim() && <ThinkBlock reasoning={leadingReasoning} thinking={false} />}
      {blocks.map((b, i) => {
        if (b.type === "tool") return <ToolCard key={b.runId} block={b} />;
        const { reasoning, answer, thinking } = splitThink(b.content);
        if (!reasoning && !answer) return null;
        return (
          <div key={`t${i}`} className="space-y-2">
            {reasoning && <ThinkBlock reasoning={reasoning} thinking={thinking} />}
            {answer && <div className="text-sm"><MarkdownContent text={answer} /></div>}
          </div>
        );
      })}
      {streaming && !visible && !leadingReasoning && (
        <span className="flex items-center gap-1.5 text-muted-foreground">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /><span className="text-xs">{t("agentTimeline.generating")}</span>
        </span>
      )}
    </div>
  );
}
