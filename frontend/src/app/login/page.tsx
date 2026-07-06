"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import { Zap, Loader2, LogIn } from "lucide-react";
import { toast } from "sonner";
import { auth } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export default function LoginPage() {
  const router = useRouter();
  const { t } = useTranslation(["login", "common"]);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!username || !password || busy) return;
    setBusy(true);
    try {
      await auth.login(username, password);
      router.replace("/");
    } catch {
      toast.error(t("login:toast.invalidCredentials"));
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
          <h1 className="text-xl font-semibold">{t("common:app.name")}</h1>
          <p className="text-sm text-muted-foreground mt-1">{t("login:subtitle")}</p>
        </div>

        <form onSubmit={submit} className="rounded-xl border border-border bg-secondary/20 p-6 space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="username" className="text-xs">{t("login:form.username")}</Label>
            <Input
              id="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoFocus
              autoComplete="username"
              placeholder={t("login:form.usernamePlaceholder")}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="password" className="text-xs">{t("login:form.password")}</Label>
            <Input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              placeholder="••••••••"
            />
          </div>
          <Button type="submit" className="w-full gap-2" disabled={busy || !username || !password}>
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <LogIn className="h-4 w-4" />}
            {t("login:form.submit")}
          </Button>
        </form>
      </div>
    </div>
  );
}
