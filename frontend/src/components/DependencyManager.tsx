"use client";
import { useState, useRef, useEffect } from "react";
import { toast } from "sonner";
import {
  Download, RefreshCw, CheckCircle2, XCircle, Trash2, Package,
  AlertTriangle, PackagePlus, Loader2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription,
} from "@/components/ui/dialog";
import { scripts as scriptsApi } from "@/lib/api";

interface Props {
  scriptId: string;
  requirements: string;
  onRequirementsChange: (v: string) => void;
}

type InstallState = "idle" | "working" | "done" | "error";
type ConfirmKind = null | "recreate" | "delete";

export default function DependencyManager({ scriptId, requirements, onRequirementsChange }: Props) {
  const [state, setState] = useState<InstallState>("idle");
  const [lines, setLines] = useState<string[]>([]);
  const [venvExists, setVenvExists] = useState(false);
  const [packages, setPackages] = useState<{ name: string; version: string }[]>([]);
  const [pkgError, setPkgError] = useState<string | null>(null);
  const [showPackages, setShowPackages] = useState(false);
  const [confirmKind, setConfirmKind] = useState<ConfirmKind>(null);
  const logsRef = useRef<HTMLDivElement>(null);
  const lastSavedRef = useRef<string>(requirements);

  const refreshPackages = async () => {
    try {
      const r = await scriptsApi.packages(scriptId);
      setPackages(r.packages);
      setPkgError(r.error);
      if (r.error) toast.error(`pip list: ${r.error}`);
    } catch (e) { setPackages([]); setPkgError(String(e)); }
  };

  useEffect(() => {
    scriptsApi.venvStatus(scriptId).then((s) => {
      setVenvExists(s.exists);
      if (s.exists) refreshPackages();
    }).catch(() => null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scriptId]);

  // autosave requirements on blur if changed since last persist
  async function persistRequirementsIfDirty() {
    if (requirements === lastSavedRef.current) return;
    try {
      await scriptsApi.update(scriptId, { requirements });
      lastSavedRef.current = requirements;
    } catch (e) {
      toast.error(`Failed to save requirements: ${e}`);
    }
  }

  async function stream(endpoint: "venv" | "install", force = false) {
    setState("working");
    setLines([]);
    try {
      if (endpoint === "install") {
        await scriptsApi.update(scriptId, { requirements });
        lastSavedRef.current = requirements;
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
          setLines((p) => [...p, line]);
          if (logsRef.current) logsRef.current.scrollTop = logsRef.current.scrollHeight;
          if (line.startsWith("ERROR:")) {
            setState("error");
            toast.error(line);
            return;
          }
          if (line === "DONE") {
            setState("done");
            if (endpoint === "venv") setVenvExists(true);
            refreshPackages();
            toast.success(endpoint === "venv" ? "Venv ready" : "Packages installed");
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
      toast.success("Venv deleted");
    } catch (e) { toast.error(String(e)); }
  }

  const busy = state === "working";

  return (
    <div className="h-full flex flex-col">
      {/* ── Toolbar ────────────────────────────────────────────────────── */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-border shrink-0">
        {/* status chip */}
        <div className="flex items-center gap-1.5 px-2 py-1 rounded-md border border-border bg-secondary/30 text-xs">
          <span
            className={`h-1.5 w-1.5 rounded-full ${
              venvExists ? "bg-emerald-400" : "bg-muted-foreground/40"
            }`}
          />
          <span className="text-muted-foreground">
            {venvExists ? `venv · ${packages.length} pkgs` : "no venv"}
          </span>
        </div>

        {state === "done" && <CheckCircle2 className="h-4 w-4 text-emerald-400" />}
        {state === "error" && <XCircle className="h-4 w-4 text-destructive" />}
        {busy && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}

        {/* primary action — Create or Install */}
        <div className="ml-2">
          {!venvExists ? (
            <Button
              size="sm"
              className="h-7 text-xs gap-1.5"
              onClick={() => stream("venv")}
              disabled={busy}
            >
              <PackagePlus className="h-3 w-3" />
              Create venv
            </Button>
          ) : (
            <Button
              size="sm"
              className="h-7 text-xs gap-1.5"
              onClick={() => stream("install")}
              disabled={busy}
              title="Install requirements into the venv"
            >
              <Download className="h-3 w-3" />
              Install
            </Button>
          )}
        </div>

        {/* installed toggle */}
        {venvExists && (
          <Button
            variant="ghost"
            size="sm"
            className="h-7 text-xs gap-1.5"
            onClick={() => { setShowPackages((v) => !v); if (!showPackages) refreshPackages(); }}
          >
            <Package className="h-3 w-3" />
            {showPackages ? "Hide list" : "Installed"}
          </Button>
        )}

        {/* danger group — right aligned */}
        {venvExists && (
          <div className="ml-auto flex items-center gap-1 pl-2 border-l border-border">
            <Button
              variant="ghost"
              size="sm"
              className="h-7 text-xs gap-1.5 text-muted-foreground hover:text-foreground"
              disabled={busy}
              onClick={() => setConfirmKind("recreate")}
              title="Delete the venv and create a fresh one"
            >
              <RefreshCw className="h-3 w-3" />
              Recreate
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="h-7 text-xs gap-1.5 text-muted-foreground hover:text-destructive"
              disabled={busy}
              onClick={() => setConfirmKind("delete")}
              title="Delete the venv"
            >
              <Trash2 className="h-3 w-3" />
              Delete
            </Button>
          </div>
        )}
      </div>

      {/* ── Body ───────────────────────────────────────────────────────── */}
      <div className="flex flex-1 min-h-0 overflow-hidden">
        {/* requirements.txt editor */}
        <div className="flex-1 min-w-0 flex flex-col">
          <textarea
            value={requirements}
            onChange={(e) => onRequirementsChange(e.target.value)}
            onBlur={persistRequirementsIfDirty}
            className="flex-1 w-full bg-transparent px-3 py-2 text-xs font-mono text-foreground resize-none focus:outline-none placeholder:text-muted-foreground"
            placeholder={"langgraph\nlangchain-openai\nrequests\n# one package per line"}
            spellCheck={false}
          />
          <div className="text-[10px] text-muted-foreground px-3 py-1 border-t border-border/50">
            requirements.txt · autosaved on blur
          </div>
        </div>

        {/* installed packages list */}
        {showPackages && (
          <div className="w-56 border-l border-border shrink-0">
            <ScrollArea className="h-full">
              <div className="p-2 font-mono text-xs space-y-0.5">
                {pkgError && (
                  <div className="text-red-400 whitespace-pre-wrap break-all">{pkgError}</div>
                )}
                {!pkgError && packages.length === 0 ? (
                  <div className="text-muted-foreground">no packages</div>
                ) : packages.map((p) => (
                  <div key={p.name} className="flex justify-between gap-2">
                    <span className="truncate">{p.name}</span>
                    <span className="text-muted-foreground shrink-0">{p.version}</span>
                  </div>
                ))}
              </div>
            </ScrollArea>
          </div>
        )}

        {/* install / venv stream output */}
        {lines.length > 0 && (
          <div className="w-56 border-l border-border shrink-0">
            <ScrollArea className="h-full">
              <div ref={logsRef} className="p-2 font-mono text-xs space-y-0.5">
                {lines.map((l, i) => (
                  <div
                    key={i}
                    className={
                      l.startsWith("ERROR") ? "text-red-400" :
                      l === "DONE" ? "text-emerald-400" :
                      "text-muted-foreground"
                    }
                  >
                    {l}
                  </div>
                ))}
              </div>
            </ScrollArea>
          </div>
        )}
      </div>

      {/* ── Confirm dialog ─────────────────────────────────────────────── */}
      <Dialog open={confirmKind !== null} onOpenChange={(o) => !o && setConfirmKind(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-amber-400" />
              {confirmKind === "delete" ? "Delete venv?" : "Recreate venv?"}
            </DialogTitle>
            <DialogDescription>
              {confirmKind === "delete"
                ? "This permanently deletes the script's .venv directory. You'll need to recreate it before running the script."
                : "This deletes the existing .venv directory and creates a fresh one. Installed packages will be gone — re-run Install to restore them."}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmKind(null)}>Cancel</Button>
            <Button
              variant="destructive"
              onClick={async () => {
                const kind = confirmKind;
                setConfirmKind(null);
                if (kind === "delete") await doDelete();
                else if (kind === "recreate") await stream("venv", true);
              }}
            >
              {confirmKind === "delete" ? "Delete" : "Recreate"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
