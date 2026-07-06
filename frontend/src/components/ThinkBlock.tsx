"use client";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, Brain, ChevronDown, ChevronRight } from "lucide-react";

// Shared reasoning ("chain-of-thought") helpers, used by both the Chat page
// (/converse) and the in-editor AI assistant panel. Single source of truth so
// the two renderers can't drift.

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
export function splitThink(content: string): { reasoning: string; answer: string; thinking: boolean } {
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
export function ThinkBlock({ reasoning, thinking }: { reasoning: string; thinking: boolean }) {
  const { t } = useTranslation("assistant");
  const [userOpen, setUserOpen] = useState<boolean | null>(null);
  const open = userOpen ?? thinking;
  const bodyRef = useRef<HTMLDivElement>(null);
  // Keep the newest reasoning in view while the model is actively thinking.
  useEffect(() => {
    if (open && thinking && bodyRef.current) {
      bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
    }
  }, [reasoning, open, thinking]);
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
        <span className="font-medium text-foreground/80">{thinking ? t("thinkBlock.thinking") : t("thinkBlock.thoughtProcess")}</span>
        {open
          ? <ChevronDown className="h-3.5 w-3.5 ml-auto text-muted-foreground" />
          : <ChevronRight className="h-3.5 w-3.5 ml-auto text-muted-foreground" />}
      </button>
      {open && (
        <div ref={bodyRef} className="px-3 pb-2.5 pt-1 border-t border-border/40 text-xs text-muted-foreground/90 whitespace-pre-wrap break-words max-h-72 overflow-auto leading-relaxed">
          {reasoning}
        </div>
      )}
    </div>
  );
}
