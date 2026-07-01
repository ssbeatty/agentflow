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
      toast.success("Admin account created");
      router.replace("/");
    } catch (err) {
      toast.error(String(err instanceof Error ? err.message : err) || "Setup failed");
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
          <h1 className="text-xl font-semibold">Initialize AgentFlow</h1>
          <p className="text-sm text-muted-foreground mt-1 text-center">
            Create the admin account. It is used to sign in to the entire admin console.
          </p>
        </div>

        <form onSubmit={submit} className="rounded-xl border border-border bg-secondary/20 p-6 space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="username" className="text-xs">Username</Label>
            <Input
              id="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoFocus
              autoComplete="username"
              placeholder="admin"
            />
            {tooShortUser && <p className="text-[11px] text-destructive">Username must be at least 3 characters</p>}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="password" className="text-xs">Password</Label>
            <Input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password"
              placeholder="At least 6 characters"
            />
            {tooShortPass && <p className="text-[11px] text-destructive">Password must be at least 6 characters</p>}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="confirm" className="text-xs">Confirm Password</Label>
            <Input
              id="confirm"
              type="password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              autoComplete="new-password"
              placeholder="Re-enter password"
            />
            {mismatch && <p className="text-[11px] text-destructive">Passwords do not match</p>}
          </div>
          <Button type="submit" className="w-full gap-2" disabled={!valid || busy}>
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldCheck className="h-4 w-4" />}
            Create and sign in
          </Button>
        </form>
      </div>
    </div>
  );
}
