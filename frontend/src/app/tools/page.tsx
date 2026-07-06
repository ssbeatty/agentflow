"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import {
  ArrowLeft, Plus, Trash2, ToggleLeft, ToggleRight, Globe, Terminal, Radio,
  Activity, Plug, Unplug, Loader2, ShieldCheck, ShieldAlert, XCircle,
  Sparkles, Pencil, Store, Search, Save,
} from "lucide-react";
import { toast } from "sonner";
import { mcpServers, skills, searchConfig } from "@/lib/api";
import type { MCPServerConfig, MCPProbeResult, SkillSummary, SearchConfig } from "@/lib/types";
import SkillMarketplaceDialog from "@/components/SkillMarketplaceDialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
import { useConfirm } from "@/components/ConfirmDialogProvider";

type Transport = MCPServerConfig["transport"];
type AuthType = "none" | "oauth2";

interface FormState {
  name: string;
  transport: Transport;
  url: string;
  command: string;
  args: string;       // newline-separated list
  env_vars: string;   // JSON string
  headers: string;    // JSON string
  enabled: boolean;
  auth_type: AuthType;
  oauth_scope: string;
}

const EMPTY_FORM: FormState = {
  name: "", transport: "http", url: "", command: "", args: "", env_vars: "", headers: "",
  enabled: true, auth_type: "none", oauth_scope: "",
};

const TRANSPORT_ICONS: Record<Transport, React.ReactNode> = {
  http: <Globe className="h-3.5 w-3.5" />,
  sse: <Radio className="h-3.5 w-3.5" />,
  stdio: <Terminal className="h-3.5 w-3.5" />,
  websocket: <Globe className="h-3.5 w-3.5" />,
};

function parseJson(s: string): Record<string, string> | undefined {
  if (!s.trim()) return undefined;
  try { return JSON.parse(s); } catch { return undefined; }
}

function fmtJson(v: Record<string, string> | undefined): string {
  if (!v || !Object.keys(v).length) return "";
  return JSON.stringify(v, null, 2);
}

export default function ToolsPage() {
  const { t } = useTranslation("tools");
  const router = useRouter();
  const confirm = useConfirm();
  const [servers, setServers] = useState<MCPServerConfig[]>([]);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [probing, setProbing] = useState<string | null>(null);
  const [connecting, setConnecting] = useState<string | null>(null);
  const [probeResult, setProbeResult] = useState<{ srv: MCPServerConfig; result: MCPProbeResult } | null>(null);

  // ── Skills ──────────────────────────────────────────────────────────────
  const [skillList, setSkillList] = useState<SkillSummary[]>([]);
  const [skillDialogOpen, setSkillDialogOpen] = useState(false);
  const [skillForm, setSkillForm] = useState({ name: "", description: "" });
  const [creatingSkill, setCreatingSkill] = useState(false);
  const [marketplaceOpen, setMarketplaceOpen] = useState(false);

  // ── Web search provider ───────────────────────────────────────────────────
  const [search, setSearch] = useState<SearchConfig | null>(null);
  const [searchProvider, setSearchProvider] = useState<"tavily" | "duckduckgo">("tavily");
  const [tavilyKey, setTavilyKey] = useState("");        // "" = leave stored key untouched
  const [savingSearch, setSavingSearch] = useState(false);
  const [testingSearch, setTestingSearch] = useState(false);

  useEffect(() => { load(); loadSkills(); loadSearch(); }, []);

  async function loadSearch() {
    try {
      const cfg = await searchConfig.get();
      setSearch(cfg);
      setSearchProvider(cfg.provider);
    } catch { toast.error(t("webSearch.toast.loadFailed")); }
  }

  async function saveSearch() {
    setSavingSearch(true);
    try {
      const payload: { provider: string; tavily_api_key?: string } = { provider: searchProvider };
      // Only send the key when the operator typed a new one (blank leaves it as-is).
      if (tavilyKey.trim()) payload.tavily_api_key = tavilyKey.trim();
      const cfg = await searchConfig.update(payload);
      setSearch(cfg);
      setSearchProvider(cfg.provider);
      setTavilyKey("");
      toast.success(t("webSearch.toast.saved"));
    } catch (e: unknown) {
      toast.error(String(e));
    } finally {
      setSavingSearch(false);
    }
  }

  async function clearTavilyKey() {
    setSavingSearch(true);
    try {
      const cfg = await searchConfig.update({ tavily_api_key: "" });
      setSearch(cfg);
      setTavilyKey("");
      toast.success(t("webSearch.toast.keyRemoved"));
    } catch (e: unknown) {
      toast.error(String(e));
    } finally {
      setSavingSearch(false);
    }
  }

  async function testTavily() {
    setTestingSearch(true);
    try {
      // Test the freshly typed key if present, else the stored one.
      const res = await searchConfig.test(tavilyKey.trim() ? { tavily_api_key: tavilyKey.trim() } : {});
      if (res.ok) toast.success(t("webSearch.toast.tavilyOk", { count: res.results ?? 0 }));
      else toast.error(t("webSearch.toast.tavilyError", { error: res.error ?? t("webSearch.toast.testFailedFallback") }));
    } catch (e: unknown) {
      toast.error(String(e));
    } finally {
      setTestingSearch(false);
    }
  }

  async function loadSkills() {
    try { setSkillList(await skills.list()); }
    catch { toast.error(t("skills.toast.loadFailed")); }
  }

  async function createSkill() {
    if (!skillForm.name.trim()) return toast.error(t("skills.toast.nameRequired"));
    setCreatingSkill(true);
    try {
      const created = await skills.create({
        name: skillForm.name.trim(),
        description: skillForm.description.trim(),
      });
      setSkillDialogOpen(false);
      setSkillForm({ name: "", description: "" });
      router.push(`/skill?id=${created.id}`);
    } catch (e: unknown) {
      toast.error(String(e));
    } finally {
      setCreatingSkill(false);
    }
  }

  async function toggleSkillEnabled(sk: SkillSummary) {
    try {
      const updated = await skills.update(sk.id, { enabled: !sk.enabled });
      setSkillList(prev => prev.map(s => s.id === sk.id ? { ...s, enabled: updated.enabled } : s));
    } catch { toast.error(t("skills.toast.updateFailed")); }
  }

  async function removeSkill(id: string) {
    if (!(await confirm(t("skills.confirm.message"), { confirmLabel: t("skills.confirm.confirmLabel"), destructive: true }))) return;
    try {
      await skills.delete(id);
      setSkillList(prev => prev.filter(s => s.id !== id));
      toast.success(t("skills.toast.deleted"));
    } catch { toast.error(t("skills.toast.deleteFailed")); }
  }

  // The OAuth callback window posts back here when sign-in completes.
  useEffect(() => {
    function onMsg(e: MessageEvent) {
      const d = e.data as { source?: string; ok?: boolean; detail?: string } | null;
      if (d && typeof d === "object" && d.source === "agentflow-oauth") {
        if (d.ok) { toast.success(t("mcpServers.toast.oauthConnected")); load(); }
        else toast.error(d.detail ? t("mcpServers.toast.oauthFailedDetail", { detail: d.detail }) : t("mcpServers.toast.oauthFailed"));
      }
    }
    window.addEventListener("message", onMsg);
    return () => window.removeEventListener("message", onMsg);
  }, [t]);

  async function load() {
    try { setServers(await mcpServers.list()); }
    catch { toast.error(t("mcpServers.toast.loadFailed")); }
  }

  function openCreate() {
    setEditId(null);
    setForm(EMPTY_FORM);
    setDialogOpen(true);
  }

  function openEdit(srv: MCPServerConfig) {
    setEditId(srv.id);
    setForm({
      name: srv.name,
      transport: srv.transport,
      url: srv.url ?? "",
      command: srv.command ?? "",
      args: (srv.args ?? []).join("\n"),
      env_vars: fmtJson(srv.env_vars as Record<string, string>),
      headers: fmtJson(srv.headers as Record<string, string>),
      enabled: srv.enabled,
      auth_type: srv.auth_type ?? "none",
      oauth_scope: srv.oauth_scope ?? "",
    });
    setDialogOpen(true);
  }

  async function save() {
    if (!form.name.trim()) return toast.error(t("mcpServers.toast.nameRequired"));
    const isNetwork = form.transport !== "stdio";
    if (isNetwork && !form.url.trim()) return toast.error(t("mcpServers.toast.urlRequired"));
    if (!isNetwork && !form.command.trim()) return toast.error(t("mcpServers.toast.commandRequired"));

    const headers = parseJson(form.headers);
    const env_vars = parseJson(form.env_vars);
    if (form.headers.trim() && headers === undefined) return toast.error(t("mcpServers.toast.headersInvalid"));
    if (form.env_vars.trim() && env_vars === undefined) return toast.error(t("mcpServers.toast.envVarsInvalid"));

    const authType: AuthType = isNetwork ? form.auth_type : "none";
    const payload = {
      name: form.name.trim(),
      transport: form.transport,
      url: form.url.trim() || undefined,
      command: form.command.trim() || undefined,
      args: form.args.trim() ? form.args.split("\n").map(s => s.trim()).filter(Boolean) : undefined,
      env_vars,
      headers,
      enabled: form.enabled,
      auth_type: authType,
      ...(authType === "oauth2" ? { oauth_config: { scope: form.oauth_scope.trim() } } : {}),
    };

    setSaving(true);
    try {
      if (editId) {
        const updated = await mcpServers.update(editId, payload);
        setServers(prev => prev.map(s => s.id === editId ? updated : s));
      } else {
        const created = await mcpServers.create(payload);
        setServers(prev => [...prev, created]);
      }
      setDialogOpen(false);
      toast.success(editId ? t("mcpServers.toast.updated") : t("mcpServers.toast.created"));
    } catch (e: unknown) {
      toast.error(String(e));
    } finally {
      setSaving(false);
    }
  }

  async function remove(id: string) {
    if (!(await confirm(t("mcpServers.confirm.message"), { confirmLabel: t("mcpServers.confirm.confirmLabel"), destructive: true }))) return;
    try {
      await mcpServers.delete(id);
      setServers(prev => prev.filter(s => s.id !== id));
      toast.success(t("mcpServers.toast.deleted"));
    } catch { toast.error(t("mcpServers.toast.deleteFailed")); }
  }

  async function toggleEnabled(srv: MCPServerConfig) {
    try {
      const updated = await mcpServers.update(srv.id, { enabled: !srv.enabled });
      setServers(prev => prev.map(s => s.id === srv.id ? updated : s));
    } catch { toast.error(t("mcpServers.toast.updateFailed")); }
  }

  async function testConnection(srv: MCPServerConfig) {
    setProbing(srv.id);
    try {
      const result = await mcpServers.probe(srv.id);
      setProbeResult({ srv, result });
      if (result.ok) toast.success(t("mcpServers.toast.testFound", { name: srv.name, count: result.tools.length }));
      else if (result.needs_auth) toast.error(t("mcpServers.toast.testAuthRequired", { name: srv.name }));
      else toast.error(t("mcpServers.toast.testFailed", { name: srv.name }));
    } catch (e: unknown) {
      toast.error(String(e));
    } finally {
      setProbing(null);
    }
  }

  async function connectOauth(srv: MCPServerConfig) {
    setConnecting(srv.id);
    try {
      const { authorize_url } = await mcpServers.oauthAuthorizeUrl(srv.id);
      const w = window.open(authorize_url, "agentflow_oauth", "width=620,height=780");
      if (!w) toast.error(t("mcpServers.toast.popupBlocked"));
    } catch (e: unknown) {
      toast.error(t("mcpServers.toast.oauthError", { error: String(e) }));
    } finally {
      setConnecting(null);
    }
  }

  async function disconnectOauth(srv: MCPServerConfig) {
    try {
      const updated = await mcpServers.oauthDisconnect(srv.id);
      setServers(prev => prev.map(s => s.id === srv.id ? updated : s));
      toast.success(t("mcpServers.toast.disconnected"));
    } catch { toast.error(t("mcpServers.toast.disconnectFailed")); }
  }

  const isNetwork = form.transport !== "stdio";

  return (
    <div className="min-h-screen">
      <header className="border-b border-border px-6 py-3 flex items-center gap-3">
        <Link href="/">
          <Button variant="ghost" size="icon"><ArrowLeft className="h-4 w-4" /></Button>
        </Link>
        <h1 className="font-semibold">{t("page.title")}</h1>
      </header>

      <main className="max-w-2xl mx-auto px-6 py-8">
        {/* Built-in tools info */}
        <div className="mb-8 rounded-lg border border-border bg-secondary/20 p-4">
          <h2 className="font-medium text-sm mb-1">{t("builtinTools.heading")}</h2>
          <p className="text-xs text-muted-foreground mb-3">
            {t("builtinTools.description.prefix")}{" "}
            <code className="font-mono bg-muted px-1 rounded">web_search</code> /{" "}
            <code className="font-mono bg-muted px-1 rounded">web_fetch</code>{" "}
            {t("builtinTools.description.suffix")}
          </p>
          <div className="flex gap-2 flex-wrap">
            {[
              {
                name: "web_fetch",
                desc: search?.tavily_connected ? t("builtinTools.webFetch.tavilyConnected") : t("builtinTools.webFetch.default"),
              },
              {
                name: "web_search",
                desc: searchProvider === "tavily" && search?.tavily_connected
                  ? t("builtinTools.webSearchTool.tavilyConnected")
                  : t("builtinTools.webSearchTool.default"),
              },
            ].map(item => (
              <div key={item.name} className="rounded-md border border-border bg-background px-3 py-1.5">
                <code className="text-xs font-mono text-primary">{item.name}</code>
                <span className="text-xs text-muted-foreground ml-2">{item.desc}</span>
              </div>
            ))}
          </div>
          <p className="text-xs text-muted-foreground mt-3">
            {t("builtinTools.usageLabel")}{" "}
            <code className="font-mono bg-muted px-1 rounded">from agentflow import get_tools, get_agent</code>
          </p>
        </div>

        {/* Web search provider */}
        <div className="mb-8 rounded-lg border border-border p-4">
          <div className="flex items-center gap-2 mb-1">
            <Search className="h-4 w-4 text-muted-foreground" />
            <h2 className="font-medium text-sm">{t("webSearch.heading")}</h2>
          </div>
          <p className="text-xs text-muted-foreground mb-3">
            {t("webSearch.description.prefix")} <code className="font-mono bg-muted px-1 rounded">web_search</code> /{" "}
            <code className="font-mono bg-muted px-1 rounded">web_fetch</code>{" "}
            {t("webSearch.description.suffix")}
          </p>

          <div className="space-y-3">
            <div className="flex items-center gap-3">
              <Label className="text-xs w-20 shrink-0">{t("webSearch.providerLabel")}</Label>
              <Select value={searchProvider} onValueChange={(v) => setSearchProvider(v as "tavily" | "duckduckgo")}>
                <SelectTrigger className="h-8 w-56"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="tavily">{t("webSearch.tavilyOption")}</SelectItem>
                  <SelectItem value="duckduckgo">{t("webSearch.duckduckgoOption")}</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {searchProvider === "tavily" && (
              <div className="flex items-center gap-3">
                <Label className="text-xs w-20 shrink-0">{t("webSearch.tavilyKeyLabel")}</Label>
                <div className="flex-1 flex items-center gap-2">
                  <Input
                    type="password"
                    value={tavilyKey}
                    onChange={(e) => setTavilyKey(e.target.value)}
                    placeholder={
                      search?.tavily_connected
                        ? t("webSearch.tavilyKeyPlaceholderSaved", { preview: search.tavily_key_preview })
                        : t("webSearch.tavilyKeyPlaceholderDefault")
                    }
                    className="h-8 font-mono text-xs"
                  />
                  {search?.tavily_connected && (
                    <Badge variant="outline" className="gap-1 border-green-600/40 text-green-600 shrink-0">
                      <ShieldCheck className="h-3 w-3" />{t("webSearch.keySetBadge")}
                    </Badge>
                  )}
                </div>
              </div>
            )}

            <div className="flex items-center gap-2 pt-1">
              <Button size="sm" onClick={saveSearch} disabled={savingSearch}>
                {savingSearch ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                <span className="ml-1">{t("webSearch.saveButton")}</span>
              </Button>
              {searchProvider === "tavily" && (
                <Button size="sm" variant="ghost" onClick={testTavily}
                  disabled={testingSearch || (!tavilyKey.trim() && !search?.tavily_connected)}>
                  {testingSearch ? <Loader2 className="h-4 w-4 animate-spin" /> : <Activity className="h-4 w-4" />}
                  <span className="ml-1 text-xs">{t("webSearch.testButton")}</span>
                </Button>
              )}
              {searchProvider === "tavily" && search?.tavily_connected && (
                <Button size="sm" variant="ghost" onClick={clearTavilyKey} disabled={savingSearch}
                  className="text-muted-foreground">
                  <Trash2 className="h-4 w-4" />
                  <span className="ml-1 text-xs">{t("webSearch.removeKeyButton")}</span>
                </Button>
              )}
            </div>
          </div>
        </div>

        {/* MCP Servers */}
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="font-medium">{t("mcpServers.heading")}</h2>
            <p className="text-xs text-muted-foreground mt-0.5">
              {t("mcpServers.description.prefix")}{" "}
              <code className="font-mono bg-muted px-1 rounded">get_tools()</code> /{" "}
              <code className="font-mono bg-muted px-1 rounded">get_agent()</code>{" "}
              {t("mcpServers.description.suffix")}
            </p>
          </div>
          <Button size="sm" onClick={openCreate}>
            <Plus className="h-4 w-4" />
            {t("mcpServers.addButton")}
          </Button>
        </div>

        <div className="space-y-3">
          {servers.length === 0 && (
            <p className="text-sm text-muted-foreground text-center py-8">
              {t("mcpServers.empty")}
            </p>
          )}
          {servers.map(srv => (
            <div key={srv.id} className="border border-border rounded-lg p-4 flex items-center justify-between gap-3">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-medium text-sm">{srv.name}</span>
                  <Badge variant={srv.enabled ? "default" : "secondary"} className="gap-1">
                    {TRANSPORT_ICONS[srv.transport]}
                    {srv.transport}
                  </Badge>
                  {!srv.enabled && <Badge variant="outline">{t("mcpServers.disabledBadge")}</Badge>}
                  {srv.auth_type === "oauth2" && (
                    srv.oauth_connected
                      ? <Badge variant="outline" className="gap-1 border-green-600/40 text-green-600">
                          <ShieldCheck className="h-3 w-3" />{t("mcpServers.authorizedBadge")}
                        </Badge>
                      : <Badge variant="outline" className="gap-1 border-amber-600/40 text-amber-600">
                          <ShieldAlert className="h-3 w-3" />{t("mcpServers.notConnectedBadge")}
                        </Badge>
                  )}
                </div>
                <p className="text-xs text-muted-foreground mt-0.5 font-mono truncate">
                  {srv.url || srv.command || "—"}
                </p>
              </div>
              <div className="flex items-center gap-1 shrink-0">
                <Button variant="ghost" size="sm" onClick={() => testConnection(srv)}
                  disabled={probing === srv.id} title={t("mcpServers.testTitle")}>
                  {probing === srv.id
                    ? <Loader2 className="h-4 w-4 animate-spin" />
                    : <Activity className="h-4 w-4" />}
                  <span className="text-xs ml-1">{t("mcpServers.testButton")}</span>
                </Button>
                {srv.auth_type === "oauth2" && (
                  <Button variant="ghost" size="sm" onClick={() => connectOauth(srv)}
                    disabled={connecting === srv.id} title={srv.oauth_connected ? t("mcpServers.reauthorizeTitle") : t("mcpServers.signInTitle")}>
                    {connecting === srv.id
                      ? <Loader2 className="h-4 w-4 animate-spin" />
                      : <Plug className="h-4 w-4" />}
                    <span className="text-xs ml-1">{srv.oauth_connected ? t("mcpServers.reconnectButton") : t("mcpServers.connectButton")}</span>
                  </Button>
                )}
                {srv.auth_type === "oauth2" && srv.oauth_connected && (
                  <Button variant="ghost" size="icon" onClick={() => disconnectOauth(srv)} title={t("mcpServers.disconnectTitle")}>
                    <Unplug className="h-4 w-4 text-muted-foreground" />
                  </Button>
                )}
                <Button variant="ghost" size="icon" onClick={() => toggleEnabled(srv)} title={srv.enabled ? t("mcpServers.disableTitle") : t("mcpServers.enableTitle")}>
                  {srv.enabled
                    ? <ToggleRight className="h-4 w-4 text-primary" />
                    : <ToggleLeft className="h-4 w-4 text-muted-foreground" />}
                </Button>
                <Button variant="ghost" size="icon" onClick={() => openEdit(srv)}>
                  <span className="text-xs">{t("mcpServers.editButton")}</span>
                </Button>
                <Button variant="ghost" size="icon" onClick={() => remove(srv.id)}>
                  <Trash2 className="h-4 w-4 text-destructive" />
                </Button>
              </div>
            </div>
          ))}
        </div>

        {/* Usage hint */}
        {servers.some(s => s.enabled) && (
          <div className="mt-6 rounded-lg border border-border bg-secondary/20 p-4 text-xs text-muted-foreground space-y-2">
            <p className="font-medium text-foreground">{t("mcpServers.usageHint.heading")}</p>
            <pre className="font-mono text-xs overflow-x-auto">{`from agentflow import get_agent, get_tools

# Zero-config: built-ins + this script's selected MCP servers + bound skills
def run(input: dict) -> dict:
    agent = get_agent()
    result = agent.invoke({"messages": [("user", input["message"])]})
    return {"reply": result["messages"][-1].content}

# Explicit: compose your own tool list
def run(input: dict) -> dict:
    tools = get_tools()          # built-ins + this script's selected MCP servers
    llm = get_llm().bind_tools(tools)
    ...`}</pre>
          </div>
        )}

        {/* Skills */}
        <Separator className="my-8" />
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="font-medium flex items-center gap-1.5">
              <Sparkles className="h-4 w-4 text-primary" /> {t("skills.heading")}
            </h2>
            <p className="text-xs text-muted-foreground mt-0.5">
              {t("skills.description.prefix")}{" "}
              <code className="font-mono bg-muted px-1 rounded">get_agent()</code> {t("skills.description.middle")} <code className="font-mono bg-muted px-1 rounded">read_skill</code> {t("skills.description.suffix")}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button size="sm" variant="outline" onClick={() => setMarketplaceOpen(true)}>
              <Store className="h-4 w-4" />
              {t("skills.browseMarketplace")}
            </Button>
            <Button size="sm" onClick={() => { setSkillForm({ name: "", description: "" }); setSkillDialogOpen(true); }}>
              <Plus className="h-4 w-4" />
              {t("skills.newSkill")}
            </Button>
          </div>
        </div>

        <div className="space-y-3">
          {skillList.length === 0 && (
            <p className="text-sm text-muted-foreground text-center py-8">
              {t("skills.empty")}
            </p>
          )}
          {skillList.map(sk => (
            <div key={sk.id} className="border border-border rounded-lg p-4 flex items-center justify-between gap-3">
              <Link href={`/skill?id=${sk.id}`} className="min-w-0 flex-1 group">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-medium text-sm group-hover:text-primary">{sk.name}</span>
                  {!sk.enabled && <Badge variant="outline">{t("skills.disabledBadge")}</Badge>}
                </div>
                <p className="text-xs text-muted-foreground mt-0.5 truncate">
                  {sk.description || t("skills.noDescription")}
                </p>
              </Link>
              <div className="flex items-center gap-1 shrink-0">
                <Button variant="ghost" size="icon" onClick={() => toggleSkillEnabled(sk)} title={sk.enabled ? t("skills.disableTitle") : t("skills.enableTitle")}>
                  {sk.enabled
                    ? <ToggleRight className="h-4 w-4 text-primary" />
                    : <ToggleLeft className="h-4 w-4 text-muted-foreground" />}
                </Button>
                <Button variant="ghost" size="icon" onClick={() => router.push(`/skill?id=${sk.id}`)} title={t("skills.editTitle")}>
                  <Pencil className="h-4 w-4" />
                </Button>
                <Button variant="ghost" size="icon" onClick={() => removeSkill(sk.id)}>
                  <Trash2 className="h-4 w-4 text-destructive" />
                </Button>
              </div>
            </div>
          ))}
        </div>

        {/* Skills usage hint */}
        {skillList.length > 0 && (
          <div className="mt-6 rounded-lg border border-border bg-secondary/20 p-4 text-xs text-muted-foreground space-y-2">
            <p className="font-medium text-foreground">{t("skills.usageHint.heading")}</p>
            <p>{t("skills.usageHint.intro")}</p>
            <pre className="font-mono text-xs overflow-x-auto">{`from agentflow import get_agent, get_deep_agent

# Lightweight — agent loads a skill's SKILL.md via the built-in read_skill tool
def run(input: dict) -> dict:
    agent = get_agent(system_prompt="Use the available skills.")
    result = agent.invoke({"messages": [("user", input["message"])]})
    return {"reply": result["messages"][-1].content}

# Deep agent — mounts skills/ so the agent reads every skill file itself
async def run(input: dict) -> dict:
    agent = get_deep_agent(system_prompt="Use the available skills.")
    result = await agent.ainvoke({"messages": [("user", input["message"])]})
    return {"reply": result["messages"][-1].content}`}</pre>
            <p>
              {t("skills.usageHint.examplesPrefix")}{" "}
              <code className="font-mono bg-muted px-1 rounded">examples/skill_agent.py</code>{" "}
              &{" "}
              <code className="font-mono bg-muted px-1 rounded">examples/skill_deep_agent.py</code>.
              {" "}{t("skills.usageHint.loadedPrefix")} <span className="font-medium">Loaded skill: …</span> {t("skills.usageHint.loadedSuffix")}
            </p>
          </div>
        )}
      </main>

      {/* Skill marketplace */}
      <SkillMarketplaceDialog
        open={marketplaceOpen}
        onOpenChange={setMarketplaceOpen}
        onInstalled={loadSkills}
      />

      {/* Add / Edit dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>{editId ? t("mcpServers.dialog.editTitle") : t("mcpServers.dialog.addTitle")}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label>{t("mcpServers.dialog.name")}</Label>
                <Input
                  value={form.name}
                  onChange={e => setForm(p => ({ ...p, name: e.target.value }))}
                  placeholder={t("mcpServers.dialog.namePlaceholder")}
                />
              </div>
              <div className="space-y-1.5">
                <Label>{t("mcpServers.dialog.transport")}</Label>
                <Select
                  value={form.transport}
                  onValueChange={v => setForm(p => ({ ...p, transport: v as Transport }))}
                >
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="http">{t("mcpServers.dialog.transportHttp")}</SelectItem>
                    <SelectItem value="sse">{t("mcpServers.dialog.transportSse")}</SelectItem>
                    <SelectItem value="stdio">{t("mcpServers.dialog.transportStdio")}</SelectItem>
                    <SelectItem value="websocket">{t("mcpServers.dialog.transportWebsocket")}</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>

            {isNetwork ? (
              <div className="space-y-1.5">
                <Label>{t("mcpServers.dialog.url")}</Label>
                <Input
                  value={form.url}
                  onChange={e => setForm(p => ({ ...p, url: e.target.value }))}
                  placeholder={t("mcpServers.dialog.urlPlaceholder")}
                />
              </div>
            ) : (
              <>
                <div className="space-y-1.5">
                  <Label>{t("mcpServers.dialog.command")}</Label>
                  <Input
                    value={form.command}
                    onChange={e => setForm(p => ({ ...p, command: e.target.value }))}
                    placeholder={t("mcpServers.dialog.commandPlaceholder")}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label>{t("mcpServers.dialog.args")} <span className="text-muted-foreground">{t("mcpServers.dialog.argsHint")}</span></Label>
                  <Textarea
                    value={form.args}
                    onChange={e => setForm(p => ({ ...p, args: e.target.value }))}
                    placeholder={t("mcpServers.dialog.argsPlaceholder")}
                    rows={3}
                    className="font-mono text-xs"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label>{t("mcpServers.dialog.envVars")} <span className="text-muted-foreground">{t("mcpServers.dialog.envVarsHint")}</span></Label>
                  <Textarea
                    value={form.env_vars}
                    onChange={e => setForm(p => ({ ...p, env_vars: e.target.value }))}
                    placeholder={t("mcpServers.dialog.envVarsPlaceholder")}
                    rows={2}
                    className="font-mono text-xs"
                  />
                </div>
              </>
            )}

            {isNetwork && (
              <>
                <div className="space-y-1.5">
                  <Label>{t("mcpServers.dialog.authentication")}</Label>
                  <Select
                    value={form.auth_type}
                    onValueChange={v => setForm(p => ({ ...p, auth_type: v as AuthType }))}
                  >
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="none">{t("mcpServers.dialog.authNone")}</SelectItem>
                      <SelectItem value="oauth2">{t("mcpServers.dialog.authOauth2")}</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                {form.auth_type === "oauth2" && (
                  <div className="space-y-1.5">
                    <Label>{t("mcpServers.dialog.oauthScope")} <span className="text-muted-foreground">{t("mcpServers.dialog.optional")}</span></Label>
                    <Input
                      value={form.oauth_scope}
                      onChange={e => setForm(p => ({ ...p, oauth_scope: e.target.value }))}
                      placeholder={t("mcpServers.dialog.oauthScopePlaceholder")}
                      className="font-mono text-xs"
                    />
                    <p className="text-xs text-muted-foreground">
                      {t("mcpServers.dialog.oauthHint.prefix")} <span className="font-medium">{t("mcpServers.connectButton")}</span>{" "}
                      {t("mcpServers.dialog.oauthHint.suffix")}
                    </p>
                  </div>
                )}

                {form.auth_type === "none" && (
                  <div className="space-y-1.5">
                    <Label>{t("mcpServers.dialog.headers")} <span className="text-muted-foreground">{t("mcpServers.dialog.headersHint")}</span></Label>
                    <Textarea
                      value={form.headers}
                      onChange={e => setForm(p => ({ ...p, headers: e.target.value }))}
                      placeholder={t("mcpServers.dialog.headersPlaceholder")}
                      rows={2}
                      className="font-mono text-xs"
                    />
                  </div>
                )}
              </>
            )}

            <Separator />
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={form.enabled}
                onChange={e => setForm(p => ({ ...p, enabled: e.target.checked }))}
                className="rounded"
              />
              <span className="text-sm">{t("mcpServers.dialog.enabledCheckbox")}</span>
            </label>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>{t("mcpServers.dialog.cancel")}</Button>
            <Button onClick={save} disabled={saving}>{saving ? t("mcpServers.dialog.saving") : t("mcpServers.dialog.save")}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Probe result dialog */}
      <Dialog open={!!probeResult} onOpenChange={o => { if (!o) setProbeResult(null); }}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>{t("mcpServers.probeDialog.title", { name: probeResult?.srv.name })}</DialogTitle>
          </DialogHeader>
          {probeResult && (probeResult.result.ok ? (
            <div className="space-y-2 max-h-[60vh] overflow-y-auto pr-1">
              <p className="text-xs text-muted-foreground">
                {t("mcpServers.probeDialog.connectedCount", { count: probeResult.result.tools.length })}
              </p>
              {probeResult.result.tools.length === 0 && (
                <p className="text-sm text-muted-foreground">{t("mcpServers.probeDialog.noTools")}</p>
              )}
              {probeResult.result.tools.map(tool => (
                <details key={tool.name} className="rounded-md border border-border p-2.5">
                  <summary className="cursor-pointer text-sm font-mono text-primary">
                    {tool.name}
                    {tool.title && <span className="text-muted-foreground font-sans ml-2">{tool.title}</span>}
                  </summary>
                  {tool.description && (
                    <p className="text-xs text-muted-foreground mt-1.5 whitespace-pre-wrap">{tool.description}</p>
                  )}
                  <pre className="mt-2 text-[11px] font-mono bg-muted/50 rounded p-2 overflow-x-auto">
                    {JSON.stringify(tool.input_schema, null, 2)}
                  </pre>
                </details>
              ))}
            </div>
          ) : (
            <div className="space-y-3">
              <div className="flex items-start gap-2 text-sm text-destructive">
                <XCircle className="h-4 w-4 mt-0.5 shrink-0" />
                <span className="break-words">{probeResult.result.error}</span>
              </div>
              {probeResult.result.needs_auth && probeResult.srv.auth_type === "oauth2" && (
                <Button size="sm" onClick={() => { connectOauth(probeResult.srv); setProbeResult(null); }}>
                  <Plug className="h-4 w-4" /> {t("mcpServers.connectButton")}
                </Button>
              )}
              {probeResult.result.needs_auth && probeResult.srv.auth_type !== "oauth2" && (
                <p className="text-xs text-muted-foreground">
                  {t("mcpServers.probeDialog.authRequiredHint.prefix")}
                  {" "}<span className="font-medium">{t("mcpServers.probeDialog.oauth2Label")}</span>{t("mcpServers.probeDialog.authRequiredHint.suffix")}{" "}
                  <code className="font-mono bg-muted px-1 rounded">Authorization</code> {t("mcpServers.probeDialog.authRequiredHint.suffix2")}
                </p>
              )}
            </div>
          ))}
          <DialogFooter>
            <Button variant="outline" onClick={() => setProbeResult(null)}>{t("mcpServers.probeDialog.close")}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Create skill dialog */}
      <Dialog open={skillDialogOpen} onOpenChange={setSkillDialogOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{t("skills.dialog.title")}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-1.5">
              <Label>{t("skills.dialog.name")}</Label>
              <Input
                value={skillForm.name}
                onChange={e => setSkillForm(p => ({ ...p, name: e.target.value }))}
                placeholder={t("skills.dialog.namePlaceholder")}
                onKeyDown={e => { if (e.key === "Enter") createSkill(); }}
              />
            </div>
            <div className="space-y-1.5">
              <Label>{t("skills.dialog.description")} <span className="text-muted-foreground">{t("skills.dialog.descriptionHint")}</span></Label>
              <Textarea
                value={skillForm.description}
                onChange={e => setSkillForm(p => ({ ...p, description: e.target.value }))}
                placeholder={t("skills.dialog.descriptionPlaceholder")}
                rows={3}
              />
            </div>
            <p className="text-xs text-muted-foreground">
              {t("skills.dialog.hint.prefix")} <code className="font-mono bg-muted px-1 rounded">SKILL.md</code> {t("skills.dialog.hint.suffix")}
            </p>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setSkillDialogOpen(false)}>{t("skills.dialog.cancel")}</Button>
            <Button onClick={createSkill} disabled={creatingSkill}>
              {creatingSkill ? t("skills.dialog.creating") : t("skills.dialog.createAndEdit")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
