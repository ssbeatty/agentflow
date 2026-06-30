"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ArrowLeft, Plus, Trash2, ToggleLeft, ToggleRight, Globe, Terminal, Radio,
  Activity, Plug, Unplug, Loader2, ShieldCheck, ShieldAlert, XCircle,
  Sparkles, Pencil,
} from "lucide-react";
import { toast } from "sonner";
import { mcpServers, skills } from "@/lib/api";
import type { MCPServerConfig, MCPProbeResult, SkillSummary } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";

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
  const router = useRouter();
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

  useEffect(() => { load(); loadSkills(); }, []);

  async function loadSkills() {
    try { setSkillList(await skills.list()); }
    catch { toast.error("Failed to load skills"); }
  }

  async function createSkill() {
    if (!skillForm.name.trim()) return toast.error("Name is required");
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
    } catch { toast.error("Failed to update"); }
  }

  async function removeSkill(id: string) {
    if (!confirm("Delete this skill?")) return;
    try {
      await skills.delete(id);
      setSkillList(prev => prev.filter(s => s.id !== id));
      toast.success("Deleted");
    } catch { toast.error("Failed to delete"); }
  }

  // The OAuth callback window posts back here when sign-in completes.
  useEffect(() => {
    function onMsg(e: MessageEvent) {
      const d = e.data as { source?: string; ok?: boolean; detail?: string } | null;
      if (d && typeof d === "object" && d.source === "agentflow-oauth") {
        if (d.ok) { toast.success("Connected"); load(); }
        else toast.error(`Authorization failed${d.detail ? `: ${d.detail}` : ""}`);
      }
    }
    window.addEventListener("message", onMsg);
    return () => window.removeEventListener("message", onMsg);
  }, []);

  async function load() {
    try { setServers(await mcpServers.list()); }
    catch { toast.error("Failed to load MCP servers"); }
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
    if (!form.name.trim()) return toast.error("Name is required");
    const isNetwork = form.transport !== "stdio";
    if (isNetwork && !form.url.trim()) return toast.error("URL is required for this transport");
    if (!isNetwork && !form.command.trim()) return toast.error("Command is required for stdio");

    const headers = parseJson(form.headers);
    const env_vars = parseJson(form.env_vars);
    if (form.headers.trim() && headers === undefined) return toast.error("Headers must be valid JSON");
    if (form.env_vars.trim() && env_vars === undefined) return toast.error("Env vars must be valid JSON");

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
      toast.success(editId ? "Updated" : "Created");
    } catch (e: unknown) {
      toast.error(String(e));
    } finally {
      setSaving(false);
    }
  }

  async function remove(id: string) {
    if (!confirm("Delete this MCP server?")) return;
    try {
      await mcpServers.delete(id);
      setServers(prev => prev.filter(s => s.id !== id));
      toast.success("Deleted");
    } catch { toast.error("Failed to delete"); }
  }

  async function toggleEnabled(srv: MCPServerConfig) {
    try {
      const updated = await mcpServers.update(srv.id, { enabled: !srv.enabled });
      setServers(prev => prev.map(s => s.id === srv.id ? updated : s));
    } catch { toast.error("Failed to update"); }
  }

  async function testConnection(srv: MCPServerConfig) {
    setProbing(srv.id);
    try {
      const result = await mcpServers.probe(srv.id);
      setProbeResult({ srv, result });
      if (result.ok) toast.success(`${srv.name}: ${result.tools.length} tool(s) found`);
      else if (result.needs_auth) toast.error(`${srv.name}: authentication required`);
      else toast.error(`${srv.name}: connection failed`);
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
      if (!w) toast.error("Popup blocked — allow popups for this site");
    } catch (e: unknown) {
      toast.error(`OAuth: ${String(e)}`);
    } finally {
      setConnecting(null);
    }
  }

  async function disconnectOauth(srv: MCPServerConfig) {
    try {
      const updated = await mcpServers.oauthDisconnect(srv.id);
      setServers(prev => prev.map(s => s.id === srv.id ? updated : s));
      toast.success("Disconnected");
    } catch { toast.error("Failed to disconnect"); }
  }

  const isNetwork = form.transport !== "stdio";

  return (
    <div className="min-h-screen">
      <header className="border-b border-border px-6 py-3 flex items-center gap-3">
        <Link href="/">
          <Button variant="ghost" size="icon"><ArrowLeft className="h-4 w-4" /></Button>
        </Link>
        <h1 className="font-semibold">Tools & MCP Servers</h1>
      </header>

      <main className="max-w-2xl mx-auto px-6 py-8">
        {/* Built-in tools info */}
        <div className="mb-8 rounded-lg border border-border bg-secondary/20 p-4">
          <h2 className="font-medium text-sm mb-1">Built-in tools (always available)</h2>
          <p className="text-xs text-muted-foreground mb-3">
            These are injected automatically — no configuration needed.
          </p>
          <div className="flex gap-2 flex-wrap">
            {[
              { name: "web_fetch", desc: "Fetch webpage text" },
              { name: "web_search", desc: "DuckDuckGo search" },
            ].map(t => (
              <div key={t.name} className="rounded-md border border-border bg-background px-3 py-1.5">
                <code className="text-xs font-mono text-primary">{t.name}</code>
                <span className="text-xs text-muted-foreground ml-2">{t.desc}</span>
              </div>
            ))}
          </div>
          <p className="text-xs text-muted-foreground mt-3">
            Usage in scripts:{" "}
            <code className="font-mono bg-muted px-1 rounded">from agentflow import get_tools, get_agent</code>
          </p>
        </div>

        {/* MCP Servers */}
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="font-medium">MCP Servers</h2>
            <p className="text-xs text-muted-foreground mt-0.5">
              Tools from enabled servers are injected into every script run via{" "}
              <code className="font-mono bg-muted px-1 rounded">get_tools()</code>
            </p>
          </div>
          <Button size="sm" onClick={openCreate}>
            <Plus className="h-4 w-4" />
            Add
          </Button>
        </div>

        <div className="space-y-3">
          {servers.length === 0 && (
            <p className="text-sm text-muted-foreground text-center py-8">
              No MCP servers configured. Add one to extend your scripts with external tools.
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
                  {!srv.enabled && <Badge variant="outline">disabled</Badge>}
                  {srv.auth_type === "oauth2" && (
                    srv.oauth_connected
                      ? <Badge variant="outline" className="gap-1 border-green-600/40 text-green-600">
                          <ShieldCheck className="h-3 w-3" />authorized
                        </Badge>
                      : <Badge variant="outline" className="gap-1 border-amber-600/40 text-amber-600">
                          <ShieldAlert className="h-3 w-3" />not connected
                        </Badge>
                  )}
                </div>
                <p className="text-xs text-muted-foreground mt-0.5 font-mono truncate">
                  {srv.url || srv.command || "—"}
                </p>
              </div>
              <div className="flex items-center gap-1 shrink-0">
                <Button variant="ghost" size="sm" onClick={() => testConnection(srv)}
                  disabled={probing === srv.id} title="Test connection & list tools">
                  {probing === srv.id
                    ? <Loader2 className="h-4 w-4 animate-spin" />
                    : <Activity className="h-4 w-4" />}
                  <span className="text-xs ml-1">Test</span>
                </Button>
                {srv.auth_type === "oauth2" && (
                  <Button variant="ghost" size="sm" onClick={() => connectOauth(srv)}
                    disabled={connecting === srv.id} title={srv.oauth_connected ? "Re-authorize" : "Sign in"}>
                    {connecting === srv.id
                      ? <Loader2 className="h-4 w-4 animate-spin" />
                      : <Plug className="h-4 w-4" />}
                    <span className="text-xs ml-1">{srv.oauth_connected ? "Reconnect" : "Connect"}</span>
                  </Button>
                )}
                {srv.auth_type === "oauth2" && srv.oauth_connected && (
                  <Button variant="ghost" size="icon" onClick={() => disconnectOauth(srv)} title="Disconnect">
                    <Unplug className="h-4 w-4 text-muted-foreground" />
                  </Button>
                )}
                <Button variant="ghost" size="icon" onClick={() => toggleEnabled(srv)} title={srv.enabled ? "Disable" : "Enable"}>
                  {srv.enabled
                    ? <ToggleRight className="h-4 w-4 text-primary" />
                    : <ToggleLeft className="h-4 w-4 text-muted-foreground" />}
                </Button>
                <Button variant="ghost" size="icon" onClick={() => openEdit(srv)}>
                  <span className="text-xs">Edit</span>
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
            <p className="font-medium text-foreground">Script usage</p>
            <pre className="font-mono text-xs overflow-x-auto">{`from agentflow import get_agent, get_tools

# Zero-config: get_agent() uses all enabled tools
def run(input: dict) -> dict:
    agent = get_agent()
    result = agent.invoke({"messages": [("user", input["message"])]})
    return {"reply": result["messages"][-1].content}

# Explicit: compose your own tool list
def run(input: dict) -> dict:
    tools = get_tools()          # built-ins + all MCP servers
    llm = get_llm().bind_tools(tools)
    ...`}</pre>
          </div>
        )}

        {/* Skills */}
        <Separator className="my-8" />
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="font-medium flex items-center gap-1.5">
              <Sparkles className="h-4 w-4 text-primary" /> Skills
            </h2>
            <p className="text-xs text-muted-foreground mt-0.5">
              Reusable instructions (SKILL.md + files) an agent loads on demand.
              Bind them per script; <code className="font-mono bg-muted px-1 rounded">get_agent()</code> exposes them via a <code className="font-mono bg-muted px-1 rounded">read_skill</code> tool.
            </p>
          </div>
          <Button size="sm" onClick={() => { setSkillForm({ name: "", description: "" }); setSkillDialogOpen(true); }}>
            <Plus className="h-4 w-4" />
            New skill
          </Button>
        </div>

        <div className="space-y-3">
          {skillList.length === 0 && (
            <p className="text-sm text-muted-foreground text-center py-8">
              No skills yet. Create one to package reusable agent instructions and files.
            </p>
          )}
          {skillList.map(sk => (
            <div key={sk.id} className="border border-border rounded-lg p-4 flex items-center justify-between gap-3">
              <Link href={`/skill?id=${sk.id}`} className="min-w-0 flex-1 group">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-medium text-sm group-hover:text-primary">{sk.name}</span>
                  {!sk.enabled && <Badge variant="outline">disabled</Badge>}
                </div>
                <p className="text-xs text-muted-foreground mt-0.5 truncate">
                  {sk.description || "No description"}
                </p>
              </Link>
              <div className="flex items-center gap-1 shrink-0">
                <Button variant="ghost" size="icon" onClick={() => toggleSkillEnabled(sk)} title={sk.enabled ? "Disable" : "Enable"}>
                  {sk.enabled
                    ? <ToggleRight className="h-4 w-4 text-primary" />
                    : <ToggleLeft className="h-4 w-4 text-muted-foreground" />}
                </Button>
                <Button variant="ghost" size="icon" onClick={() => router.push(`/skill?id=${sk.id}`)} title="Edit">
                  <Pencil className="h-4 w-4" />
                </Button>
                <Button variant="ghost" size="icon" onClick={() => removeSkill(sk.id)}>
                  <Trash2 className="h-4 w-4 text-destructive" />
                </Button>
              </div>
            </div>
          ))}
        </div>
      </main>

      {/* Add / Edit dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>{editId ? "Edit MCP Server" : "Add MCP Server"}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label>Name</Label>
                <Input
                  value={form.name}
                  onChange={e => setForm(p => ({ ...p, name: e.target.value }))}
                  placeholder="my-server"
                />
              </div>
              <div className="space-y-1.5">
                <Label>Transport</Label>
                <Select
                  value={form.transport}
                  onValueChange={v => setForm(p => ({ ...p, transport: v as Transport }))}
                >
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="http">http (Streamable HTTP)</SelectItem>
                    <SelectItem value="sse">sse (Server-Sent Events)</SelectItem>
                    <SelectItem value="stdio">stdio (local process)</SelectItem>
                    <SelectItem value="websocket">websocket</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>

            {isNetwork ? (
              <div className="space-y-1.5">
                <Label>URL</Label>
                <Input
                  value={form.url}
                  onChange={e => setForm(p => ({ ...p, url: e.target.value }))}
                  placeholder="http://localhost:8001/mcp"
                />
              </div>
            ) : (
              <>
                <div className="space-y-1.5">
                  <Label>Command</Label>
                  <Input
                    value={form.command}
                    onChange={e => setForm(p => ({ ...p, command: e.target.value }))}
                    placeholder="python"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label>Args <span className="text-muted-foreground">(one per line)</span></Label>
                  <Textarea
                    value={form.args}
                    onChange={e => setForm(p => ({ ...p, args: e.target.value }))}
                    placeholder={"/path/to/server.py\n--port\n8001"}
                    rows={3}
                    className="font-mono text-xs"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label>Env vars <span className="text-muted-foreground">(JSON object, optional)</span></Label>
                  <Textarea
                    value={form.env_vars}
                    onChange={e => setForm(p => ({ ...p, env_vars: e.target.value }))}
                    placeholder={'{"MY_API_KEY": "..."}'}
                    rows={2}
                    className="font-mono text-xs"
                  />
                </div>
              </>
            )}

            {isNetwork && (
              <>
                <div className="space-y-1.5">
                  <Label>Authentication</Label>
                  <Select
                    value={form.auth_type}
                    onValueChange={v => setForm(p => ({ ...p, auth_type: v as AuthType }))}
                  >
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="none">None / static headers</SelectItem>
                      <SelectItem value="oauth2">OAuth 2.0 (browser sign-in)</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                {form.auth_type === "oauth2" && (
                  <div className="space-y-1.5">
                    <Label>OAuth scope <span className="text-muted-foreground">(optional)</span></Label>
                    <Input
                      value={form.oauth_scope}
                      onChange={e => setForm(p => ({ ...p, oauth_scope: e.target.value }))}
                      placeholder="space-separated scopes"
                      className="font-mono text-xs"
                    />
                    <p className="text-xs text-muted-foreground">
                      Save the server, then click <span className="font-medium">Connect</span> to sign in.
                      Endpoints are auto-discovered (RFC 9728 / 8414) and a client is registered
                      dynamically when supported.
                    </p>
                  </div>
                )}

                {form.auth_type === "none" && (
                  <div className="space-y-1.5">
                    <Label>Headers <span className="text-muted-foreground">(JSON object, optional)</span></Label>
                    <Textarea
                      value={form.headers}
                      onChange={e => setForm(p => ({ ...p, headers: e.target.value }))}
                      placeholder={'{"Authorization": "Bearer ..."}'}
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
              <span className="text-sm">Enabled (inject into all script runs)</span>
            </label>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>Cancel</Button>
            <Button onClick={save} disabled={saving}>{saving ? "Saving…" : "Save"}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Probe result dialog */}
      <Dialog open={!!probeResult} onOpenChange={o => { if (!o) setProbeResult(null); }}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>{probeResult?.srv.name} — connection test</DialogTitle>
          </DialogHeader>
          {probeResult && (probeResult.result.ok ? (
            <div className="space-y-2 max-h-[60vh] overflow-y-auto pr-1">
              <p className="text-xs text-muted-foreground">
                Connected · {probeResult.result.tools.length} tool(s)
              </p>
              {probeResult.result.tools.length === 0 && (
                <p className="text-sm text-muted-foreground">This server exposes no tools.</p>
              )}
              {probeResult.result.tools.map(t => (
                <details key={t.name} className="rounded-md border border-border p-2.5">
                  <summary className="cursor-pointer text-sm font-mono text-primary">
                    {t.name}
                    {t.title && <span className="text-muted-foreground font-sans ml-2">{t.title}</span>}
                  </summary>
                  {t.description && (
                    <p className="text-xs text-muted-foreground mt-1.5 whitespace-pre-wrap">{t.description}</p>
                  )}
                  <pre className="mt-2 text-[11px] font-mono bg-muted/50 rounded p-2 overflow-x-auto">
                    {JSON.stringify(t.input_schema, null, 2)}
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
                  <Plug className="h-4 w-4" /> Connect
                </Button>
              )}
              {probeResult.result.needs_auth && probeResult.srv.auth_type !== "oauth2" && (
                <p className="text-xs text-muted-foreground">
                  This server requires authentication. Edit it and set Authentication to
                  {" "}<span className="font-medium">OAuth 2.0</span>, or add an{" "}
                  <code className="font-mono bg-muted px-1 rounded">Authorization</code> header.
                </p>
              )}
            </div>
          ))}
          <DialogFooter>
            <Button variant="outline" onClick={() => setProbeResult(null)}>Close</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Create skill dialog */}
      <Dialog open={skillDialogOpen} onOpenChange={setSkillDialogOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>New skill</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-1.5">
              <Label>Name</Label>
              <Input
                value={skillForm.name}
                onChange={e => setSkillForm(p => ({ ...p, name: e.target.value }))}
                placeholder="pdf-processing"
                onKeyDown={e => { if (e.key === "Enter") createSkill(); }}
              />
            </div>
            <div className="space-y-1.5">
              <Label>Description <span className="text-muted-foreground">(shown to the agent)</span></Label>
              <Textarea
                value={skillForm.description}
                onChange={e => setSkillForm(p => ({ ...p, description: e.target.value }))}
                placeholder="What this skill does and when to use it"
                rows={3}
              />
            </div>
            <p className="text-xs text-muted-foreground">
              A starter <code className="font-mono bg-muted px-1 rounded">SKILL.md</code> is created — edit it and add files next.
            </p>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setSkillDialogOpen(false)}>Cancel</Button>
            <Button onClick={createSkill} disabled={creatingSkill}>
              {creatingSkill ? "Creating…" : "Create & edit"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
