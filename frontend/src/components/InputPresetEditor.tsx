"use client";
import { useEffect, useRef, useState } from "react";
import { Loader2, Save, Trash2, Plus, ChevronDown } from "lucide-react";
import { toast } from "sonner";
import { inputPresets } from "@/lib/api";
import type { ScriptInputPreset } from "@/lib/types";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { useConfirm } from "@/components/ConfirmDialogProvider";

interface Props {
  scriptId: string;
  value: string;
  onChange: (v: string) => void;
  error: string;
  onError: (e: string) => void;
}

export default function InputPresetEditor({ scriptId, value, onChange, error, onError }: Props) {
  const [presets, setPresets] = useState<ScriptInputPreset[]>([]);
  const [selectedId, setSelectedId] = useState<string>("");
  const [saving, setSaving] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [newName, setNewName] = useState("");
  const menuRef = useRef<HTMLDivElement>(null);
  const confirm = useConfirm();

  useEffect(() => {
    inputPresets.list(scriptId).then(setPresets).catch(() => null);
  }, [scriptId]);

  // Close popovers on outside click
  useEffect(() => {
    function onDown(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    }
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, []);

  const selected = presets.find(p => p.id === selectedId) ?? null;
  const dirty = selected ? selected.input_json !== value : false;

  function loadPreset(p: ScriptInputPreset) {
    onChange(p.input_json);
    onError("");
    setSelectedId(p.id);
    setMenuOpen(false);
  }

  function formatJson() {
    try {
      onChange(JSON.stringify(JSON.parse(value), null, 2));
      onError("");
    } catch {
      onError("Invalid JSON");
    }
  }

  async function saveAsNew() {
    const name = newName.trim();
    if (!name) return;
    try {
      JSON.parse(value || "{}");
    } catch {
      onError("Invalid JSON");
      return;
    }
    setSaving(true);
    try {
      const p = await inputPresets.create(scriptId, { name, input_json: value });
      setPresets(prev => [...prev, p]);
      setSelectedId(p.id);
      setNewName("");
      setCreateOpen(false);
      toast.success(`Saved preset "${name}"`);
    } catch (e: unknown) {
      toast.error(String(e));
    } finally { setSaving(false); }
  }

  async function updateCurrent() {
    if (!selected) return;
    try {
      JSON.parse(value || "{}");
    } catch {
      onError("Invalid JSON");
      return;
    }
    setSaving(true);
    try {
      const p = await inputPresets.update(scriptId, selected.id, { input_json: value });
      setPresets(prev => prev.map(x => x.id === p.id ? p : x));
      toast.success("Preset updated");
    } catch (e: unknown) {
      toast.error(String(e));
    } finally { setSaving(false); }
  }

  async function deleteCurrent() {
    if (!selected) return;
    if (!(await confirm(`Delete preset "${selected.name}"?`, { confirmLabel: "Delete", destructive: true }))) return;
    try {
      await inputPresets.delete(scriptId, selected.id);
      setPresets(prev => prev.filter(x => x.id !== selected.id));
      setSelectedId("");
      toast.success("Preset deleted");
    } catch (e: unknown) {
      toast.error(String(e));
    }
  }

  return (
    <div className="space-y-1.5">
      <p className="text-[10px] uppercase tracking-wider font-semibold text-muted-foreground/70 flex items-center justify-between">
        <span className="flex items-center gap-2">
          Input JSON
          {error && <span className="text-destructive normal-case font-normal">{error}</span>}
          {selected && dirty && <span className="text-amber-400 normal-case font-normal">modified</span>}
        </span>
        <button onClick={formatJson}
          className="text-[10px] normal-case font-normal text-muted-foreground hover:text-foreground transition-colors">
          Format
        </button>
      </p>

      {/* Preset selector row */}
      <div className="flex items-center gap-1.5" ref={menuRef}>
        <div className="relative flex-1 min-w-0">
          <button
            type="button"
            onClick={() => setMenuOpen(v => !v)}
            className="w-full h-7 px-2.5 flex items-center gap-1.5 rounded-md border border-border bg-secondary/30 hover:bg-secondary/50 transition-colors text-xs text-left"
          >
            <span className="truncate flex-1">
              {selected ? selected.name : <span className="text-muted-foreground">No preset</span>}
            </span>
            <ChevronDown className="h-3 w-3 text-muted-foreground shrink-0" />
          </button>
          {menuOpen && (
            <div className="absolute z-10 mt-1 left-0 right-0 max-h-56 overflow-y-auto rounded-md border border-border bg-popover shadow-lg">
              <button
                onClick={() => { setSelectedId(""); setMenuOpen(false); }}
                className="w-full text-left px-2.5 py-1.5 text-xs text-muted-foreground hover:bg-secondary/50"
              >
                — None (manual input) —
              </button>
              {presets.length === 0 && (
                <div className="px-2.5 py-1.5 text-xs text-muted-foreground italic">No saved presets</div>
              )}
              {presets.map(p => (
                <button key={p.id} onClick={() => loadPreset(p)}
                  className={`w-full text-left px-2.5 py-1.5 text-xs hover:bg-secondary/50 truncate ${
                    p.id === selectedId ? "bg-secondary/40 text-foreground" : ""
                  }`}>
                  {p.name}
                </button>
              ))}
            </div>
          )}
        </div>

        {selected && (
          <>
            <Button variant="outline" size="sm" className="h-7 px-2"
              onClick={updateCurrent} disabled={saving || !dirty} title="Update preset with current input">
              {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />}
            </Button>
            <Button variant="outline" size="sm" className="h-7 px-2 text-muted-foreground hover:text-destructive"
              onClick={deleteCurrent} title="Delete preset">
              <Trash2 className="h-3 w-3" />
            </Button>
          </>
        )}

        <Button variant="outline" size="sm" className="h-7 px-2"
          onClick={() => { setCreateOpen(v => !v); setNewName(""); }} title="Save as new preset">
          <Plus className="h-3 w-3" />
        </Button>
      </div>

      {createOpen && (
        <div className="flex items-center gap-1.5">
          <Input
            value={newName}
            onChange={e => setNewName(e.target.value)}
            placeholder="Preset name (e.g. edge case)"
            className="h-7 text-xs flex-1"
            autoFocus
            onKeyDown={e => {
              if (e.key === "Enter") saveAsNew();
              if (e.key === "Escape") { setCreateOpen(false); setNewName(""); }
            }}
          />
          <Button size="sm" className="h-7 px-2" onClick={saveAsNew} disabled={saving || !newName.trim()}>
            {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : "Save"}
          </Button>
        </div>
      )}

      <Textarea
        value={value}
        onChange={e => { onChange(e.target.value); onError(""); }}
        className="text-xs font-mono min-h-[100px] resize-y"
        placeholder="{}"
        spellCheck={false}
      />
    </div>
  );
}
