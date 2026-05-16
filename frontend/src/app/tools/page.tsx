"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, Plus, Trash2, ToggleLeft, ToggleRight, Globe, Terminal, Radio } from "lucide-react";
import { toast } from "sonner";
import { mcpServers } from "@/lib/api";
import type { MCPServerConfig } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";

type Transport = MCPServerConfig["transport"];

interface FormState {
  name: string;
  transport: Transport;
  url: string;
  command: string;
  args: string;       // newline-separated list
  env_vars: string;   // JSON string
  headers: string;    // JSON string
  enabled: boolean;
}

const EMPTY_FORM: FormState = {
  name: "", transport: "http", url: "", command: "", args: "", env_vars: "", headers: "", enabled: true,
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
  const [servers, setServers] = useState<MCPServerConfig[]>([]);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);

  useEffect(() => { load(); }, []);

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

    const payload: Omit<MCPServerConfig, "id" | "created_at" | "updated_at"> = {
      name: form.name.trim(),
      transport: form.transport,
      url: form.url.trim() || undefined,
      command: form.command.trim() || undefined,
      args: form.args.trim() ? form.args.split("\n").map(s => s.trim()).filter(Boolean) : undefined,
      env_vars: env_vars,
      headers: headers,
      enabled: form.enabled,
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

  const isNetwork = form.transport !== "stdio";

  return (
    <div className="min-h-screen">
      <header className="border-b border-border px-6 py-3 flex items-center gap-3">
        <Link href="/settings">
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
                <div className="flex items-center gap-2">
                  <span className="font-medium text-sm">{srv.name}</span>
                  <Badge variant={srv.enabled ? "default" : "secondary"} className="gap-1">
                    {TRANSPORT_ICONS[srv.transport]}
                    {srv.transport}
                  </Badge>
                  {!srv.enabled && <Badge variant="outline">disabled</Badge>}
                </div>
                <p className="text-xs text-muted-foreground mt-0.5 font-mono truncate">
                  {srv.url || srv.command || "—"}
                </p>
              </div>
              <div className="flex items-center gap-1 shrink-0">
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
      </main>

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
    </div>
  );
}
