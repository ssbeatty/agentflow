"use client";
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  ArrowLeft, Plus, Trash2, Star, Loader2, Cpu, Pencil, Power, Check,
} from "lucide-react";
import { toast } from "sonner";
import { channels as channelsApi } from "@/lib/api";
import type { Channel } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Separator } from "@/components/ui/separator";
import { useConfirm } from "@/components/ConfirmDialogProvider";

const PROVIDERS = ["openai", "anthropic", "deepseek", "ollama", "custom"] as const;
type ProviderKey = typeof PROVIDERS[number];

const BASE_PLACEHOLDER: Record<ProviderKey, string> = {
  openai: "https://api.openai.com/v1",
  anthropic: "https://api.anthropic.com/v1",
  deepseek: "https://api.deepseek.com",
  ollama: "http://localhost:11434",
  custom: "https://your-endpoint/v1",
};

interface FormState {
  name: string;
  provider: ProviderKey;
  base_url: string;
  api_key: string;
  priority: number;
  enabled: boolean;
  models: string[];       // selected models (the channel's model list)
  available: string[];    // fetched + manually-added model ids to choose from
  customModel: string;
  fetching: boolean;
  fetchError: string | null;
}

const emptyForm = (provider: ProviderKey = "openai"): FormState => ({
  name: "", provider, base_url: "", api_key: "", priority: 0, enabled: true,
  models: [], available: [], customModel: "", fetching: false, fetchError: null,
});

export default function SettingsPage() {
  const confirm = useConfirm();
  const [list, setList] = useState<Channel[]>([]);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm());
  const [saving, setSaving] = useState(false);

  useEffect(() => { load(); }, []);

  async function load() {
    try { setList(await channelsApi.list()); }
    catch { toast.error("Failed to load channels"); }
  }

  function openCreate() {
    setEditId(null);
    setForm(emptyForm());
    setDialogOpen(true);
  }

  function openEdit(ch: Channel) {
    setEditId(ch.id);
    setForm({
      name: ch.name,
      provider: ch.provider as ProviderKey,
      base_url: ch.base_url ?? "",
      api_key: "",
      priority: ch.priority,
      enabled: ch.enabled,
      models: ch.models,
      available: ch.models,   // show current models even before re-fetching
      customModel: "",
      fetching: false,
      fetchError: null,
    });
    setDialogOpen(true);
  }

  async function fetchModels() {
    setForm(p => ({ ...p, fetching: true, fetchError: null }));
    try {
      const { models, error } = await channelsApi.listModels({
        provider: form.provider,
        api_key: form.api_key || undefined,
        base_url: form.base_url || undefined,
      });
      if (error) {
        setForm(p => ({ ...p, fetching: false, fetchError: error }));
      } else {
        setForm(p => ({
          ...p,
          fetching: false,
          available: Array.from(new Set([...p.models, ...models])),
          fetchError: models.length ? null : "No models returned",
        }));
      }
    } catch (e: unknown) {
      setForm(p => ({ ...p, fetching: false, fetchError: String(e) }));
    }
  }

  function toggleModel(m: string) {
    setForm(p => {
      const s = new Set(p.models);
      s.has(m) ? s.delete(m) : s.add(m);
      return { ...p, models: [...s] };
    });
  }

  function addCustom() {
    const m = form.customModel.trim();
    if (!m) return;
    setForm(p => ({
      ...p,
      available: p.available.includes(m) ? p.available : [m, ...p.available],
      models: p.models.includes(m) ? p.models : [...p.models, m],
      customModel: "",
    }));
  }

  async function save() {
    if (!form.name.trim()) return toast.error("Channel name is required");
    if (form.models.length === 0) return toast.error("Select at least one model");
    setSaving(true);
    try {
      const payload = {
        name: form.name.trim(),
        provider: form.provider,
        api_key: form.api_key || undefined,
        base_url: form.base_url || undefined,
        models: form.models,
        priority: Number.isFinite(form.priority) ? form.priority : 0,
        enabled: form.enabled,
      };
      if (editId) {
        const u = await channelsApi.update(editId, payload);
        setList(prev => prev.map(c => c.id === editId ? u : c));
      } else {
        const c = await channelsApi.create(payload);
        setList(prev => [...prev, c]);
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
    if (!(await confirm("Delete this channel?", { confirmLabel: "Delete", destructive: true }))) return;
    try {
      await channelsApi.delete(id);
      setList(prev => prev.filter(c => c.id !== id));
      toast.success("Deleted");
    } catch { toast.error("Failed to delete"); }
  }

  async function toggleEnabled(ch: Channel) {
    try {
      const u = await channelsApi.update(ch.id, { enabled: !ch.enabled });
      setList(prev => prev.map(c => c.id === ch.id ? u : c));
    } catch { toast.error("Failed to update"); }
  }

  async function setDefault(ch: Channel, model: string) {
    try {
      const u = await channelsApi.setDefault(ch.id, model);
      setList(prev => prev.map(c => ({
        ...c,
        is_default: c.id === u.id,
        default_model: c.id === u.id ? u.default_model : null,
      })));
      toast.success(`Default model: ${model}`);
    } catch { toast.error("Failed to set default"); }
  }

  const sorted = useMemo(
    () => [...list].sort((a, b) => b.priority - a.priority || a.name.localeCompare(b.name)),
    [list],
  );

  return (
    <div className="min-h-screen">
      <header className="border-b border-border px-6 py-3 flex items-center gap-3">
        <Link href="/">
          <Button variant="ghost" size="icon"><ArrowLeft className="h-4 w-4" /></Button>
        </Link>
        <h1 className="font-semibold">Settings</h1>
      </header>

      <main className="max-w-2xl mx-auto px-6 py-8">
        <div className="flex items-start justify-between mb-6 gap-4">
          <div>
            <h2 className="font-medium">LLM Channels</h2>
            <p className="text-xs text-muted-foreground mt-1 leading-relaxed">
              A channel is one provider endpoint (key + base URL) serving a set of models.
              Call a model from a script with{" "}
              <code className="font-mono bg-muted px-1 rounded">get_llm(&quot;model-id&quot;)</code>.
              If the same model lives in several channels, the highest{" "}
              <span className="font-medium">priority</span> wins (ties → first).
              The <Star className="inline h-3 w-3 text-amber-400 fill-amber-400 align-middle" /> model
              is what <code className="font-mono bg-muted px-1 rounded">get_llm()</code> returns by default.
            </p>
          </div>
          <Button size="sm" onClick={openCreate} className="shrink-0">
            <Plus className="h-4 w-4" />
            Add channel
          </Button>
        </div>

        {list.length === 0 && (
          <p className="text-sm text-muted-foreground text-center py-12 border border-dashed border-border rounded-lg">
            No channels yet. Click <span className="font-medium">Add channel</span> to connect a provider and pick its models.
          </p>
        )}

        <div className="space-y-3">
          {sorted.map(ch => (
            <div
              key={ch.id}
              className={cn(
                "border rounded-lg overflow-hidden transition-opacity",
                ch.enabled ? "border-border" : "border-border/50 opacity-60",
              )}
            >
              <div className="flex items-center gap-3 px-4 py-2.5 bg-secondary/20">
                <Cpu className="h-4 w-4 text-muted-foreground shrink-0" />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-medium text-sm truncate">{ch.name}</span>
                    <Badge variant="secondary" className="text-[10px] capitalize">{ch.provider}</Badge>
                    <Badge variant="outline" className="text-[10px]" title="Priority — higher wins">P{ch.priority}</Badge>
                    {!ch.enabled && <Badge variant="outline" className="text-[10px]">disabled</Badge>}
                    {ch.has_api_key && <span className="text-[10px] text-muted-foreground">🔑</span>}
                  </div>
                  {ch.base_url && (
                    <p className="text-xs text-muted-foreground font-mono truncate mt-0.5">{ch.base_url}</p>
                  )}
                </div>
                <div className="flex items-center gap-0.5 shrink-0">
                  <Button variant="ghost" size="icon" onClick={() => toggleEnabled(ch)} title={ch.enabled ? "Disable" : "Enable"}>
                    <Power className={cn("h-4 w-4", ch.enabled ? "text-primary" : "text-muted-foreground")} />
                  </Button>
                  <Button variant="ghost" size="icon" onClick={() => openEdit(ch)} title="Edit">
                    <Pencil className="h-4 w-4" />
                  </Button>
                  <Button variant="ghost" size="icon" onClick={() => remove(ch.id)} title="Delete">
                    <Trash2 className="h-4 w-4 text-destructive" />
                  </Button>
                </div>
              </div>

              <div className="px-4 py-3">
                {ch.models.length === 0 ? (
                  <p className="text-xs text-muted-foreground">No models — click <Pencil className="inline h-3 w-3" /> to add some.</p>
                ) : (
                  <div className="flex flex-wrap gap-1.5">
                    {ch.models.map(m => {
                      const isDefault = ch.is_default && ch.default_model === m;
                      return (
                        <span
                          key={m}
                          className={cn(
                            "group inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs font-mono",
                            isDefault ? "border-amber-400/50 bg-amber-400/10" : "border-border bg-background",
                          )}
                        >
                          {m}
                          <button
                            onClick={() => setDefault(ch, m)}
                            title={isDefault ? "Default model for get_llm()" : "Set as default"}
                            className="shrink-0"
                          >
                            <Star className={cn(
                              "h-3 w-3 transition-colors",
                              isDefault ? "text-amber-400 fill-amber-400" : "text-muted-foreground/40 hover:text-amber-400",
                            )} />
                          </button>
                        </span>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      </main>

      {/* Add / Edit channel dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>{editId ? "Edit channel" : "Add channel"}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label>Name</Label>
                <Input
                  value={form.name}
                  onChange={e => setForm(p => ({ ...p, name: e.target.value }))}
                  placeholder="e.g. OpenAI main"
                />
              </div>
              <div className="space-y-1.5">
                <Label>Priority <span className="text-muted-foreground">(higher wins)</span></Label>
                <Input
                  type="number"
                  value={form.priority}
                  onChange={e => setForm(p => ({ ...p, priority: Number(e.target.value) }))}
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label>Provider</Label>
                <Select
                  value={form.provider}
                  onValueChange={v => setForm(p => ({ ...p, provider: v as ProviderKey }))}
                >
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {PROVIDERS.map(p => <SelectItem key={p} value={p} className="capitalize">{p}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label>Base URL <span className="text-muted-foreground">(optional)</span></Label>
                <Input
                  value={form.base_url}
                  onChange={e => setForm(p => ({ ...p, base_url: e.target.value }))}
                  placeholder={BASE_PLACEHOLDER[form.provider]}
                  className="font-mono text-xs"
                />
              </div>
            </div>

            <div className="space-y-1.5">
              <Label>
                API Key
                {editId && <span className="text-muted-foreground"> (blank = keep existing)</span>}
              </Label>
              <div className="flex gap-2">
                <Input
                  type="password"
                  value={form.api_key}
                  onChange={e => setForm(p => ({ ...p, api_key: e.target.value }))}
                  placeholder={editId ? "••••••••" : "sk-..."}
                />
                <Button variant="secondary" onClick={fetchModels} disabled={form.fetching} className="shrink-0">
                  {form.fetching ? <Loader2 className="h-4 w-4 animate-spin" /> : "Load models"}
                </Button>
              </div>
            </div>

            {form.fetchError && <p className="text-xs text-destructive break-words">{form.fetchError}</p>}

            {form.available.length > 0 && (
              <div className="space-y-1.5">
                <Label>Models <span className="text-muted-foreground">({form.models.length} selected)</span></Label>
                <div className="max-h-52 overflow-y-auto rounded-md border border-border divide-y divide-border/50">
                  {form.available.map(m => (
                    <label key={m} className="flex items-center gap-2 px-3 py-1.5 cursor-pointer hover:bg-muted/40">
                      <input type="checkbox" checked={form.models.includes(m)} onChange={() => toggleModel(m)} className="rounded" />
                      <span className="font-mono text-xs">{m}</span>
                    </label>
                  ))}
                </div>
              </div>
            )}

            <div className="space-y-1.5">
              <Label>Add a model manually <span className="text-muted-foreground">(if not listed)</span></Label>
              <div className="flex gap-2">
                <Input
                  value={form.customModel}
                  onChange={e => setForm(p => ({ ...p, customModel: e.target.value }))}
                  onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); addCustom(); } }}
                  placeholder="gpt-4o"
                  className="font-mono text-xs"
                />
                <Button variant="outline" onClick={addCustom} className="shrink-0">Add</Button>
              </div>
            </div>

            <Separator />
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={form.enabled}
                onChange={e => setForm(p => ({ ...p, enabled: e.target.checked }))}
                className="rounded"
              />
              <span className="text-sm">Enabled (models available to scripts)</span>
            </label>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>Cancel</Button>
            <Button onClick={save} disabled={saving}>
              {saving ? "Saving…" : <><Check className="h-4 w-4" />Save</>}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
