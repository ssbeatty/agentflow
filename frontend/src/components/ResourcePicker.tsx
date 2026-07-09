"use client";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Wrench, Sparkles, Blocks, Search, X, Check, Plus, Boxes } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";

export type ResourceType = "mcp" | "skill" | "module";

export interface ResourceItem {
  type: ResourceType;
  id: string;
  name: string;
  description?: string;
}

export type ResourceSelection = Record<ResourceType, string[]>;

interface Props {
  items: ResourceItem[];
  selected: ResourceSelection;
  onChange: (next: ResourceSelection) => void;
}

const TYPE_META: Record<ResourceType, { icon: React.ReactNode; labelKey: string }> = {
  mcp: { icon: <Wrench className="h-3.5 w-3.5" />, labelKey: "config.resources.types.mcp" },
  skill: { icon: <Sparkles className="h-3.5 w-3.5" />, labelKey: "config.resources.types.skill" },
  module: { icon: <Blocks className="h-3.5 w-3.5" />, labelKey: "config.resources.types.module" },
};

const ORDER: ResourceType[] = ["mcp", "skill", "module"];

/**
 * Unified searchable picker for the resources a script binds — MCP tool servers,
 * skills, and code modules. The Config panel shows only the SELECTED items as
 * compact removable chips + a "Manage" button; the dialog is a single searchable,
 * type-filterable list. This scales to many resources without the flat chip grid
 * getting messy (search + grouping + "selected floats to top").
 */
export default function ResourcePicker({ items, selected, onChange }: Props) {
  const { t } = useTranslation("script");
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<ResourceType | "all">("all");

  const isSelected = (it: ResourceItem) => selected[it.type]?.includes(it.id);

  function toggle(it: ResourceItem) {
    const cur = selected[it.type] || [];
    const next = cur.includes(it.id) ? cur.filter(x => x !== it.id) : [...cur, it.id];
    onChange({ ...selected, [it.type]: next });
  }

  function remove(it: ResourceItem) {
    onChange({ ...selected, [it.type]: (selected[it.type] || []).filter(x => x !== it.id) });
  }

  const byId = useMemo(() => new Map(items.map(it => [`${it.type}:${it.id}`, it])), [items]);

  // Selected items (resolved to real, still-available resources), in a stable order.
  const selectedItems = useMemo(() => {
    const out: ResourceItem[] = [];
    for (const type of ORDER) {
      for (const id of selected[type] || []) {
        const it = byId.get(`${type}:${id}`);
        if (it) out.push(it);
      }
    }
    return out;
  }, [selected, byId]);

  const counts = useMemo(() => {
    const c: Record<ResourceType, number> = { mcp: 0, skill: 0, module: 0 };
    for (const it of selectedItems) c[it.type]++;
    return c;
  }, [selectedItems]);

  // Dialog list: filter by type + query, selected first, then alphabetical.
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return items
      .filter(it => filter === "all" || it.type === filter)
      .filter(it => !q || it.name.toLowerCase().includes(q) || (it.description || "").toLowerCase().includes(q))
      .sort((a, b) => {
        const sa = isSelected(a) ? 0 : 1;
        const sb = isSelected(b) ? 0 : 1;
        if (sa !== sb) return sa - sb;
        if (a.type !== b.type) return ORDER.indexOf(a.type) - ORDER.indexOf(b.type);
        return a.name.localeCompare(b.name);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items, filter, query, selected]);

  const summaryParts = ORDER
    .filter(type => counts[type] > 0)
    .map(type => `${counts[type]} ${t(TYPE_META[type].labelKey)}`);

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <p className="text-[10px] uppercase tracking-wider font-semibold text-muted-foreground/70 flex items-center gap-1.5">
          <Boxes className="h-3 w-3" />{t("config.resources.label")}
        </p>
        <Button variant="outline" size="sm" className="h-6 px-2 text-[11px]" onClick={() => setOpen(true)}>
          <Plus className="h-3 w-3" />{t("config.resources.manage")}
        </Button>
      </div>

      {selectedItems.length === 0 ? (
        <p className="text-[11px] text-muted-foreground/60 leading-snug">
          {items.length === 0 ? t("config.resources.none") : t("config.resources.empty")}
        </p>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {selectedItems.map(it => (
            <span
              key={`${it.type}:${it.id}`}
              title={it.description || it.name}
              className="inline-flex items-center gap-1.5 pl-2 pr-1 py-1 rounded-md text-xs font-medium border bg-primary/10 border-primary/40 text-primary"
            >
              <span className="opacity-70">{TYPE_META[it.type].icon}</span>
              <span className="truncate max-w-[140px]">{it.name}</span>
              <button
                onClick={() => remove(it)}
                className="rounded p-0.5 hover:bg-primary/20 transition-colors"
                title={t("config.resources.remove")}
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          ))}
        </div>
      )}
      {summaryParts.length > 0 && (
        <p className="text-[10px] text-muted-foreground/60">{summaryParts.join(" · ")}</p>
      )}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-lg flex flex-col max-h-[80vh]">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-base">
              <Boxes className="h-4 w-4 text-primary" />{t("config.resources.dialogTitle")}
            </DialogTitle>
          </DialogHeader>

          <div className="relative shrink-0">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
            <Input
              autoFocus
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder={t("config.resources.searchPlaceholder")}
              className="h-8 pl-8 text-sm"
            />
          </div>

          <div className="flex items-center gap-1 shrink-0">
            {(["all", ...ORDER] as const).map(f => {
              const active = filter === f;
              const label = f === "all" ? t("config.resources.filters.all") : t(TYPE_META[f].labelKey);
              return (
                <button
                  key={f}
                  onClick={() => setFilter(f)}
                  className={`px-2.5 py-1 rounded-md text-xs font-medium border transition-colors ${
                    active
                      ? "bg-primary/10 border-primary/40 text-primary"
                      : "bg-secondary/30 border-border/60 text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {label}
                </button>
              );
            })}
          </div>

          <ScrollArea className="flex-1 min-h-0 -mx-1 px-1">
            {shown.length === 0 ? (
              <p className="text-xs text-muted-foreground/60 py-8 text-center">
                {t("config.resources.noMatches")}
              </p>
            ) : (
              <div className="space-y-1 py-1">
                {shown.map(it => {
                  const active = isSelected(it);
                  return (
                    <button
                      key={`${it.type}:${it.id}`}
                      onClick={() => toggle(it)}
                      className={`w-full flex items-start gap-2.5 rounded-md border px-2.5 py-2 text-left transition-colors ${
                        active
                          ? "bg-primary/10 border-primary/40"
                          : "bg-secondary/20 border-border/60 hover:border-border hover:bg-secondary/40"
                      }`}
                    >
                      <span className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border ${
                        active ? "bg-primary border-primary text-primary-foreground" : "border-border"
                      }`}>
                        {active && <Check className="h-3 w-3" />}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="flex items-center gap-1.5">
                          <span className="text-muted-foreground shrink-0">{TYPE_META[it.type].icon}</span>
                          <span className="text-xs font-medium truncate">{it.name}</span>
                          <span className="ml-auto text-[9px] uppercase tracking-wide text-muted-foreground/60 shrink-0">
                            {t(TYPE_META[it.type].labelKey)}
                          </span>
                        </span>
                        {it.description && (
                          <span className="block text-[11px] text-muted-foreground/70 leading-snug line-clamp-2 mt-0.5">
                            {it.description}
                          </span>
                        )}
                      </span>
                    </button>
                  );
                })}
              </div>
            )}
          </ScrollArea>

          <div className="flex items-center justify-between shrink-0 pt-1">
            <span className="text-[11px] text-muted-foreground/70">
              {summaryParts.length > 0 ? summaryParts.join(" · ") : t("config.resources.nothingSelected")}
            </span>
            <Button size="sm" className="h-7 text-xs" onClick={() => setOpen(false)}>
              {t("config.resources.done")}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
