"use client";
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useTranslation } from "react-i18next";
import { ArrowLeft, Coins, Zap, Play, CheckCircle2, TrendingUp } from "lucide-react";
import { executions } from "@/lib/api";
import type { UsageStats } from "@/lib/types";
import { compactNumber } from "@/lib/utils";

// Run-status → a reserved status color (never a categorical hue) + i18n key.
// good → emerald, critical → destructive, warning → amber, active → primary.
const STATUS_ORDER = ["completed", "running", "queued", "pending", "cancelled", "failed", "unknown"] as const;
const STATUS_COLOR: Record<string, string> = {
  completed: "hsl(160 84% 39%)",
  running: "hsl(var(--primary))",
  queued: "hsl(0 0% 45%)",
  pending: "hsl(0 0% 38%)",
  cancelled: "hsl(38 92% 50%)",
  failed: "hsl(var(--destructive))",
  unknown: "hsl(0 0% 30%)",
};

export default function DashboardPage() {
  const { t } = useTranslation(["analytics", "common"]);
  const [days, setDays] = useState(7);
  const [stats, setStats] = useState<UsageStats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    executions.usageStats(days).then(setStats).catch(() => null).finally(() => setLoading(false));
  }, [days]);

  const successRate = useMemo(() => {
    if (!stats) return null;
    const done = (stats.status_counts.completed || 0) + (stats.status_counts.failed || 0);
    if (done === 0) return null;
    return Math.round(((stats.status_counts.completed || 0) / done) * 100);
  }, [stats]);

  return (
    <div className="min-h-screen flex flex-col">
      {/* Header */}
      <header className="border-b border-border px-6 py-3 flex items-center gap-3">
        <Link href="/" className="text-muted-foreground hover:text-foreground transition-colors">
          <ArrowLeft className="h-4 w-4" />
        </Link>
        <div className="flex items-baseline gap-2">
          <h1 className="font-semibold text-base">{t("analytics:title")}</h1>
          <span className="text-xs text-muted-foreground hidden sm:inline">{t("analytics:subtitle")}</span>
        </div>
        <div className="ml-auto flex items-center rounded-lg border border-border p-0.5 text-xs">
          {[7, 30].map((d) => (
            <button
              key={d}
              onClick={() => setDays(d)}
              className={`px-2.5 py-1 rounded-md transition-colors ${
                days === d ? "bg-secondary text-foreground" : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {t(`analytics:range.${d}d`)}
            </button>
          ))}
        </div>
      </header>

      <main className="flex-1 px-6 py-8 max-w-6xl mx-auto w-full space-y-5">
        {loading && !stats ? (
          <div className="space-y-5">
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
              {[...Array(4)].map((_, i) => <div key={i} className="h-24 rounded-xl border border-border bg-secondary/20 animate-pulse" />)}
            </div>
            <div className="h-64 rounded-xl border border-border bg-secondary/20 animate-pulse" />
          </div>
        ) : !stats || stats.runs === 0 ? (
          <div className="flex flex-col items-center justify-center py-32 text-center">
            <TrendingUp className="h-12 w-12 text-muted-foreground/30 mb-4" />
            <p className="text-muted-foreground">{t("analytics:empty")}</p>
          </div>
        ) : (
          <>
            {/* KPI tiles */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
              <StatTile
                icon={<Coins className="h-4 w-4" />}
                label={t("analytics:kpi.tokens")}
                value={compactNumber(stats.total_tokens)}
                sub={t("analytics:kpi.promptCompletion", {
                  prompt: compactNumber(stats.prompt_tokens),
                  completion: compactNumber(stats.completion_tokens),
                })}
              />
              <StatTile icon={<Zap className="h-4 w-4" />} label={t("analytics:kpi.calls")} value={compactNumber(stats.llm_calls)} />
              <StatTile icon={<Play className="h-4 w-4" />} label={t("analytics:kpi.runs")} value={stats.runs.toLocaleString()} />
              <StatTile
                icon={<CheckCircle2 className="h-4 w-4" />}
                label={t("analytics:kpi.successRate")}
                value={successRate === null ? "—" : `${successRate}%`}
              />
            </div>

            {/* Token usage trend */}
            <section className="rounded-xl border border-border bg-secondary/10 p-5">
              <div className="text-sm font-medium mb-4">{t("analytics:chart.title")}</div>
              <UsageAreaChart daily={stats.daily} />
            </section>

            {/* Two columns: top scripts + run outcomes */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
              <section className="rounded-xl border border-border bg-secondary/10 p-5">
                <div className="text-sm font-medium mb-4">{t("analytics:topScripts.title")}</div>
                <TopScripts items={stats.by_script} />
              </section>
              <section className="rounded-xl border border-border bg-secondary/10 p-5">
                <div className="text-sm font-medium mb-4">{t("analytics:outcomes.title")}</div>
                <RunOutcomes counts={stats.status_counts} />
              </section>
            </div>
          </>
        )}
      </main>
    </div>
  );
}

function StatTile({ icon, label, value, sub }: { icon: React.ReactNode; label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl border border-border bg-secondary/20 p-4">
      <div className="flex items-center gap-1.5 text-muted-foreground text-xs mb-2">
        {icon}{label}
      </div>
      <div className="text-2xl font-semibold tabular-nums leading-none">{value}</div>
      {sub && <div className="text-[11px] text-muted-foreground mt-1.5 tabular-nums">{sub}</div>}
    </div>
  );
}

function UsageAreaChart({ daily }: { daily: UsageStats["daily"] }) {
  const { t } = useTranslation("analytics");
  const [hover, setHover] = useState<number | null>(null);
  const max = Math.max(1, ...daily.map((d) => d.total_tokens));
  const n = daily.length;

  // Percentage coordinates so the chart is responsive without a resize observer.
  const px = (i: number) => (n > 1 ? (i / (n - 1)) * 100 : 50);
  const py = (v: number) => (1 - v / max) * 100; // 0 (top) … 100 (bottom)

  const linePts = daily.map((d, i) => `${px(i)},${py(d.total_tokens)}`).join(" ");
  const areaPath = `M0,100 L ${daily.map((d, i) => `${px(i)},${py(d.total_tokens)}`).join(" L ")} L 100,100 Z`;

  return (
    <div>
      <div
        className="relative h-52"
        onMouseLeave={() => setHover(null)}
        onMouseMove={(e) => {
          const r = e.currentTarget.getBoundingClientRect();
          const ratio = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
          setHover(Math.round(ratio * (n - 1)));
        }}
      >
        {/* recessive gridlines */}
        <div className="absolute inset-0 flex flex-col justify-between pointer-events-none">
          {[0, 1, 2, 3].map((i) => <div key={i} className="border-t border-border/40" />)}
        </div>

        <svg className="absolute inset-0 w-full h-full overflow-visible" viewBox="0 0 100 100" preserveAspectRatio="none">
          <defs>
            <linearGradient id="usageFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="hsl(var(--primary))" stopOpacity="0.28" />
              <stop offset="100%" stopColor="hsl(var(--primary))" stopOpacity="0" />
            </linearGradient>
          </defs>
          <path d={areaPath} fill="url(#usageFill)" />
          <polyline
            points={linePts}
            fill="none"
            stroke="hsl(var(--primary))"
            strokeWidth={2}
            strokeLinejoin="round"
            strokeLinecap="round"
            vectorEffect="non-scaling-stroke"
          />
        </svg>

        {/* hover crosshair + dot + tooltip (HTML overlay, percentage-positioned) */}
        {hover !== null && daily[hover] && (
          <>
            <div className="absolute top-0 bottom-0 w-px bg-border pointer-events-none" style={{ left: `${px(hover)}%` }} />
            <div
              className="absolute w-2 h-2 rounded-full bg-[hsl(var(--primary))] ring-2 ring-background pointer-events-none -translate-x-1/2 -translate-y-1/2"
              style={{ left: `${px(hover)}%`, top: `${py(daily[hover].total_tokens)}%` }}
            />
            <div
              className="absolute z-10 -translate-x-1/2 -translate-y-full mb-2 px-2 py-1 rounded-md border border-border bg-popover text-[11px] whitespace-nowrap pointer-events-none shadow-md"
              style={{ left: `${Math.min(88, Math.max(12, px(hover)))}%`, top: `${py(daily[hover].total_tokens)}%` }}
            >
              <div className="font-medium tabular-nums">{daily[hover].date.slice(5)}</div>
              <div className="text-muted-foreground tabular-nums">
                {t("chart.tokensOn", { tokens: daily[hover].total_tokens.toLocaleString(), runs: daily[hover].runs })}
              </div>
            </div>
          </>
        )}
      </div>

      {/* x-axis: sparse date labels */}
      <div className="flex justify-between mt-2 text-[10px] text-muted-foreground/70 tabular-nums">
        {daily.filter((_, i) => i === 0 || i === Math.floor(n / 2) || i === n - 1).map((d) => (
          <span key={d.date}>{d.date.slice(5)}</span>
        ))}
      </div>
    </div>
  );
}

function TopScripts({ items }: { items: UsageStats["by_script"] }) {
  const { t } = useTranslation("analytics");
  const top = items.slice(0, 6);
  const max = Math.max(1, ...top.map((s) => s.total_tokens));
  if (top.length === 0) return <div className="text-xs text-muted-foreground">{t("topScripts.empty")}</div>;
  return (
    <div className="space-y-2.5">
      {top.map((s) => (
        <Link key={s.script_id} href={`/script/?id=${s.script_id}`} className="block group">
          <div className="flex items-center justify-between text-xs mb-1">
            <span className="truncate group-hover:text-primary transition-colors">{s.name}</span>
            <span className="tabular-nums text-muted-foreground shrink-0 ml-2">{compactNumber(s.total_tokens)}</span>
          </div>
          <div className="h-1.5 rounded-full bg-secondary/60 overflow-hidden">
            <div className="h-full rounded-full bg-primary/70 group-hover:bg-primary transition-all" style={{ width: `${(s.total_tokens / max) * 100}%` }} />
          </div>
        </Link>
      ))}
    </div>
  );
}

function RunOutcomes({ counts }: { counts: Record<string, number> }) {
  const { t } = useTranslation("analytics");
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  const present = STATUS_ORDER.filter((s) => (counts[s] || 0) > 0);
  if (total === 0) return <div className="text-xs text-muted-foreground">{t("outcomes.empty")}</div>;
  return (
    <div>
      {/* segmented bar */}
      <div className="flex h-3 rounded-full overflow-hidden gap-[2px]">
        {present.map((s) => (
          <div key={s} style={{ width: `${((counts[s] || 0) / total) * 100}%`, backgroundColor: STATUS_COLOR[s] }} title={`${t(`outcomes.${s}`)}: ${counts[s]}`} />
        ))}
      </div>
      {/* legend (color + label + count — never color-alone) */}
      <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 mt-4">
        {present.map((s) => (
          <div key={s} className="flex items-center gap-2 text-xs">
            <span className="h-2.5 w-2.5 rounded-sm shrink-0" style={{ backgroundColor: STATUS_COLOR[s] }} />
            <span className="text-muted-foreground">{t(`outcomes.${s}`)}</span>
            <span className="ml-auto tabular-nums">{counts[s]}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
