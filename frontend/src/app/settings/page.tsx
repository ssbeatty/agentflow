"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, Plus, Trash2, Star, StarOff } from "lucide-react";
import { toast } from "sonner";
import { llmConfigs } from "@/lib/api";
import type { LLMConfig } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import { Separator } from "@/components/ui/separator";

const PROVIDERS = ["openai", "anthropic", "deepseek", "ollama", "custom"] as const;

type ProviderKey = typeof PROVIDERS[number];

const DEFAULT_MODELS: Record<ProviderKey, string> = {
  openai: "gpt-4o",
  anthropic: "claude-opus-4-7-20251101",
  deepseek: "deepseek-chat",
  ollama: "llama3.2",
  custom: "",
};

interface FormState {
  name: string;
  provider: ProviderKey;
  model: string;
  api_key: string;
  base_url: string;
  is_default: boolean;
}

const EMPTY_FORM: FormState = {
  name: "", provider: "openai", model: "gpt-4o", api_key: "", base_url: "", is_default: false,
};

export default function SettingsPage() {
  const [configs, setConfigs] = useState<LLMConfig[]>([]);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    load();
  }, []);

  async function load() {
    try {
      setConfigs(await llmConfigs.list());
    } catch {
      toast.error("Failed to load LLM configs");
    }
  }

  function openCreate() {
    setEditId(null);
    setForm(EMPTY_FORM);
    setDialogOpen(true);
  }

  function openEdit(cfg: LLMConfig) {
    setEditId(cfg.id);
    setForm({
      name: cfg.name,
      provider: cfg.provider as ProviderKey,
      model: cfg.model,
      api_key: "",
      base_url: cfg.base_url || "",
      is_default: cfg.is_default,
    });
    setDialogOpen(true);
  }

  async function save() {
    if (!form.name || !form.model) return toast.error("Name and model are required");
    setSaving(true);
    try {
      const payload = {
        name: form.name,
        provider: form.provider,
        model: form.model,
        api_key: form.api_key || undefined,
        base_url: form.base_url || undefined,
        is_default: form.is_default,
        extra_config: {},
      };
      if (editId) {
        const updated = await llmConfigs.update(editId, payload);
        setConfigs((prev) => prev.map((c) => (c.id === editId ? updated : c)));
      } else {
        const created = await llmConfigs.create(payload);
        setConfigs((prev) => [...prev, created]);
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
    if (!confirm("Delete this LLM config?")) return;
    try {
      await llmConfigs.delete(id);
      setConfigs((prev) => prev.filter((c) => c.id !== id));
      toast.success("Deleted");
    } catch {
      toast.error("Failed to delete");
    }
  }

  async function setDefault(id: string) {
    try {
      const updated = await llmConfigs.setDefault(id);
      setConfigs((prev) =>
        prev.map((c) => ({ ...c, is_default: c.id === updated.id }))
      );
    } catch {
      toast.error("Failed");
    }
  }

  return (
    <div className="min-h-screen">
      <header className="border-b border-border px-6 py-3 flex items-center gap-3">
        <Link href="/">
          <Button variant="ghost" size="icon">
            <ArrowLeft className="h-4 w-4" />
          </Button>
        </Link>
        <h1 className="font-semibold">Settings</h1>
      </header>

      <main className="max-w-2xl mx-auto px-6 py-8">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h2 className="font-medium">LLM Configurations</h2>
            <p className="text-xs text-muted-foreground mt-0.5">
              Available via <code className="font-mono bg-muted px-1 rounded">get_llm(&quot;name&quot;)</code> in scripts
            </p>
          </div>
          <Button size="sm" onClick={openCreate}>
            <Plus className="h-4 w-4" />
            Add
          </Button>
        </div>

        <div className="space-y-3">
          {configs.length === 0 && (
            <p className="text-sm text-muted-foreground text-center py-8">No LLM configs yet</p>
          )}
          {configs.map((cfg) => (
            <div
              key={cfg.id}
              className="border border-border rounded-lg p-4 flex items-center justify-between gap-3"
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-sm">{cfg.name}</span>
                  {cfg.is_default && <Badge variant="success">default</Badge>}
                </div>
                <p className="text-xs text-muted-foreground mt-0.5">
                  {cfg.provider} · {cfg.model}
                  {cfg.base_url && ` · ${cfg.base_url}`}
                </p>
                {cfg.has_api_key && (
                  <p className="text-xs text-muted-foreground font-mono mt-0.5">
                    ••••••••••••••••
                  </p>
                )}
              </div>
              <div className="flex items-center gap-1 shrink-0">
                <Button variant="ghost" size="icon" onClick={() => setDefault(cfg.id)} title="Set default">
                  {cfg.is_default ? <Star className="h-4 w-4 text-amber-400" /> : <StarOff className="h-4 w-4" />}
                </Button>
                <Button variant="ghost" size="icon" onClick={() => openEdit(cfg)}>
                  <span className="text-xs">Edit</span>
                </Button>
                <Button variant="ghost" size="icon" onClick={() => remove(cfg.id)}>
                  <Trash2 className="h-4 w-4 text-destructive" />
                </Button>
              </div>
            </div>
          ))}
        </div>
      </main>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editId ? "Edit LLM Config" : "Add LLM Config"}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-1.5">
              <Label>Name (used in get_llm)</Label>
              <Input
                value={form.name}
                onChange={(e) => setForm((p) => ({ ...p, name: e.target.value }))}
                placeholder="default"
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label>Provider</Label>
                <Select
                  value={form.provider}
                  onValueChange={(v) =>
                    setForm((p) => ({
                      ...p,
                      provider: v as ProviderKey,
                      model: DEFAULT_MODELS[v as ProviderKey],
                    }))
                  }
                >
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {PROVIDERS.map((p) => <SelectItem key={p} value={p}>{p}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label>Model</Label>
                <Input
                  value={form.model}
                  onChange={(e) => setForm((p) => ({ ...p, model: e.target.value }))}
                  placeholder="gpt-4o"
                />
              </div>
            </div>
            <div className="space-y-1.5">
              <Label>
                API Key
                {editId && (
                  <span className="text-muted-foreground"> (leave blank to keep existing)</span>
                )}
              </Label>
              <Input
                type="password"
                value={form.api_key}
                onChange={(e) => setForm((p) => ({ ...p, api_key: e.target.value }))}
                placeholder={editId ? "••••••••" : "sk-..."}
              />
            </div>
            <div className="space-y-1.5">
              <Label>Base URL <span className="text-muted-foreground">(optional)</span></Label>
              <Input
                value={form.base_url}
                onChange={(e) => setForm((p) => ({ ...p, base_url: e.target.value }))}
                placeholder="https://api.openai.com/v1"
              />
            </div>
            <Separator />
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={form.is_default}
                onChange={(e) => setForm((p) => ({ ...p, is_default: e.target.checked }))}
                className="rounded"
              />
              <span className="text-sm">Set as default</span>
            </label>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>Cancel</Button>
            <Button onClick={save} disabled={saving}>
              {saving ? "Saving…" : "Save"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
