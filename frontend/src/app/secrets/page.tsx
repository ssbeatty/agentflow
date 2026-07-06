"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useTranslation } from "react-i18next";
import {
  ArrowLeft, KeyRound, Lock, Plus, Trash2, Loader2, Pencil,
} from "lucide-react";
import { toast } from "sonner";
import { secrets as secretsApi } from "@/lib/api";
import type { Secret } from "@/lib/types";
import { formatDate } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription,
} from "@/components/ui/dialog";
import { useConfirm } from "@/components/ConfirmDialogProvider";

export default function SecretsPage() {
  const { t } = useTranslation("secrets");
  const confirm = useConfirm();
  const [items, setItems] = useState<Secret[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<Secret | null>(null);
  const [creating, setCreating] = useState(false);

  useEffect(() => { load(); }, []);

  async function load() {
    try { setItems(await secretsApi.list()); }
    catch { /* 401 handled globally */ }
    finally { setLoading(false); }
  }

  async function remove(s: Secret) {
    if (!(await confirm(t("confirm.deleteMessage", { key: s.key }), { confirmLabel: t("confirm.deleteLabel"), destructive: true }))) return;
    try {
      await secretsApi.delete(s.id);
      setItems((prev) => prev.filter((x) => x.id !== s.id));
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
          <Lock className="h-4 w-4 text-primary" />
          <span className="font-semibold text-sm">{t("header.title")}</span>
        </div>
        <Button size="sm" className="ml-auto gap-1.5" onClick={() => setCreating(true)}>
          <Plus className="h-3.5 w-3.5" />
          {t("header.newSecret")}
        </Button>
      </header>

      <main className="flex-1 px-6 py-8 max-w-3xl mx-auto w-full">
        <p className="text-xs text-muted-foreground mb-5">
          {t("intro.line1")} <b>{t("intro.bold")}</b>. {t("intro.line2")}{" "}
          <code className="bg-muted px-1 py-0.5 rounded font-mono">get_secret(&quot;BARK_KEY&quot;)</code>{" "}
          {t("intro.line3")}
        </p>

        {loading ? (
          <div className="py-12 flex justify-center"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
        ) : items.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <KeyRound className="h-10 w-10 text-muted-foreground/40 mb-3" />
            <p className="text-sm text-muted-foreground">{t("empty.text")}</p>
            <Button className="mt-4 gap-1.5" onClick={() => setCreating(true)}>
              <Plus className="h-4 w-4" />
              {t("empty.cta")}
            </Button>
          </div>
        ) : (
          <div className="divide-y divide-border/60 rounded-lg border border-border/60 overflow-hidden">
            {items.map((s) => (
              <div key={s.id} className="flex items-center gap-3 px-4 py-3 text-sm">
                <div className="min-w-0 flex-1">
                  <div className="font-mono font-medium truncate">{s.key}</div>
                  <div className="text-[11px] text-muted-foreground mt-0.5 flex items-center gap-2 flex-wrap">
                    <span className="font-mono">{s.preview || t("list.empty")}</span>
                    {s.description && <span className="truncate">· {s.description}</span>}
                    <span>{t("list.updated", { date: formatDate(s.updated_at) })}</span>
                  </div>
                </div>
                <Button
                  variant="ghost" size="icon"
                  className="h-7 w-7 text-muted-foreground hover:text-foreground shrink-0"
                  onClick={() => setEditing(s)}
                  title={t("list.edit")}
                >
                  <Pencil className="h-3.5 w-3.5" />
                </Button>
                <Button
                  variant="ghost" size="icon"
                  className="h-7 w-7 text-muted-foreground hover:text-destructive shrink-0"
                  onClick={() => remove(s)}
                  title={t("list.delete")}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </div>
            ))}
          </div>
        )}
      </main>

      <CreateDialog
        open={creating}
        existing={items}
        onOpenChange={setCreating}
        onCreated={(s) => { setItems((prev) => [...prev, s].sort((a, b) => a.key.localeCompare(b.key))); setCreating(false); }}
      />
      <EditDialog
        secret={editing}
        onOpenChange={(o) => { if (!o) setEditing(null); }}
        onSaved={(s) => { setItems((prev) => prev.map((x) => (x.id === s.id ? s : x))); setEditing(null); }}
      />
    </div>
  );
}

// ── Create ──────────────────────────────────────────────────────────────────

function CreateDialog({
  open, existing, onOpenChange, onCreated,
}: {
  open: boolean;
  existing: Secret[];
  onOpenChange: (o: boolean) => void;
  onCreated: (s: Secret) => void;
}) {
  const { t } = useTranslation("secrets");
  const [key, setKey] = useState("");
  const [value, setValue] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) { setKey(""); setValue(""); setDescription(""); }
  }, [open]);

  const keyValid = /^[A-Za-z_][A-Za-z0-9_]*$/.test(key);
  const collides = existing.some((s) => s.key.toUpperCase() === key.toUpperCase());
  const canSave = keyValid && !collides && value.length > 0 && !busy;

  async function save() {
    if (!canSave) return;
    setBusy(true);
    try {
      const s = await secretsApi.create({ key, value, description });
      onCreated(s);
    } catch (err) {
      toast.error(String(err instanceof Error ? err.message : err) || t("toast.createFailed"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("createDialog.title")}</DialogTitle>
          <DialogDescription>{t("createDialog.description")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-3 py-2">
          <div className="space-y-1.5">
            <Label htmlFor="sk-key" className="text-xs">{t("createDialog.keyLabel")}</Label>
            <Input
              id="sk-key" value={key} autoFocus
              onChange={(e) => setKey(e.target.value)}
              placeholder={t("createDialog.keyPlaceholder")}
              className="font-mono"
            />
            {key.length > 0 && !keyValid && (
              <p className="text-[11px] text-destructive">{t("createDialog.keyInvalid")}</p>
            )}
            {keyValid && collides && (
              <p className="text-[11px] text-destructive">{t("createDialog.keyCollides")}</p>
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="sk-val" className="text-xs">{t("createDialog.valueLabel")}</Label>
            <Input
              id="sk-val" value={value} type="password"
              onChange={(e) => setValue(e.target.value)}
              placeholder={t("createDialog.valuePlaceholder")}
              className="font-mono"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="sk-desc" className="text-xs">{t("createDialog.descriptionLabel")}</Label>
            <Input
              id="sk-desc" value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={t("createDialog.descriptionPlaceholder")}
            />
          </div>
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

// ── Edit ────────────────────────────────────────────────────────────────────

function EditDialog({
  secret, onOpenChange, onSaved,
}: {
  secret: Secret | null;
  onOpenChange: (o: boolean) => void;
  onSaved: (s: Secret) => void;
}) {
  const { t } = useTranslation("secrets");
  const [value, setValue] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (secret) { setValue(""); setDescription(secret.description || ""); }
  }, [secret]);

  async function save() {
    if (!secret || busy) return;
    setBusy(true);
    try {
      // Only send the value when the operator actually typed a new one;
      // an empty box means "leave the stored value unchanged".
      const data: { value?: string; description?: string } = { description };
      if (value.length > 0) data.value = value;
      const s = await secretsApi.update(secret.id, data);
      onSaved(s);
      toast.success(t("toast.updated"));
    } catch (err) {
      toast.error(String(err instanceof Error ? err.message : err) || t("toast.updateFailed"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={!!secret} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="font-mono">{secret?.key}</DialogTitle>
          <DialogDescription>
            {t("editDialog.currentValue")} <span className="font-mono">{secret?.preview || t("list.empty")}</span>. {t("editDialog.leaveBlank")}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3 py-2">
          <div className="space-y-1.5">
            <Label htmlFor="se-val" className="text-xs">{t("editDialog.newValueLabel")}</Label>
            <Input
              id="se-val" value={value} type="password" autoFocus
              onChange={(e) => setValue(e.target.value)}
              placeholder={t("editDialog.newValuePlaceholder")}
              className="font-mono"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="se-desc" className="text-xs">{t("editDialog.descriptionLabel")}</Label>
            <Input
              id="se-desc" value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={t("editDialog.descriptionPlaceholder")}
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>{t("actions.cancel")}</Button>
          <Button onClick={save} disabled={busy} className="gap-1.5">
            {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
            {t("actions.save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
