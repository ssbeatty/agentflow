"use client";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Play, Loader2, Plus, Trash2, Check, X, ChevronDown, ChevronRight, FlaskConical, TrendingUp, TrendingDown, Minus,
} from "lucide-react";
import { toast } from "sonner";
import { evals } from "@/lib/api";
import type { EvalCase, EvalRun, Assertion, AssertionType, EvalCaseResult } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { formatDate } from "@/lib/utils";

const ASSERTION_TYPES: AssertionType[] = ["contains", "not_contains", "regex", "equals", "judge"];

/**
 * The script's Eval tab: a test dataset (input + assertions) + batch runs that
 * grade the script's output into a pass/fail score, comparable across runs.
 * This is the "improve prompt → run eval → don't regress → promote" loop.
 */
export default function EvalPanel({ scriptId }: { scriptId: string }) {
  const { t } = useTranslation("script");
  const [cases, setCases] = useState<EvalCase[]>([]);
  const [runs, setRuns] = useState<EvalRun[]>([]);
  const [selectedRun, setSelectedRun] = useState<EvalRun | null>(null);
  const [running, setRunning] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);

  const loadCases = useCallback(() => {
    evals.listCases(scriptId).then(setCases).catch(() => null);
  }, [scriptId]);

  const loadRuns = useCallback(() => {
    evals.listRuns(scriptId).then((rs) => {
      setRuns(rs);
      // Auto-select the newest run's detail so the result is visible on open.
      if (rs[0]) evals.getRun(rs[0].id).then(setSelectedRun).catch(() => null);
    }).catch(() => null);
  }, [scriptId]);

  useEffect(() => {
    loadCases();
    loadRuns();
  }, [loadCases, loadRuns]);

  // Poll while the selected run is in progress. Keyed on the run's id+status, so
  // it (a) starts as soon as runEval selects a fresh "running" run and, crucially,
  // (b) RESUMES automatically after a remount — switching bottom tabs unmounts
  // this panel, which used to drop the interval and leave a finished eval stuck
  // showing "running" until a manual refresh. On completion it refreshes the
  // history + toasts exactly once.
  useEffect(() => {
    if (!selectedRun || selectedRun.status !== "running") return;
    setRunning(true);
    const id = selectedRun.id;
    const timer = setInterval(async () => {
      try {
        const r = await evals.getRun(id);
        if (r.status === "running") {
          setSelectedRun((cur) => (cur?.id === id ? r : cur));
          return;
        }
        clearInterval(timer);
        setRunning(false);
        setSelectedRun((cur) => (cur?.id === id ? r : cur));
        loadRuns();
        if (r.status === "completed") toast.success(t("eval.toast.done", { passed: r.passed, total: r.total }));
        else toast.error(t("eval.toast.failed"));
      } catch { /* transient error — keep polling */ }
    }, 2000);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedRun?.id, selectedRun?.status, loadRuns, t]);

  // Per-case pass/fail from the selected run, for the badge on each case row.
  const resultByCase: Record<string, EvalCaseResult> = {};
  for (const r of selectedRun?.results_json ?? []) resultByCase[r.case_id] = r;

  const prevRun = runs.find((r) => r.status === "completed" && r.id !== selectedRun?.id);

  async function addCase() {
    try {
      const c = await evals.createCase({
        script_id: scriptId,
        name: t("eval.newCaseName", { n: cases.length + 1 }),
        input_json: "{}",
        assertions: [{ type: "contains", value: "" }],
      });
      setCases((p) => [...p, c]);
      setExpanded(c.id);
    } catch (e) { toast.error(String(e)); }
  }

  async function saveCase(id: string, patch: Partial<EvalCase>) {
    try {
      const updated = await evals.updateCase(id, {
        name: patch.name,
        input_json: patch.input_json,
        assertions: patch.assertions,
      });
      setCases((p) => p.map((c) => (c.id === id ? updated : c)));
    } catch (e) { toast.error(String(e)); }
  }

  async function delCase(id: string) {
    try {
      await evals.deleteCase(id);
      setCases((p) => p.filter((c) => c.id !== id));
    } catch (e) { toast.error(String(e)); }
  }

  async function runEval() {
    setRunning(true);
    try {
      const run = await evals.startRun({ script_id: scriptId });
      setRuns((p) => [run, ...p]);
      setSelectedRun(run);   // status "running" → the polling effect above takes over
    } catch (e) {
      setRunning(false);
      toast.error(String(e));
    }
  }

  return (
    <ScrollArea className="h-full">
      <div className="p-3 space-y-4">
        {/* Header: dataset + run */}
        <div className="flex items-center gap-2">
          <FlaskConical className="h-4 w-4 text-primary" />
          <span className="text-sm font-medium">{t("eval.dataset")}</span>
          <span className="text-[10px] text-muted-foreground/70">{t("eval.caseCount", { count: cases.length })}</span>
          <div className="ml-auto flex items-center gap-2">
            <Button size="sm" variant="outline" className="h-7 gap-1 text-xs" onClick={addCase}>
              <Plus className="h-3 w-3" />{t("eval.addCase")}
            </Button>
            <Button size="sm" className="h-7 gap-1 text-xs" onClick={runEval} disabled={running || cases.length === 0}>
              {running ? <Loader2 className="h-3 w-3 animate-spin" /> : <Play className="h-3 w-3" />}
              {t("eval.runEval")}
            </Button>
          </div>
        </div>

        {cases.length === 0 && (
          <div className="text-xs text-muted-foreground border border-dashed border-border rounded-lg p-4 text-center">
            {t("eval.empty")}
          </div>
        )}

        {/* Dataset */}
        <div className="space-y-1.5">
          {cases.map((c) => (
            <CaseRow
              key={c.id}
              c={c}
              expanded={expanded === c.id}
              result={resultByCase[c.id]}
              onToggle={() => setExpanded(expanded === c.id ? null : c.id)}
              onSave={(patch) => saveCase(c.id, patch)}
              onDelete={() => delCase(c.id)}
            />
          ))}
        </div>

        {/* Latest result */}
        {selectedRun && (
          <ResultView run={selectedRun} prevRun={prevRun} caseName={(id) => cases.find((c) => c.id === id)?.name} />
        )}

        {/* Past runs */}
        {runs.length > 1 && (
          <div>
            <div className="text-[10px] uppercase tracking-wide text-muted-foreground/70 mb-1.5">{t("eval.history")}</div>
            <div className="space-y-0.5">
              {runs.map((r) => (
                <button
                  key={r.id}
                  onClick={() => evals.getRun(r.id).then(setSelectedRun)}
                  className={`w-full flex items-center gap-2 text-xs px-2 py-1 rounded hover:bg-secondary/40 transition-colors ${
                    selectedRun?.id === r.id ? "bg-secondary/40" : ""
                  }`}
                >
                  <ScorePill run={r} />
                  {r.revision_number != null && <span className="text-muted-foreground">v{r.revision_number}</span>}
                  <span className="ml-auto text-muted-foreground/70">{formatDate(r.created_at)}</span>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </ScrollArea>
  );
}

function ScorePill({ run }: { run: EvalRun }) {
  const { t } = useTranslation("script");
  if (run.status === "running") return <span className="flex items-center gap-1 text-blue-400"><Loader2 className="h-3 w-3 animate-spin" />{t("eval.running")}</span>;
  if (run.status === "failed") return <span className="text-destructive">{t("eval.failedShort")}</span>;
  const all = run.passed === run.total && run.total > 0;
  return (
    <span className={`tabular-nums font-medium ${all ? "text-emerald-400" : "text-amber-400"}`}>
      {run.passed}/{run.total}
    </span>
  );
}

function ResultView({
  run, prevRun, caseName,
}: {
  run: EvalRun;
  prevRun?: EvalRun;
  caseName: (id: string) => string | undefined;
}) {
  const { t } = useTranslation("script");
  const delta = prevRun ? run.passed - prevRun.passed : null;
  return (
    <div className="rounded-lg border border-border bg-secondary/20 p-3 space-y-2">
      <div className="flex items-center gap-2">
        <ScorePill run={run} />
        <span className="text-xs text-muted-foreground">{t("eval.passed")}</span>
        {delta != null && delta !== 0 && (
          <span className={`flex items-center gap-0.5 text-xs ${delta > 0 ? "text-emerald-400" : "text-destructive"}`}>
            {delta > 0 ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
            {delta > 0 ? `+${delta}` : delta} {t("eval.vsPrev")}
          </span>
        )}
        {delta === 0 && (
          <span className="flex items-center gap-0.5 text-xs text-muted-foreground"><Minus className="h-3 w-3" />{t("eval.noChange")}</span>
        )}
        {run.judge_model && <span className="ml-auto text-[10px] text-muted-foreground/60">{t("eval.judge")}: {run.judge_model}</span>}
      </div>
      {run.error && <div className="text-xs text-destructive">{run.error}</div>}
      <div className="space-y-1">
        {(run.results_json ?? []).map((r) => (
          <div key={r.case_id} className="text-xs">
            <div className="flex items-center gap-2">
              {r.passed ? <Check className="h-3 w-3 text-emerald-400 shrink-0" /> : <X className="h-3 w-3 text-destructive shrink-0" />}
              <span className={r.passed ? "" : "text-foreground"}>{r.name || caseName(r.case_id)}</span>
              {r.error && <span className="text-destructive/80 truncate">— {r.error}</span>}
            </div>
            {/* Failing assertion details */}
            {!r.passed && !r.error && r.assertions.filter((a) => !a.passed).map((a, i) => (
              <div key={i} className="ml-5 text-[11px] text-muted-foreground">
                <span className="font-mono">{a.type}</span> {a.value && <span className="opacity-70">“{a.value}”</span>} — {a.detail}
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

function CaseRow({
  c, expanded, result, onToggle, onSave, onDelete,
}: {
  c: EvalCase;
  expanded: boolean;
  result?: EvalCaseResult;
  onToggle: () => void;
  onSave: (patch: Partial<EvalCase>) => void;
  onDelete: () => void;
}) {
  const { t } = useTranslation("script");
  const [name, setName] = useState(c.name);
  const [inputJson, setInputJson] = useState(c.input_json);
  const [assertions, setAssertions] = useState<Assertion[]>(c.assertions);
  const [jsonErr, setJsonErr] = useState("");

  // Re-sync when the case is replaced by a saved copy from the server.
  useEffect(() => { setName(c.name); setInputJson(c.input_json); setAssertions(c.assertions); }, [c]);

  function commit(next?: Partial<EvalCase>) {
    try { JSON.parse(inputJson || "{}"); setJsonErr(""); }
    catch (e) { setJsonErr(String(e)); return; }
    onSave({ name, input_json: inputJson, assertions, ...next });
  }

  function setAssertion(i: number, patch: Partial<Assertion>) {
    setAssertions((p) => p.map((a, idx) => (idx === i ? { ...a, ...patch } : a)));
  }

  return (
    <div className="rounded-lg border border-border/70 overflow-hidden">
      <div className="flex items-center gap-2 px-2 py-1.5 text-xs hover:bg-secondary/30">
        <button onClick={onToggle} className="flex items-center gap-2 flex-1 min-w-0 text-left">
          {expanded ? <ChevronDown className="h-3 w-3 shrink-0" /> : <ChevronRight className="h-3 w-3 shrink-0" />}
          {result && (result.passed ? <Check className="h-3 w-3 text-emerald-400 shrink-0" /> : <X className="h-3 w-3 text-destructive shrink-0" />)}
          <span className="truncate">{c.name}</span>
          <span className="text-muted-foreground/60 shrink-0">{t("eval.assertionCount", { count: c.assertions.length })}</span>
        </button>
        <button onClick={onDelete} className="shrink-0 text-muted-foreground/50 hover:text-destructive" title={t("eval.deleteCase")}>
          <Trash2 className="h-3 w-3" />
        </button>
      </div>

      {expanded && (
        <div className="px-3 py-2 space-y-2 border-t border-border/60 bg-background/40">
          <div>
            <label className="text-[10px] text-muted-foreground">{t("eval.caseNameLabel")}</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              onBlur={() => commit()}
              className="w-full mt-0.5 px-2 py-1 text-xs rounded border border-border bg-background"
            />
          </div>
          <div>
            <label className="text-[10px] text-muted-foreground">{t("eval.inputLabel")}</label>
            <textarea
              value={inputJson}
              onChange={(e) => setInputJson(e.target.value)}
              onBlur={() => commit()}
              rows={3}
              spellCheck={false}
              className="w-full mt-0.5 px-2 py-1 text-xs font-mono rounded border border-border bg-background resize-y"
            />
            {jsonErr && <div className="text-[10px] text-destructive mt-0.5">{jsonErr}</div>}
          </div>
          <div>
            <div className="flex items-center justify-between">
              <label className="text-[10px] text-muted-foreground">{t("eval.assertionsLabel")}</label>
              <button
                onClick={() => { const next = [...assertions, { type: "contains" as AssertionType, value: "" }]; setAssertions(next); onSave({ name, input_json: inputJson, assertions: next }); }}
                className="text-[10px] text-primary hover:underline flex items-center gap-0.5"
              >
                <Plus className="h-3 w-3" />{t("eval.addAssertion")}
              </button>
            </div>
            <div className="space-y-1 mt-1">
              {assertions.map((a, i) => (
                <div key={i} className="flex items-center gap-1">
                  <select
                    value={a.type}
                    onChange={(e) => setAssertion(i, { type: e.target.value as AssertionType })}
                    onBlur={() => commit()}
                    className="px-1.5 py-1 text-[11px] rounded border border-border bg-background shrink-0"
                  >
                    {ASSERTION_TYPES.map((tp) => <option key={tp} value={tp}>{t(`eval.assertionTypes.${tp}`)}</option>)}
                  </select>
                  <input
                    value={a.value}
                    onChange={(e) => setAssertion(i, { value: e.target.value })}
                    onBlur={() => commit()}
                    placeholder={a.type === "judge" ? t("eval.judgePlaceholder") : t("eval.valuePlaceholder")}
                    className="flex-1 min-w-0 px-2 py-1 text-[11px] rounded border border-border bg-background"
                  />
                  {a.type === "judge" && (
                    <input
                      type="number" min={0} max={10}
                      value={a.threshold ?? 7}
                      onChange={(e) => setAssertion(i, { threshold: Number(e.target.value) })}
                      onBlur={() => commit()}
                      title={t("eval.thresholdTitle")}
                      className="w-12 px-1.5 py-1 text-[11px] rounded border border-border bg-background shrink-0"
                    />
                  )}
                  <button
                    onClick={() => { const next = assertions.filter((_, idx) => idx !== i); setAssertions(next); onSave({ name, input_json: inputJson, assertions: next }); }}
                    className="shrink-0 text-muted-foreground/50 hover:text-destructive"
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
