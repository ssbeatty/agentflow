"use client";
import { useState, useRef, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import {
  Download, RefreshCw, CheckCircle2, XCircle, Trash2, Package,
  AlertTriangle, PackagePlus, Loader2, Search,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription,
} from "@/components/ui/dialog";
import { scripts as scriptsApi } from "@/lib/api";
import { summarizeError } from "@/lib/utils";

interface Props {
  scriptId: string;
  requirements: string;
  onRequirementsSaved?: () => void;
}

type InstallState = "idle" | "working" | "done" | "error";
type ConfirmKind = null | "recreate" | "delete";

export default function DependencyManager({ scriptId, requirements, onRequirementsSaved }: Props) {
  const { t } = useTranslation("scriptPanels");
  const [state, setState] = useState<InstallState>("idle");
  const [lines, setLines] = useState<string[]>([]);
  const [venvExists, setVenvExists] = useState(false);
  const [packages, setPackages] = useState<{ name: string; version: string }[]>([]);
  const [pkgError, setPkgError] = useState<string | null>(null);
  const [showPackages, setShowPackages] = useState(false);
  const [search, setSearch] = useState("");
  const [confirmKind, setConfirmKind] = useState<ConfirmKind>(null);
  const logsRef = useRef<HTMLDivElement>(null);

  const refreshPackages = async () => {
    try {
      const r = await scriptsApi.packages(scriptId);
      setPackages(r.packages);
      setPkgError(r.error);
      if (r.error) toast.error(t("dependencyManager.toast.pipListError", { error: summarizeError(r.error) }));
    } catch (e) { setPackages([]); setPkgError(String(e)); }
  };

  useEffect(() => {
    scriptsApi.venvStatus(scriptId).then(s => {
      setVenvExists(s.exists);
      if (s.exists) refreshPackages();
    }).catch(() => null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scriptId]);

  async function stream(endpoint: "venv" | "install", force = false) {
    setState("working");
    setLines([]);
    setShowPackages(false); // show logs while working
    try {
      if (endpoint === "install") {
        await scriptsApi.update(scriptId, { requirements });
        onRequirementsSaved?.();
      }
      const url = endpoint === "venv" && force
        ? `/api/scripts/${scriptId}/venv?force=true`
        : `/api/scripts/${scriptId}/${endpoint}`;
      const res = await fetch(url, { method: "POST" });
      if (!res.ok) throw new Error(await res.text());
      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const parts = buf.split("\n");
        buf = parts.pop() ?? "";
        for (const line of parts) {
          if (!line) continue;
          setLines(p => [...p, line]);
          if (logsRef.current) logsRef.current.scrollTop = logsRef.current.scrollHeight;
          if (line.startsWith("ERROR:")) { setState("error"); toast.error(summarizeError(line)); return; }
          if (line === "DONE") {
            setState("done");
            if (endpoint === "venv") setVenvExists(true);
            refreshPackages();
            toast.success(endpoint === "venv" ? t("dependencyManager.toast.venvReady") : t("dependencyManager.toast.packagesInstalled"));
            return;
          }
        }
      }
      setState("done");
    } catch (e: unknown) {
      setState("error");
      toast.error(String(e));
    }
  }

  async function doDelete() {
    try {
      await scriptsApi.deleteVenv(scriptId);
      setVenvExists(false);
      setPackages([]);
      setShowPackages(false);
      setLines([]);
      setState("idle");
      toast.success(t("dependencyManager.toast.venvDeleted"));
    } catch (e) { toast.error(String(e)); }
  }

  function toggleList() {
    if (showPackages) {
      setShowPackages(false);
    } else {
      setShowPackages(true);
      setSearch("");
      refreshPackages();
    }
  }

  const busy = state === "working";
  const filteredPackages = search
    ? packages.filter(p => p.name.toLowerCase().includes(search.toLowerCase()))
    : packages;

  return (
    <div className="h-full flex flex-col">
      {/* Toolbar — 2 compact rows */}
      <div className="border-b border-border shrink-0">
        {/* Row 1: status + icon actions */}
        <div className="flex items-center gap-1.5 px-2 py-1">
          <span className={`h-1.5 w-1.5 rounded-full shrink-0 ${venvExists ? "bg-emerald-400" : "bg-muted-foreground/40"}`} />
          <span className="text-xs text-muted-foreground flex-1 truncate">
            {venvExists ? t("dependencyManager.status.venv", { count: packages.length }) : t("dependencyManager.status.noVenv")}
          </span>
          {state === "done" && <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400 shrink-0" />}
          {state === "error" && <XCircle className="h-3.5 w-3.5 text-destructive shrink-0" />}
          {busy && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground shrink-0" />}
          {venvExists && (
            <>
              <button onClick={() => !busy && setConfirmKind("recreate")} disabled={busy}
                title={t("dependencyManager.actions.recreateVenvTitle")}
                className="h-5 w-5 rounded flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-white/10 disabled:opacity-40 transition-colors shrink-0">
                <RefreshCw className="h-3 w-3" />
              </button>
              <button onClick={() => !busy && setConfirmKind("delete")} disabled={busy}
                title={t("dependencyManager.actions.deleteVenvTitle")}
                className="h-5 w-5 rounded flex items-center justify-center text-muted-foreground hover:text-destructive hover:bg-white/10 disabled:opacity-40 transition-colors shrink-0">
                <Trash2 className="h-3 w-3" />
              </button>
            </>
          )}
        </div>
        {/* Row 2: primary actions */}
        <div className="flex items-center gap-1 px-2 pb-1.5">
          {!venvExists ? (
            <Button size="sm" className="h-6 text-xs gap-1 flex-1" onClick={() => stream("venv")} disabled={busy}>
              <PackagePlus className="h-3 w-3" />{t("dependencyManager.actions.createVenv")}
            </Button>
          ) : (
            <Button size="sm" className="h-6 text-xs gap-1 flex-1" onClick={() => stream("install")} disabled={busy}>
              <Download className="h-3 w-3" />{t("dependencyManager.actions.install")}
            </Button>
          )}
          {venvExists && (
            <Button variant="outline" size="sm" className="h-6 text-xs gap-1 flex-1" onClick={toggleList}>
              <Package className="h-3 w-3" />{showPackages ? t("dependencyManager.actions.hide") : t("dependencyManager.actions.list")}
            </Button>
          )}
        </div>
      </div>

      {/* Hint */}
      {!venvExists && lines.length === 0 && (
        <div className="px-3 py-2 text-xs text-muted-foreground/70">
          {t("dependencyManager.hint.before")}<code className="text-foreground/80">requirements.txt</code>{t("dependencyManager.hint.after")}
        </div>
      )}

      {/* Body: packages OR logs — never side by side */}
      <div className="flex-1 min-h-0 overflow-hidden flex flex-col">
        {showPackages ? (
          <>
            {/* Search bar */}
            <div className="px-2 py-1 border-b border-border shrink-0">
              <div className="relative">
                <Search className="absolute left-1.5 top-1/2 -translate-y-1/2 h-3 w-3 text-muted-foreground/60 pointer-events-none" />
                <input
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                  placeholder={t("dependencyManager.search.placeholder")}
                  className="w-full pl-5 pr-2 py-0.5 text-xs font-mono bg-transparent focus:outline-none placeholder:text-muted-foreground/40"
                />
              </div>
            </div>
            {/* Package list */}
            <ScrollArea className="flex-1">
              <div className="p-2 font-mono text-xs space-y-0.5">
                {pkgError && <div className="text-red-400 whitespace-pre-wrap break-all">{pkgError}</div>}
                {!pkgError && filteredPackages.length === 0 && (
                  <div className="text-muted-foreground">
                    {packages.length === 0 ? t("dependencyManager.packages.empty") : t("dependencyManager.packages.noMatch")}
                  </div>
                )}
                {filteredPackages.map(p => (
                  <div key={p.name} className="flex justify-between gap-2">
                    <span className="truncate">{p.name}</span>
                    <span className="text-muted-foreground shrink-0">{p.version}</span>
                  </div>
                ))}
              </div>
            </ScrollArea>
          </>
        ) : lines.length > 0 ? (
          /* Stream output */
          <ScrollArea className="flex-1">
            <div ref={logsRef} className="p-2 font-mono text-xs space-y-0.5">
              {lines.map((l, i) => (
                <div key={i} className={
                  l.startsWith("ERROR") ? "text-red-400" :
                  l === "DONE" ? "text-emerald-400" :
                  "text-muted-foreground"
                }>{l}</div>
              ))}
            </div>
          </ScrollArea>
        ) : null}
      </div>

      {/* Confirm dialog */}
      <Dialog open={confirmKind !== null} onOpenChange={o => !o && setConfirmKind(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-amber-400" />
              {confirmKind === "delete" ? t("dependencyManager.confirmDialog.deleteTitle") : t("dependencyManager.confirmDialog.recreateTitle")}
            </DialogTitle>
            <DialogDescription>
              {confirmKind === "delete"
                ? t("dependencyManager.confirmDialog.deleteDescription")
                : t("dependencyManager.confirmDialog.recreateDescription")}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmKind(null)}>{t("dependencyManager.confirmDialog.cancel")}</Button>
            <Button variant="destructive" onClick={async () => {
              const kind = confirmKind;
              setConfirmKind(null);
              if (kind === "delete") await doDelete();
              else if (kind === "recreate") await stream("venv", true);
            }}>
              {confirmKind === "delete" ? t("dependencyManager.confirmDialog.deleteConfirm") : t("dependencyManager.confirmDialog.recreateConfirm")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
