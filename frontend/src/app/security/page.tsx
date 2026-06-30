"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ArrowLeft, KeyRound, Plus, Trash2, Loader2, Copy, Check, LogOut,
  ShieldCheck, AlertTriangle, User,
} from "lucide-react";
import { toast } from "sonner";
import { auth, apiKeys as apiKeysApi } from "@/lib/api";
import type { ApiKey, ApiKeyCreated } from "@/lib/types";
import { formatDate } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription,
} from "@/components/ui/dialog";

export default function SecurityPage() {
  const router = useRouter();
  const [username, setUsername] = useState<string>("");

  useEffect(() => {
    auth.me().then((m) => setUsername(m.username)).catch(() => {});
  }, []);

  async function logout() {
    try { await auth.logout(); } catch { /* ignore */ }
    router.replace("/login");
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
          <ShieldCheck className="h-4 w-4 text-primary" />
          <span className="font-semibold text-sm">安全设置</span>
        </div>
        <Button variant="ghost" size="sm" className="ml-auto gap-1.5 text-muted-foreground hover:text-destructive" onClick={logout}>
          <LogOut className="h-4 w-4" />
          退出登录
        </Button>
      </header>

      <main className="flex-1 px-6 py-8 max-w-3xl mx-auto w-full space-y-8">
        <AccountCard username={username} />
        <ApiKeysCard />
      </main>
    </div>
  );
}

// ── Account: change password ──────────────────────────────────────────────────

function AccountCard({ username }: { username: string }) {
  const [oldPw, setOldPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);

  const valid = oldPw.length > 0 && newPw.length >= 6 && newPw === confirm;

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!valid || busy) return;
    setBusy(true);
    try {
      await auth.changePassword(oldPw, newPw);
      toast.success("密码已更新");
      setOldPw(""); setNewPw(""); setConfirm("");
    } catch (err) {
      toast.error(String(err instanceof Error ? err.message : err) || "更新失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-xl border border-border bg-secondary/20 p-6">
      <div className="flex items-center gap-2 mb-1">
        <User className="h-4 w-4 text-primary" />
        <h2 className="font-medium text-sm">管理员账户</h2>
      </div>
      <p className="text-xs text-muted-foreground mb-4">
        当前登录：<span className="font-mono text-foreground">{username || "…"}</span>
      </p>

      <form onSubmit={save} className="space-y-3 max-w-sm">
        <div className="space-y-1.5">
          <Label htmlFor="oldpw" className="text-xs">当前密码</Label>
          <Input id="oldpw" type="password" value={oldPw} onChange={(e) => setOldPw(e.target.value)} autoComplete="current-password" />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="newpw" className="text-xs">新密码（至少 6 位）</Label>
          <Input id="newpw" type="password" value={newPw} onChange={(e) => setNewPw(e.target.value)} autoComplete="new-password" />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="cfpw" className="text-xs">确认新密码</Label>
          <Input id="cfpw" type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password" />
          {confirm.length > 0 && confirm !== newPw && (
            <p className="text-[11px] text-destructive">两次密码不一致</p>
          )}
        </div>
        <Button type="submit" size="sm" disabled={!valid || busy} className="gap-1.5">
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <KeyRound className="h-3.5 w-3.5" />}
          修改密码
        </Button>
      </form>
    </section>
  );
}

// ── API keys ──────────────────────────────────────────────────────────────────

function ApiKeysCard() {
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [loading, setLoading] = useState(true);
  const [createOpen, setCreateOpen] = useState(false);
  const [newName, setNewName] = useState("");
  const [creating, setCreating] = useState(false);
  const [created, setCreated] = useState<ApiKeyCreated | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => { load(); }, []);

  async function load() {
    try { setKeys(await apiKeysApi.list()); }
    catch { /* 401 handled globally */ }
    finally { setLoading(false); }
  }

  async function create() {
    if (creating) return;
    setCreating(true);
    try {
      const k = await apiKeysApi.create(newName.trim() || "API Key");
      setCreated(k);
      setKeys((prev) => [k, ...prev]);
      setNewName("");
      setCreateOpen(false);
    } catch (err) {
      toast.error(String(err instanceof Error ? err.message : err) || "创建失败");
    } finally {
      setCreating(false);
    }
  }

  async function revoke(id: string) {
    try {
      await apiKeysApi.delete(id);
      setKeys((prev) => prev.filter((k) => k.id !== id));
      toast.success("已吊销");
    } catch {
      toast.error("吊销失败");
    }
  }

  function copyKey() {
    if (!created) return;
    navigator.clipboard.writeText(created.key).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  return (
    <section className="rounded-xl border border-border bg-secondary/20 p-6">
      <div className="flex items-center gap-2 mb-1">
        <KeyRound className="h-4 w-4 text-primary" />
        <h2 className="font-medium text-sm">API Keys</h2>
        <Button size="sm" className="ml-auto gap-1.5" onClick={() => setCreateOpen(true)}>
          <Plus className="h-3.5 w-3.5" />
          签发 Key
        </Button>
      </div>
      <p className="text-xs text-muted-foreground mb-4">
        外部系统调用运行接口时用作鉴权。请求头携带{" "}
        <code className="bg-muted px-1 py-0.5 rounded font-mono">X-API-Key: af_…</code>{" "}
        访问 <code className="bg-muted px-1 py-0.5 rounded font-mono">POST /api/executions/run</code>。
      </p>

      {loading ? (
        <div className="py-8 flex justify-center"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
      ) : keys.length === 0 ? (
        <p className="text-xs text-muted-foreground text-center py-8">还没有 API Key</p>
      ) : (
        <div className="divide-y divide-border/60 rounded-lg border border-border/60 overflow-hidden">
          {keys.map((k) => (
            <div key={k.id} className="flex items-center gap-3 px-4 py-3 text-sm">
              <div className="min-w-0 flex-1">
                <div className="font-medium truncate">{k.name}</div>
                <div className="text-[11px] text-muted-foreground font-mono mt-0.5">
                  {k.prefix}••••••••  ·  建于 {formatDate(k.created_at)}
                  {k.last_used_at && <>  ·  最近使用 {formatDate(k.last_used_at)}</>}
                </div>
              </div>
              <Button
                variant="ghost" size="icon"
                className="h-7 w-7 text-muted-foreground hover:text-destructive shrink-0"
                onClick={() => revoke(k.id)}
                title="吊销"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            </div>
          ))}
        </div>
      )}

      {/* Create dialog */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>签发新的 API Key</DialogTitle>
            <DialogDescription>给 Key 起个名字，便于日后识别用途。</DialogDescription>
          </DialogHeader>
          <div className="space-y-1.5 py-2">
            <Label htmlFor="keyname" className="text-xs">名称</Label>
            <Input
              id="keyname"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="例如：生产环境 / n8n 调用"
              autoFocus
              onKeyDown={(e) => { if (e.key === "Enter") create(); }}
            />
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setCreateOpen(false)}>取消</Button>
            <Button onClick={create} disabled={creating} className="gap-1.5">
              {creating && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              签发
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Show-once dialog */}
      <Dialog open={!!created} onOpenChange={(o) => { if (!o) setCreated(null); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>保存你的 API Key</DialogTitle>
            <DialogDescription className="flex items-start gap-1.5 text-amber-500">
              <AlertTriangle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
              这是唯一一次显示完整的 Key，关闭后无法再次查看，请立即复制保存。
            </DialogDescription>
          </DialogHeader>
          <div className="flex items-center gap-2 py-2">
            <code className="flex-1 min-w-0 break-all bg-muted rounded-lg px-3 py-2 text-xs font-mono">
              {created?.key}
            </code>
            <Button size="icon" variant="outline" className="shrink-0" onClick={copyKey} title="复制">
              {copied ? <Check className="h-4 w-4 text-green-500" /> : <Copy className="h-4 w-4" />}
            </Button>
          </div>
          <DialogFooter>
            <Button onClick={() => setCreated(null)}>我已保存</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}
