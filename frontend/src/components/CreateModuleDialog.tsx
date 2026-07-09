"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import { scripts } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription,
} from "@/components/ui/dialog";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/** Slug a display name into a valid python package identifier (matches the
 *  backend's normalize_package_name; the backend re-derives/validates anyway). */
function slugPackage(name: string): string {
  const s = name.trim().toLowerCase().replace(/[^0-9a-z_]+/g, "_").replace(/^_+|_+$/g, "");
  if (!s) return "";
  return /^[0-9]/.test(s) ? "mod_" + s : s;
}

export default function CreateModuleDialog({ open, onOpenChange }: Props) {
  const { t } = useTranslation("module");
  const router = useRouter();
  const [name, setName] = useState("");
  const [pkg, setPkg] = useState("");
  const [pkgEdited, setPkgEdited] = useState(false);
  const [loading, setLoading] = useState(false);

  const effectivePkg = pkgEdited ? pkg : slugPackage(name);

  function reset() {
    setName(""); setPkg(""); setPkgEdited(false);
  }

  async function handleCreate() {
    if (!name.trim()) return toast.error(t("create.nameRequired"));
    setLoading(true);
    try {
      const s = await scripts.create({
        name: name.trim(),
        kind: "module",
        module_package: effectivePkg || undefined,
      });
      toast.success(t("create.created"));
      reset();
      router.push(`/module?id=${s.id}`);
    } catch (e: unknown) {
      toast.error(String(e));
      setLoading(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(v) => { onOpenChange(v); if (!v) reset(); }}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{t("create.title")}</DialogTitle>
          <DialogDescription>{t("create.description")}</DialogDescription>
        </DialogHeader>

        <div className="space-y-3 py-1">
          <div className="space-y-1.5">
            <Label>{t("create.name")}</Label>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t("create.namePlaceholder")}
              onKeyDown={(e) => e.key === "Enter" && handleCreate()}
              autoFocus
            />
          </div>
          <div className="space-y-1.5">
            <Label>{t("create.package")}</Label>
            <Input
              value={effectivePkg}
              onChange={(e) => { setPkg(e.target.value); setPkgEdited(true); }}
              placeholder="my_module"
              className="font-mono text-sm"
            />
            <p className="text-[11px] text-muted-foreground/70">
              {t("create.importHint", { pkg: effectivePkg || "my_module" })}
            </p>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => { onOpenChange(false); reset(); }}>{t("create.cancel")}</Button>
          <Button onClick={handleCreate} disabled={loading}>
            {loading ? t("create.creating") : t("create.create")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
