"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { Plus, Play, Clock, Settings, Zap, MessageSquare, BookOpen, Wrench } from "lucide-react";
import { toast } from "sonner";
import { scripts } from "@/lib/api";
import type { ScriptSummary } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { formatDate } from "@/lib/utils";
import CreateScriptDialog from "@/components/CreateScriptDialog";

export default function Dashboard() {
  const [items, setItems] = useState<ScriptSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);

  useEffect(() => {
    scripts.list()
      .then(setItems)
      .catch(() => toast.error("Failed to load scripts"))
      .finally(() => setLoading(false));
  }, []);

  const handleCreated = (s: ScriptSummary) => {
    setItems((prev) => [s as ScriptSummary, ...prev]);
    setDialogOpen(false);
  };

  return (
    <div className="min-h-screen flex flex-col">
      {/* Navbar */}
      <header className="border-b border-border px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Zap className="h-5 w-5 text-primary" />
          <span className="font-semibold text-base">OpenGraph</span>
        </div>
        <div className="flex items-center gap-2">
          <Link href="/chat">
            <Button variant="ghost" size="sm" className="gap-1.5">
              <MessageSquare className="h-4 w-4" />
              Chat
            </Button>
          </Link>
          <Link href="/docs">
            <Button variant="ghost" size="sm" className="gap-1.5">
              <BookOpen className="h-4 w-4" />
              Docs
            </Button>
          </Link>
          <Link href="/tools">
            <Button variant="ghost" size="sm" className="gap-1.5">
              <Wrench className="h-4 w-4" />
              Tools
            </Button>
          </Link>
          <Link href="/settings">
            <Button variant="ghost" size="icon">
              <Settings className="h-4 w-4" />
            </Button>
          </Link>
          <Button size="sm" onClick={() => setDialogOpen(true)}>
            <Plus className="h-4 w-4" />
            New Script
          </Button>
        </div>
      </header>

      {/* Main */}
      <main className="flex-1 px-6 py-8 max-w-6xl mx-auto w-full">
        <div className="mb-6">
          <h1 className="text-2xl font-semibold">Scripts</h1>
          <p className="text-muted-foreground text-sm mt-1">
            {items.length} LangGraph agent{items.length !== 1 ? "s" : ""}
          </p>
        </div>

        {loading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {[...Array(3)].map((_, i) => (
              <div key={i} className="h-40 rounded-xl border border-border bg-secondary/30 animate-pulse" />
            ))}
          </div>
        ) : items.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-24 text-center">
            <Zap className="h-12 w-12 text-muted-foreground/40 mb-4" />
            <p className="text-muted-foreground">No scripts yet</p>
            <Button className="mt-4" onClick={() => setDialogOpen(true)}>
              <Plus className="h-4 w-4" />
              Create your first script
            </Button>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {items.map((s) => (
              <ScriptCard key={s.id} script={s} />
            ))}
          </div>
        )}
      </main>

      <CreateScriptDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        onCreated={handleCreated}
      />
    </div>
  );
}

function ScriptCard({ script }: { script: ScriptSummary }) {
  return (
    <div className="group rounded-xl border border-border bg-secondary/20 p-5 hover:border-primary/50 hover:bg-secondary/40 transition-all h-full flex flex-col">
      <Link href={`/script/?id=${script.id}`} className="block flex-1">
        <h3 className="font-medium text-sm leading-tight line-clamp-2 group-hover:text-primary transition-colors mb-3">
          {script.name}
        </h3>
        {script.description && (
          <p className="text-xs text-muted-foreground line-clamp-2 mb-3">
            {script.description}
          </p>
        )}
      </Link>
      <div className="flex items-center gap-3 mt-auto pt-2 border-t border-border/50 text-xs text-muted-foreground">
        <span className="flex items-center gap-1">
          <Clock className="h-3 w-3" />
          {formatDate(script.updated_at)}
        </span>
        <div className="ml-auto flex items-center gap-1">
          <Link
            href={`/chat?id=${script.id}`}
            className="flex items-center gap-1 hover:text-primary px-1.5 py-0.5 rounded transition-colors"
            onClick={(e) => e.stopPropagation()}
          >
            <MessageSquare className="h-3 w-3" />
            Chat
          </Link>
          <Link
            href={`/script/?id=${script.id}`}
            className="flex items-center gap-1 hover:text-primary px-1.5 py-0.5 rounded transition-colors"
          >
            <Play className="h-3 w-3" />
            Open
          </Link>
        </div>
      </div>
    </div>
  );
}
