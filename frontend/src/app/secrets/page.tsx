"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
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

export default function SecretsPage() {
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
    if (!confirm(`Delete secret ${s.key}? Scripts referencing it will no longer read a value.`)) return;
    try {
      await secretsApi.delete(s.id);
      setItems((prev) => prev.filter((x) => x.id !== s.id));
      toast.success("Deleted");
    } catch {
      toast.error("Delete failed");
    }
  }

  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-border px-6 py-3 flex items-center gap-3">
        <Link href="/">
          <Button variant="ghost" size="sm" className="gap-1.5">
            <ArrowLeft className="h-4 w-4" />
            Home
          </Button>
        </Link>
        <div className="flex items-center gap-2">
          <Lock className="h-4 w-4 text-primary" />
          <span className="font-semibold text-sm">Secrets</span>
        </div>
        <Button size="sm" className="ml-auto gap-1.5" onClick={() => setCreating(true)}>
          <Plus className="h-3.5 w-3.5" />
          New Secret
        </Button>
      </header>

      <main className="flex-1 px-6 py-8 max-w-3xl mx-auto w-full">
        <p className="text-xs text-muted-foreground mb-5">
          Credentials are stored server-side and injected into the script process at run time —
          they <b>never appear in source code, input data, or the frontend</b>. Read them in a
          script with{" "}
          <code className="bg-muted px-1 py-0.5 rounded font-mono">get_secret(&quot;BARK_KEY&quot;)</code>{" "}
          (keys are case-insensitive). All scripts share the same set of secrets.
        </p>

        {loading ? (
          <div className="py-12 flex justify-center"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
        ) : items.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <KeyRound className="h-10 w-10 text-muted-foreground/40 mb-3" />
            <p className="text-sm text-muted-foreground">No secrets yet</p>
            <Button className="mt-4 gap-1.5" onClick={() => setCreating(true)}>
              <Plus className="h-4 w-4" />
              Add your first secret
            </Button>
          </div>
        ) : (
          <div className="divide-y divide-border/60 rounded-lg border border-border/60 overflow-hidden">
            {items.map((s) => (
              <div key={s.id} className="flex items-center gap-3 px-4 py-3 text-sm">
                <div className="min-w-0 flex-1">
                  <div className="font-mono font-medium truncate">{s.key}</div>
                  <div className="text-[11px] text-muted-foreground mt-0.5 flex items-center gap-2 flex-wrap">
                    <span className="font-mono">{s.preview || "(empty)"}</span>
                    {s.description && <span className="truncate">· {s.description}</span>}
                    <span>· updated {formatDate(s.updated_at)}</span>
                  </div>
                </div>
                <Button
                  variant="ghost" size="icon"
                  className="h-7 w-7 text-muted-foreground hover:text-foreground shrink-0"
                  onClick={() => setEditing(s)}
                  title="Edit"
                >
                  <Pencil className="h-3.5 w-3.5" />
                </Button>
                <Button
                  variant="ghost" size="icon"
                  className="h-7 w-7 text-muted-foreground hover:text-destructive shrink-0"
                  onClick={() => remove(s)}
                  title="Delete"
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
      toast.error(String(err instanceof Error ? err.message : err) || "Create failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New Secret</DialogTitle>
          <DialogDescription>Keys may contain letters, digits and underscores, and cannot start with a digit.</DialogDescription>
        </DialogHeader>
        <div className="space-y-3 py-2">
          <div className="space-y-1.5">
            <Label htmlFor="sk-key" className="text-xs">Key</Label>
            <Input
              id="sk-key" value={key} autoFocus
              onChange={(e) => setKey(e.target.value)}
              placeholder="e.g. BARK_KEY"
              className="font-mono"
            />
            {key.length > 0 && !keyValid && (
              <p className="text-[11px] text-destructive">Only letters / digits / underscore, cannot start with a digit</p>
            )}
            {keyValid && collides && (
              <p className="text-[11px] text-destructive">A secret with this key already exists (case-insensitive)</p>
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="sk-val" className="text-xs">Value</Label>
            <Input
              id="sk-val" value={value} type="password"
              onChange={(e) => setValue(e.target.value)}
              placeholder="Not shown again after saving"
              className="font-mono"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="sk-desc" className="text-xs">Description (optional)</Label>
            <Input
              id="sk-desc" value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What it's for"
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={save} disabled={!canSave} className="gap-1.5">
            {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
            Save
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
      toast.success("Updated");
    } catch (err) {
      toast.error(String(err instanceof Error ? err.message : err) || "Update failed");
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
            Current value: <span className="font-mono">{secret?.preview || "(empty)"}</span>. Leave blank to keep it unchanged.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3 py-2">
          <div className="space-y-1.5">
            <Label htmlFor="se-val" className="text-xs">New value</Label>
            <Input
              id="se-val" value={value} type="password" autoFocus
              onChange={(e) => setValue(e.target.value)}
              placeholder="Leave blank to keep current"
              className="font-mono"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="se-desc" className="text-xs">Description</Label>
            <Input
              id="se-desc" value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What it's for"
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={save} disabled={busy} className="gap-1.5">
            {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
