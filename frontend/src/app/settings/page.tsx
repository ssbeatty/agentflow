"use client";
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useTranslation } from "react-i18next";
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
import LanguageSwitcher from "@/components/LanguageSwitcher";

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
  const { t } = useTranslation("settings");
  const confirm = useConfirm();
  const [list, setList] = useState<Channel[]>([]);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm());
  const [saving, setSaving] = useState(false);

  useEffect(() => { load(); }, []);

  async function load() {
    try { setList(await channelsApi.list()); }
    catch { toast.error(t("toast.loadFailed")); }
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
          fetchError: models.length ? null : t("dialog.noModelsReturned"),
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
    if (!form.name.trim()) return toast.error(t("toast.nameRequired"));
    if (form.models.length === 0) return toast.error(t("toast.modelsRequired"));
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
      toast.success(editId ? t("toast.updated") : t("toast.created"));
    } catch (e: unknown) {
      toast.error(String(e));
    } finally {
      setSaving(false);
    }
  }

  async function remove(id: string) {
    if (!(await confirm(t("confirm.deleteMessage"), { confirmLabel: t("confirm.deleteLabel"), destructive: true }))) return;
    try {
      await channelsApi.delete(id);
      setList(prev => prev.filter(c => c.id !== id));
      toast.success(t("toast.deleted"));
    } catch { toast.error(t("toast.deleteFailed")); }
  }

  async function toggleEnabled(ch: Channel) {
    try {
      const u = await channelsApi.update(ch.id, { enabled: !ch.enabled });
      setList(prev => prev.map(c => c.id === ch.id ? u : c));
    } catch { toast.error(t("toast.updateFailed")); }
  }

  async function setDefault(ch: Channel, model: string) {
    try {
      const u = await channelsApi.setDefault(ch.id, model);
      setList(prev => prev.map(c => ({
        ...c,
        is_default: c.id === u.id,
        default_model: c.id === u.id ? u.default_model : null,
      })));
      toast.success(t("toast.defaultModel", { model }));
    } catch { toast.error(t("toast.setDefaultFailed")); }
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
        <h1 className="font-semibold">{t("header.title")}</h1>
      </header>

      <main className="max-w-2xl mx-auto px-6 py-8">
        <div className="mb-6 border border-border rounded-lg px-4 py-3">
          <h2 className="font-medium mb-2">{t("general.title")}</h2>
          <div className="flex items-center justify-between gap-4">
            <Label className="text-sm">{t("general.language")}</Label>
            <LanguageSwitcher />
          </div>
        </div>

        <div className="flex items-start justify-between mb-6 gap-4">
          <div>
            <h2 className="font-medium">{t("channels.title")}</h2>
            <p className="text-xs text-muted-foreground mt-1 leading-relaxed">
              {t("channels.description.part1")}{" "}
              <code className="font-mono bg-muted px-1 rounded">get_llm(&quot;model-id&quot;)</code>
              {t("channels.description.part2")}{" "}
              <span className="font-medium">{t("channels.description.priorityWord")}</span>{" "}
              {t("channels.description.part3")}{" "}
              <Star className="inline h-3 w-3 text-amber-400 fill-amber-400 align-middle" />{" "}
              {t("channels.description.part4")}{" "}
              <code className="font-mono bg-muted px-1 rounded">get_llm()</code>{" "}
              {t("channels.description.part5")}
            </p>
          </div>
          <Button size="sm" onClick={openCreate} className="shrink-0">
            <Plus className="h-4 w-4" />
            {t("channels.addChannel")}
          </Button>
        </div>

        {list.length === 0 && (
          <p className="text-sm text-muted-foreground text-center py-12 border border-dashed border-border rounded-lg">
            {t("channels.emptyState.prefix")} <span className="font-medium">{t("channels.addChannel")}</span> {t("channels.emptyState.suffix")}
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
                    <Badge variant="outline" className="text-[10px]" title={t("channels.priorityTitle")}>P{ch.priority}</Badge>
                    {!ch.enabled && <Badge variant="outline" className="text-[10px]">{t("channels.disabled")}</Badge>}
                    {ch.has_api_key && <span className="text-[10px] text-muted-foreground">🔑</span>}
                  </div>
                  {ch.base_url && (
                    <p className="text-xs text-muted-foreground font-mono truncate mt-0.5">{ch.base_url}</p>
                  )}
                </div>
                <div className="flex items-center gap-0.5 shrink-0">
                  <Button variant="ghost" size="icon" onClick={() => toggleEnabled(ch)} title={ch.enabled ? t("channels.disableTitle") : t("channels.enableTitle")}>
                    <Power className={cn("h-4 w-4", ch.enabled ? "text-primary" : "text-muted-foreground")} />
                  </Button>
                  <Button variant="ghost" size="icon" onClick={() => openEdit(ch)} title={t("channels.editTitle")}>
                    <Pencil className="h-4 w-4" />
                  </Button>
                  <Button variant="ghost" size="icon" onClick={() => remove(ch.id)} title={t("channels.deleteTitle")}>
                    <Trash2 className="h-4 w-4 text-destructive" />
                  </Button>
                </div>
              </div>

              <div className="px-4 py-3">
                {ch.models.length === 0 ? (
                  <p className="text-xs text-muted-foreground">{t("channels.noModels")} <Pencil className="inline h-3 w-3" /> {t("channels.noModelsSuffix")}</p>
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
                            title={isDefault ? t("channels.defaultModelTitle") : t("channels.setDefaultTitle")}
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
            <DialogTitle>{editId ? t("dialog.editTitle") : t("dialog.addTitle")}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label>{t("dialog.nameLabel")}</Label>
                <Input
                  value={form.name}
                  onChange={e => setForm(p => ({ ...p, name: e.target.value }))}
                  placeholder={t("dialog.namePlaceholder")}
                />
              </div>
              <div className="space-y-1.5">
                <Label>{t("dialog.priorityLabel")} <span className="text-muted-foreground">{t("dialog.priorityHint")}</span></Label>
                <Input
                  type="number"
                  value={form.priority}
                  onChange={e => setForm(p => ({ ...p, priority: Number(e.target.value) }))}
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label>{t("dialog.providerLabel")}</Label>
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
                <Label>{t("dialog.baseUrlLabel")} <span className="text-muted-foreground">{t("dialog.optional")}</span></Label>
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
                {t("dialog.apiKeyLabel")}
                {editId && <span className="text-muted-foreground"> {t("dialog.apiKeyKeepHint")}</span>}
              </Label>
              <div className="flex gap-2">
                <Input
                  type="password"
                  value={form.api_key}
                  onChange={e => setForm(p => ({ ...p, api_key: e.target.value }))}
                  placeholder={editId ? t("dialog.apiKeyPlaceholderEdit") : t("dialog.apiKeyPlaceholderCreate")}
                />
                <Button variant="secondary" onClick={fetchModels} disabled={form.fetching} className="shrink-0">
                  {form.fetching ? <Loader2 className="h-4 w-4 animate-spin" /> : t("dialog.loadModels")}
                </Button>
              </div>
            </div>

            {form.fetchError && <p className="text-xs text-destructive break-words">{form.fetchError}</p>}

            {form.available.length > 0 && (
              <div className="space-y-1.5">
                <Label>{t("dialog.modelsLabel")} <span className="text-muted-foreground">{t("dialog.modelsSelected", { count: form.models.length })}</span></Label>
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
              <Label>{t("dialog.addModelLabel")} <span className="text-muted-foreground">{t("dialog.addModelHint")}</span></Label>
              <div className="flex gap-2">
                <Input
                  value={form.customModel}
                  onChange={e => setForm(p => ({ ...p, customModel: e.target.value }))}
                  onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); addCustom(); } }}
                  placeholder={t("dialog.addModelPlaceholder")}
                  className="font-mono text-xs"
                />
                <Button variant="outline" onClick={addCustom} className="shrink-0">{t("dialog.add")}</Button>
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
              <span className="text-sm">{t("dialog.enabledLabel")}</span>
            </label>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>{t("dialog.cancel")}</Button>
            <Button onClick={save} disabled={saving}>
              {saving ? t("dialog.saving") : <><Check className="h-4 w-4" />{t("dialog.save")}</>}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
