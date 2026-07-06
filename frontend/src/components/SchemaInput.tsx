"use client";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { FileJson, LayoutList } from "lucide-react";
import type { JsonSchema } from "@/lib/types";
import { isFormRenderable, exampleForSchema } from "@/lib/schemaForm";
import SchemaForm from "@/components/SchemaForm";
import InputPresetEditor from "@/components/InputPresetEditor";

interface Props {
  scriptId: string;
  schema?: JsonSchema | null;
  /** Input as a JSON string (the run/preset source of truth). */
  value: string;
  onChange: (v: string) => void;
  error: string;
  onError: (e: string) => void;
}

/**
 * Input editor that adapts to the script's declared INPUT_SCHEMA:
 *  - schema present & form-renderable → a Form/JSON toggle; Form mode renders a
 *    typed widget per field, JSON mode is the classic preset editor.
 *  - no schema → just the classic preset editor (legacy behaviour).
 * The `value` (a JSON string) stays the single source of truth for running.
 */
export default function SchemaInput({ scriptId, schema, value, onChange, error, onError }: Props) {
  const { t } = useTranslation("scriptPanels");
  const renderable = isFormRenderable(schema);
  const [mode, setMode] = useState<"form" | "json">(renderable ? "form" : "json");

  const jsonEditor = (
    <InputPresetEditor
      scriptId={scriptId}
      value={value}
      onChange={onChange}
      error={error}
      onError={onError}
    />
  );

  if (!schema || !renderable) return jsonEditor;

  // Parse current JSON into an object for the form (best-effort).
  let obj: Record<string, unknown> = {};
  try {
    const parsed = JSON.parse(value || "{}");
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) obj = parsed as Record<string, unknown>;
  } catch { /* keep {} */ }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <span
          className="text-[9px] uppercase tracking-wide px-1.5 py-0.5 rounded bg-primary/10 text-primary font-semibold"
          title={t("schemaForm.schemaBadgeTitle")}
        >
          {t("schemaForm.schemaBadge")}
        </span>
        <div className="flex items-center gap-0.5 rounded-md border border-border p-0.5">
          <button
            type="button"
            onClick={() => setMode("form")}
            className={`h-6 px-2 rounded text-[11px] flex items-center gap-1 transition-colors ${
              mode === "form" ? "bg-secondary text-foreground" : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <LayoutList className="h-3 w-3" /> {t("schemaForm.modeForm")}
          </button>
          <button
            type="button"
            onClick={() => setMode("json")}
            className={`h-6 px-2 rounded text-[11px] flex items-center gap-1 transition-colors ${
              mode === "json" ? "bg-secondary text-foreground" : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <FileJson className="h-3 w-3" /> {t("schemaForm.modeJson")}
          </button>
        </div>
      </div>

      {mode === "form" ? (
        <SchemaForm
          schema={schema}
          value={obj}
          onChange={(next) => {
            onChange(JSON.stringify(next, null, 2));
            onError("");
          }}
        />
      ) : (
        jsonEditor
      )}
    </div>
  );
}

// Re-export so callers can seed an initial input from the schema if desired.
export { exampleForSchema };
