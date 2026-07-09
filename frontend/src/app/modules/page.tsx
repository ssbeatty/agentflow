"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useTranslation } from "react-i18next";
import { ArrowLeft, Plus, Clock, Blocks, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { scripts } from "@/lib/api";
import type { ScriptSummary } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { formatDate } from "@/lib/utils";
import CreateModuleDialog from "@/components/CreateModuleDialog";

export default function ModulesPage() {
  const { t } = useTranslation("dashboard");
  const [modules, setModules] = useState<ScriptSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);

  useEffect(() => {
    scripts.list("module")
      .then(setModules)
      .catch(() => toast.error(t("toast.loadFailed")))
      .finally(() => setLoading(false));
  }, [t]);

  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-border px-6 py-3 flex items-center gap-3">
        <Link href="/">
          <Button variant="ghost" size="icon"><ArrowLeft className="h-4 w-4" /></Button>
        </Link>
        <Blocks className="h-5 w-5 text-primary" />
        <span className="font-semibold text-base">{t("modules.heading")}</span>
        <div className="flex-1" />
        <Button size="sm" onClick={() => setDialogOpen(true)}>
          <Plus className="h-4 w-4" />
          {t("modules.new")}
        </Button>
      </header>

      <main className="flex-1 px-6 py-8 max-w-6xl mx-auto w-full">
        <div className="mb-6">
          <h1 className="text-2xl font-semibold">{t("modules.heading")}</h1>
          <p className="text-muted-foreground text-sm mt-1">{t("modules.pageSubtitle")}</p>
        </div>

        {loading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {[...Array(3)].map((_, i) => (
              <div key={i} className="h-32 rounded-xl border border-border bg-secondary/30 animate-pulse" />
            ))}
          </div>
        ) : modules.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-24 text-center">
            <Blocks className="h-12 w-12 text-muted-foreground/40 mb-4" />
            <p className="text-muted-foreground">{t("modules.empty")}</p>
            <Button className="mt-4" onClick={() => setDialogOpen(true)}>
              <Plus className="h-4 w-4" />
              {t("modules.new")}
            </Button>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {modules.map((m) => (
              <ModuleCard key={m.id} module={m} />
            ))}
          </div>
        )}
      </main>

      <CreateModuleDialog open={dialogOpen} onOpenChange={setDialogOpen} />
    </div>
  );
}

function ModuleCard({ module }: { module: ScriptSummary }) {
  return (
    <Link href={`/module?id=${module.id}`}
      className="group rounded-xl border border-border bg-secondary/20 p-5 hover:border-primary/50 hover:bg-secondary/40 transition-all h-full flex flex-col">
      <div className="flex items-center gap-2 mb-2">
        <Blocks className="h-4 w-4 text-muted-foreground group-hover:text-primary transition-colors shrink-0" />
        <h3 className="font-medium text-sm leading-tight line-clamp-1 group-hover:text-primary transition-colors">
          {module.name}
        </h3>
      </div>
      {module.module_package && (
        <code className="text-[11px] text-primary/80 font-mono mb-2 truncate">
          import {module.module_package}
        </code>
      )}
      {module.description && (
        <p className="text-xs text-muted-foreground line-clamp-2">{module.description}</p>
      )}
      <div className="flex items-center gap-1 mt-auto pt-3 border-t border-border/50 text-xs text-muted-foreground">
        <Clock className="h-3 w-3" />
        {formatDate(module.updated_at)}
      </div>
    </Link>
  );
}
