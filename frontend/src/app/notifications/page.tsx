"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useTranslation } from "react-i18next";
import {
  ArrowLeft, Bell, BellRing, Plus, Trash2, Loader2, Pencil, Send,
} from "lucide-react";
import { toast } from "sonner";
import { notificationChannels as api } from "@/lib/api";
import type { NotificationChannel, NotificationChannelType } from "@/lib/types";
import { formatDate } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { useConfirm } from "@/components/ConfirmDialogProvider";

type FieldSpec = {
  key: string;
  secret?: boolean;
  type?: "text" | "number" | "checkbox";
  placeholder?: string;
};

// Per-provider config fields (labels come from i18n `fields.<key>`).
const FIELDS: Record<NotificationChannelType, FieldSpec[]> = {
  pushplus: [
    { key: "token", secret: true },
    { key: "topic" },
  ],
  bark: [
    { key: "server_url", placeholder: "https://api.day.app" },
    { key: "device_key", secret: true },
    { key: "sound" },
  ],
  email: [
    { key: "smtp_host", placeholder: "smtp.gmail.com" },
    { key: "smtp_port", type: "number", placeholder: "587" },
    { key: "username" },
    { key: "password", secret: true },
    { key: "from_addr" },
    { key: "to_addrs" },
    { key: "use_tls", type: "checkbox" },
  ],
};

const TYPES: NotificationChannelType[] = ["bark", "pushplus", "email"];

export default function NotificationsPage() {
  const { t } = useTranslation("notifications");
  const confirm = useConfirm();
  const [items, setItems] = useState<NotificationChannel[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<NotificationChannel | null>(null);
  const [creating, setCreating] = useState(false);
  const [testingId, setTestingId] = useState<string | null>(null);

  useEffect(() => { load(); }, []);

  async function load() {
    try { setItems(await api.list()); }
    catch { /* 401 handled globally */ }
    finally { setLoading(false); }
  }

  async function toggle(c: NotificationChannel) {
    try {
      const updated = await api.update(c.id, { enabled: !c.enabled });
      setItems((prev) => prev.map((x) => (x.id === c.id ? updated : x)));
    } catch {
      toast.error(t("toast.toggleFailed"));
    }
  }

  async function test(c: NotificationChannel) {
    setTestingId(c.id);
    try {
      const r = await api.test(c.id);
      if (r.ok) toast.success(t("toast.testOk"));
      else toast.error(t("toast.testFailed", { error: r.error || "" }));
    } catch (err) {
      toast.error(t("toast.testFailed", { error: String(err instanceof Error ? err.message : err) }));
    } finally {
      setTestingId(null);
    }
  }

  async function remove(c: NotificationChannel) {
    if (!(await confirm(t("confirm.deleteMessage", { name: c.name }), { confirmLabel: t("confirm.deleteLabel"), destructive: true }))) return;
    try {
      await api.delete(c.id);
      setItems((prev) => prev.filter((x) => x.id !== c.id));
      toast.success(t("toast.deleted"));
    } catch {
      toast.error(t("toast.deleteFailed"));
    }
  }

  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-border px-6 py-3 flex items-center gap-3">
        <Link href="/">
          <Button variant="ghost" size="sm" className="gap-1.5">
            <ArrowLeft className="h-4 w-4" />
            {t("header.home")}
          </Button>
        </Link>
        <div className="flex items-center gap-2">
          <Bell className="h-4 w-4 text-primary" />
          <span className="font-semibold text-sm">{t("header.title")}</span>
        </div>
        <Button size="sm" className="ml-auto gap-1.5" onClick={() => setCreating(true)}>
          <Plus className="h-3.5 w-3.5" />
          {t("header.new")}
        </Button>
      </header>

      <main className="flex-1 px-6 py-8 max-w-3xl mx-auto w-full">
        <p className="text-xs text-muted-foreground mb-5">{t("intro")}</p>

        {loading ? (
          <div className="py-12 flex justify-center"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
        ) : items.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <BellRing className="h-10 w-10 text-muted-foreground/40 mb-3" />
            <p className="text-sm text-muted-foreground">{t("empty.text")}</p>
            <Button className="mt-4 gap-1.5" onClick={() => setCreating(true)}>
              <Plus className="h-4 w-4" />
              {t("empty.cta")}
            </Button>
          </div>
        ) : (
          <div className="divide-y divide-border/60 rounded-lg border border-border/60 overflow-hidden">
            {items.map((c) => (
              <div key={c.id} className="flex items-center gap-3 px-4 py-3 text-sm">
                <button
                  onClick={() => toggle(c)}
                  title={c.enabled ? t("list.enabled") : t("list.disabled")}
                  className={`shrink-0 h-4 w-4 rounded-full border transition-colors ${
                    c.enabled ? "bg-primary border-primary" : "bg-transparent border-muted-foreground/40"
                  }`}
                />
                <div className="min-w-0 flex-1">
                  <div className="font-medium truncate flex items-center gap-2">
                    {c.name}
                    <span className="text-[10px] font-mono uppercase px-1.5 py-0.5 rounded bg-muted text-muted-foreground">
                      {t(`types.${c.type}`)}
                    </span>
                  </div>
                  <div className="text-[11px] text-muted-foreground mt-0.5 flex items-center gap-2 flex-wrap">
                    <span>{c.has_secret ? t("list.secretSet") : t("list.noSecret")}</span>
                    <span>· {t("list.created", { date: formatDate(c.created_at) })}</span>
                  </div>
                </div>
                <Button
                  variant="ghost" size="icon"
                  className="h-7 w-7 text-muted-foreground hover:text-foreground shrink-0"
                  onClick={() => test(c)} disabled={testingId === c.id}
                  title={t("list.test")}
                >
                  {testingId === c.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
                </Button>
                <Button
                  variant="ghost" size="icon"
                  className="h-7 w-7 text-muted-foreground hover:text-foreground shrink-0"
                  onClick={() => setEditing(c)} title={t("list.edit")}
                >
                  <Pencil className="h-3.5 w-3.5" />
                </Button>
                <Button
                  variant="ghost" size="icon"
                  className="h-7 w-7 text-muted-foreground hover:text-destructive shrink-0"
                  onClick={() => remove(c)} title={t("list.delete")}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </div>
            ))}
          </div>
        )}
      </main>

      <ChannelDialog
        open={creating || !!editing}
        channel={editing}
        onOpenChange={(o) => { if (!o) { setCreating(false); setEditing(null); } }}
        onSaved={(c) => {
          setItems((prev) => {
            const i = prev.findIndex((x) => x.id === c.id);
            return i >= 0 ? prev.map((x) => (x.id === c.id ? c : x)) : [...prev, c];
          });
          setCreating(false); setEditing(null);
        }}
      />
    </div>
  );
}

// ── Create / Edit ─────────────────────────────────────────────────────────────

function ChannelDialog({
  open, channel, onOpenChange, onSaved,
}: {
  open: boolean;
  channel: NotificationChannel | null;
  onOpenChange: (o: boolean) => void;
  onSaved: (c: NotificationChannel) => void;
}) {
  const { t } = useTranslation("notifications");
  const isEdit = !!channel;
  const [name, setName] = useState("");
  const [type, setType] = useState<NotificationChannelType>("bark");
  const [values, setValues] = useState<Record<string, string | boolean>>({});
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    if (channel) {
      setName(channel.name);
      setType(channel.type);
      // Non-secret fields prefill from config_safe; secrets stay blank.
      const init: Record<string, string | boolean> = {};
      for (const [k, v] of Object.entries(channel.config_safe || {})) {
        init[k] = typeof v === "boolean" ? v : String(v ?? "");
      }
      if (init.use_tls === undefined) init.use_tls = true;
      setValues(init);
    } else {
      setName("");
      setType("bark");
      setValues({ use_tls: true });
    }
  }, [open, channel]);

  const fields = FIELDS[type];
  const canSave = name.trim().length > 0 && !busy;

  function buildConfig(): Record<string, unknown> {
    const config: Record<string, unknown> = {};
    for (const f of fields) {
      const v = values[f.key];
      if (f.type === "checkbox") { config[f.key] = !!v; continue; }
      if (f.secret) { if (v) config[f.key] = v; continue; }  // blank secret → omit (keep existing on edit)
      if (v !== undefined && String(v) !== "") config[f.key] = v;
    }
    return config;
  }

  async function save() {
    if (!canSave) return;
    setBusy(true);
    try {
      const config = buildConfig();
      const saved = channel
        ? await api.update(channel.id, { name: name.trim(), config })
        : await api.create({ name: name.trim(), type, config });
      onSaved(saved);
      toast.success(channel ? t("toast.updated") : t("toast.created"));
    } catch (err) {
      toast.error(String(err instanceof Error ? err.message : err) || t("toast.saveFailed"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{isEdit ? t("dialog.editTitle") : t("dialog.createTitle")}</DialogTitle>
          {isEdit && <DialogDescription>{t("dialog.secretKeep")}</DialogDescription>}
        </DialogHeader>
        <div className="space-y-3 py-2">
          <div className="space-y-1.5">
            <Label htmlFor="nc-name" className="text-xs">{t("dialog.nameLabel")}</Label>
            <Input
              id="nc-name" value={name} autoFocus
              onChange={(e) => setName(e.target.value)}
              placeholder={t("dialog.namePlaceholder")}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="nc-type" className="text-xs">{t("dialog.typeLabel")}</Label>
            <Select
              value={type} disabled={isEdit}
              onValueChange={(v) => setType(v as NotificationChannelType)}
            >
              <SelectTrigger id="nc-type" className="h-9">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {TYPES.map((ty) => (
                  <SelectItem key={ty} value={ty}>{t(`types.${ty}`)}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {fields.map((f) => (
            f.type === "checkbox" ? (
              <label key={f.key} className="flex items-center gap-2 text-xs cursor-pointer select-none pt-1">
                <input
                  type="checkbox"
                  checked={!!values[f.key]}
                  onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.checked }))}
                  className="h-3.5 w-3.5"
                />
                {t(`fields.${f.key}`)}
              </label>
            ) : (
              <div key={f.key} className="space-y-1.5">
                <Label htmlFor={`nc-${f.key}`} className="text-xs">{t(`fields.${f.key}`)}</Label>
                <Input
                  id={`nc-${f.key}`}
                  type={f.secret ? "password" : f.type === "number" ? "number" : "text"}
                  value={String(values[f.key] ?? "")}
                  onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
                  placeholder={f.secret && isEdit ? "••••••" : (f.placeholder || "")}
                  className={f.secret ? "font-mono" : ""}
                />
              </div>
            )
          ))}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>{t("actions.cancel")}</Button>
          <Button onClick={save} disabled={!canSave} className="gap-1.5">
            {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
            {t("actions.save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
