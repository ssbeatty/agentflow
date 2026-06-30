"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { Zap, Loader2, ShieldCheck } from "lucide-react";
import { toast } from "sonner";
import { auth } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export default function SetupPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);

  const tooShortUser = username.length > 0 && username.length < 3;
  const tooShortPass = password.length > 0 && password.length < 6;
  const mismatch = confirm.length > 0 && confirm !== password;
  const valid =
    username.length >= 3 && password.length >= 6 && confirm === password;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!valid || busy) return;
    setBusy(true);
    try {
      await auth.setup(username, password);
      toast.success("管理员账户已创建");
      router.replace("/");
    } catch (err) {
      toast.error(String(err instanceof Error ? err.message : err) || "创建失败");
      setBusy(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-background px-4">
      <div className="w-full max-w-sm">
        <div className="flex flex-col items-center mb-8">
          <div className="h-12 w-12 rounded-2xl bg-primary/15 flex items-center justify-center mb-3">
            <Zap className="h-6 w-6 text-primary" />
          </div>
          <h1 className="text-xl font-semibold">初始化 AgentFlow</h1>
          <p className="text-sm text-muted-foreground mt-1 text-center">
            创建管理员账户。此账户用于登录整个管理后台。
          </p>
        </div>

        <form onSubmit={submit} className="rounded-xl border border-border bg-secondary/20 p-6 space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="username" className="text-xs">用户名</Label>
            <Input
              id="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoFocus
              autoComplete="username"
              placeholder="admin"
            />
            {tooShortUser && <p className="text-[11px] text-destructive">用户名至少 3 个字符</p>}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="password" className="text-xs">密码</Label>
            <Input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password"
              placeholder="至少 6 个字符"
            />
            {tooShortPass && <p className="text-[11px] text-destructive">密码至少 6 个字符</p>}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="confirm" className="text-xs">确认密码</Label>
            <Input
              id="confirm"
              type="password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              autoComplete="new-password"
              placeholder="再次输入密码"
            />
            {mismatch && <p className="text-[11px] text-destructive">两次密码不一致</p>}
          </div>
          <Button type="submit" className="w-full gap-2" disabled={!valid || busy}>
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldCheck className="h-4 w-4" />}
            创建并登录
          </Button>
        </form>
      </div>
    </div>
  );
}
