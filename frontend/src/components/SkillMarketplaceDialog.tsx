"use client";
import { useCallback, useEffect, useState } from "react";
import {
  Loader2, Download, Check, Star, RefreshCw, Search, BookOpen, ExternalLink, ArrowLeft,
} from "lucide-react";
import { toast } from "sonner";
import { marketplace } from "@/lib/api";
import type { MarketplaceSkill, RegistrySkill } from "@/lib/types";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type Tab = "official" | "skillsmp" | "skillssh";

const TAB_LABEL: Record<Tab, string> = {
  official: "官方 anthropics/skills",
  skillsmp: "社区 SkillsMP",
  skillssh: "社区 skills.sh",
};

interface Choice {
  owner: string;
  repo: string;
  ref?: string | null;
  skills: MarketplaceSkill[];
  label: string;
}

// Browse & install Agent Skills from the official anthropics/skills repo and the
// community registries (SkillsMP, skills.sh). Every install resolves to a GitHub
// repo on the backend, which downloads the folder into the on-disk skill store.
export default function SkillMarketplaceDialog({
  open, onOpenChange, onInstalled,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  onInstalled: () => void;
}) {
  const [tab, setTab] = useState<Tab>("official");

  const [official, setOfficial] = useState<MarketplaceSkill[]>([]);
  const [officialLoaded, setOfficialLoaded] = useState(false);
  const [loadingOfficial, setLoadingOfficial] = useState(false);
  const [hasToken, setHasToken] = useState(true);

  const [q, setQ] = useState("");
  const [results, setResults] = useState<RegistrySkill[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [rate, setRate] = useState<number | null>(null);
  const [hasKey, setHasKey] = useState(true);
  const [authRequired, setAuthRequired] = useState(false);

  const [installing, setInstalling] = useState<string | null>(null);
  const [installed, setInstalled] = useState<Set<string>>(new Set());
  const [choice, setChoice] = useState<Choice | null>(null);

  const isRegistry = tab === "skillsmp" || tab === "skillssh";

  const loadOfficial = useCallback(async (refresh = false) => {
    setLoadingOfficial(true);
    try {
      const r = await marketplace.official(refresh);
      setOfficial(r.skills);
      setHasToken(r.has_token);
      setOfficialLoaded(true);
    } catch (e) { toast.error(String(e)); }
    finally { setLoadingOfficial(false); }
  }, []);

  useEffect(() => {
    if (open && tab === "official" && !officialLoaded) loadOfficial(false);
  }, [open, tab, officialLoaded, loadOfficial]);

  function switchTab(t: Tab) {
    if (t === tab) return;
    setTab(t);
    if (t === "skillsmp" || t === "skillssh") {
      // reset the search panel so results from the other provider don't linger
      setResults(null);
      setRate(null);
      setAuthRequired(false);
    }
  }

  async function doSearch() {
    if (!q.trim() || !isRegistry) return;
    const provider = tab === "skillssh" ? "skillssh" : "skillsmp";
    setSearching(true);
    setAuthRequired(false);
    try {
      const r = await marketplace.search(q.trim(), provider);
      setResults(r.skills);
      setRate(r.rate_remaining);
      setHasKey(r.has_key);
      setAuthRequired(!!r.auth_required);
    } catch (e) { toast.error(String(e)); }
    finally { setSearching(false); }
  }

  async function install(
    body: Parameters<typeof marketplace.install>[0],
    key: string,
    label: string,
  ) {
    setInstalling(key);
    try {
      const r = await marketplace.install(body);
      if (r.needs_choice && r.skills) {
        setChoice({ owner: r.owner!, repo: r.repo!, ref: r.ref, skills: r.skills, label });
        return;
      }
      toast.success(r.already_installed ? `“${label}” already installed` : `Installed “${r.skill?.name ?? label}”`);
      setInstalled(prev => new Set(prev).add(key));
      onInstalled();
    } catch (e) { toast.error(String(e)); }
    finally { setInstalling(null); }
  }

  function Card({
    name, description, meta, installKey, isInstalled, onInstall, href,
  }: {
    name: string; description: string; meta?: React.ReactNode;
    installKey: string; isInstalled: boolean; onInstall: () => void; href?: string;
  }) {
    const busy = installing === installKey;
    const done = isInstalled || installed.has(installKey);
    return (
      <div className="border border-border rounded-lg p-3 flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <BookOpen className="h-3.5 w-3.5 text-fuchsia-400 shrink-0" />
            <span className="font-medium text-sm truncate">{name}</span>
            {meta}
            {href && (
              <a href={href} target="_blank" rel="noreferrer" title="Open on GitHub"
                className="text-muted-foreground hover:text-foreground">
                <ExternalLink className="h-3 w-3" />
              </a>
            )}
          </div>
          <p className="text-xs text-muted-foreground mt-1 line-clamp-2">{description || "No description"}</p>
        </div>
        <Button size="sm" variant={done ? "outline" : "default"} disabled={busy || done} onClick={onInstall}>
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
            : done ? <Check className="h-3.5 w-3.5" />
            : <Download className="h-3.5 w-3.5" />}
          {done ? "Installed" : "Install"}
        </Button>
      </div>
    );
  }

  return (
    <Dialog open={open} onOpenChange={v => { onOpenChange(v); if (!v) setChoice(null); }}>
      <DialogContent className="max-w-2xl max-h-[85vh] flex flex-col overflow-hidden">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <BookOpen className="h-4 w-4 text-primary" /> Skill Marketplace
          </DialogTitle>
        </DialogHeader>

        {choice ? (
          /* ── Multi-skill repo: pick which one to install ── */
          <div className="flex-1 min-h-0 flex flex-col gap-3">
            <button onClick={() => setChoice(null)}
              className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground shrink-0">
              <ArrowLeft className="h-3 w-3" /> Back
            </button>
            <p className="text-xs text-muted-foreground shrink-0">
              <span className="font-medium text-foreground">{choice.owner}/{choice.repo}</span> bundles
              several skills — choose one:
            </p>
            <div className="flex-1 min-h-0 overflow-y-auto pr-1 space-y-2">
              {choice.skills.map(s => (
                <Card
                  key={s.path}
                  name={s.name}
                  description={s.description}
                  meta={<span className="text-[10px] text-muted-foreground/60 font-mono">{s.path}</span>}
                  installKey={`${choice.owner}/${choice.repo}#${s.path}`}
                  isInstalled={false}
                  onInstall={() => install(
                    { owner: choice.owner, repo: choice.repo, ref: choice.ref, subpath: s.path },
                    `${choice.owner}/${choice.repo}#${s.path}`, s.name,
                  )}
                />
              ))}
            </div>
          </div>
        ) : (
          <div className="flex-1 min-h-0 flex flex-col gap-3">
            {/* Tabs */}
            <div className="flex items-center gap-1 border-b border-border shrink-0">
              {(["official", "skillsmp", "skillssh"] as Tab[]).map(t => (
                <button key={t} onClick={() => switchTab(t)}
                  className={`px-3 py-1.5 text-sm border-b-2 -mb-px transition-colors whitespace-nowrap ${
                    tab === t ? "border-primary text-foreground font-medium" : "border-transparent text-muted-foreground hover:text-foreground"
                  }`}>
                  {TAB_LABEL[t]}
                </button>
              ))}
              <div className="flex-1" />
              {tab === "official" && (
                <Button variant="ghost" size="icon" title="Refresh"
                  onClick={() => loadOfficial(true)} disabled={loadingOfficial}>
                  <RefreshCw className={`h-3.5 w-3.5 ${loadingOfficial ? "animate-spin" : ""}`} />
                </Button>
              )}
            </div>

            {tab === "official" ? (
              <>
                {!hasToken && (
                  <p className="text-[11px] text-amber-500/90 shrink-0">
                    未设置 GITHUB_TOKEN — GitHub 匿名限流 60次/小时。设置后可提高上限。
                  </p>
                )}
                <div className="flex-1 min-h-0 overflow-y-auto pr-1 space-y-2">
                  {loadingOfficial && (
                    <div className="flex items-center justify-center py-10 text-muted-foreground">
                      <Loader2 className="h-5 w-5 animate-spin" />
                    </div>
                  )}
                  {!loadingOfficial && official.length === 0 && officialLoaded && (
                    <p className="text-sm text-muted-foreground text-center py-10">No skills found.</p>
                  )}
                  {official.map(s => (
                    <Card
                      key={s.upstream ?? s.path}
                      name={s.name}
                      description={s.description}
                      meta={<span className="text-[10px] text-muted-foreground/60 font-mono truncate">{s.path}</span>}
                      installKey={s.upstream ?? s.path}
                      isInstalled={!!s.installed}
                      onInstall={() => install(
                        { owner: s.owner, repo: s.repo, subpath: s.path },
                        s.upstream ?? s.path, s.name,
                      )}
                    />
                  ))}
                </div>
              </>
            ) : (
              <>
                <div className="flex items-center gap-2 shrink-0">
                  <div className="relative flex-1">
                    <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
                    <Input
                      value={q}
                      onChange={e => setQ(e.target.value)}
                      onKeyDown={e => { if (e.key === "Enter") doSearch(); }}
                      placeholder="搜索社区技能，如 pdf、web scraping…"
                      className="pl-8"
                    />
                  </div>
                  <Button onClick={doSearch} disabled={searching || !q.trim()}>
                    {searching ? <Loader2 className="h-4 w-4 animate-spin" /> : "搜索"}
                  </Button>
                </div>
                {tab === "skillssh" && (authRequired || results == null) && (
                  <p className="text-[11px] text-amber-500/90 shrink-0">
                    skills.sh 搜索需要 Vercel OIDC token — 设置环境变量 SKILLS_SH_TOKEN（或
                    VERCEL_OIDC_TOKEN）后可用。SkillsMP 无需 token。
                  </p>
                )}
                {rate != null && (
                  <p className="text-[11px] text-muted-foreground shrink-0">
                    今日剩余额度 {rate}{tab === "skillsmp" && !hasKey && " — 设置 SKILLSMP_API_KEY 可提升至 500/天"}
                  </p>
                )}
                <div className="flex-1 min-h-0 overflow-y-auto pr-1 space-y-2">
                  {results?.length === 0 && !authRequired && (
                    <p className="text-sm text-muted-foreground text-center py-10">No results.</p>
                  )}
                  {results?.map(s => (
                    <Card
                      key={String(s.id) + s.githubUrl}
                      name={s.name}
                      description={s.description}
                      href={s.githubUrl || undefined}
                      meta={
                        <span className="flex items-center gap-2 text-[10px] text-muted-foreground/70">
                          {s.author && <span>@{s.author}</span>}
                          <span className="flex items-center gap-0.5"><Star className="h-3 w-3" />{s.stars}</span>
                        </span>
                      }
                      installKey={s.githubUrl || String(s.id)}
                      isInstalled={false}
                      onInstall={() => install({ githubUrl: s.githubUrl }, s.githubUrl || String(s.id), s.name)}
                    />
                  ))}
                  {results == null && !(tab === "skillssh") && (
                    <p className="text-sm text-muted-foreground text-center py-10">
                      输入关键词搜索社区技能。安装时会从对应的 GitHub 仓库拉取。
                    </p>
                  )}
                </div>
              </>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
