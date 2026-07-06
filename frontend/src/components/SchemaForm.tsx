"use client";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import type { JsonSchema } from "@/lib/types";
import { orderedProperties, fieldKind, exampleForSchema } from "@/lib/schemaForm";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";

interface Props {
  schema: JsonSchema;
  /** Current form value as an object. */
  value: Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void;
}

/**
 * Renders a lightweight form for a flat-ish object JSON Schema. Scalar / enum /
 * string-array fields get proper widgets; anything else (nested object, mixed
 * array) falls back to a per-field raw-JSON textarea. Unknown-shaped schemas
 * should be gated out by isFormRenderable() before mounting this.
 */
export default function SchemaForm({ schema, value, onChange }: Props) {
  const { t } = useTranslation("scriptPanels");
  const props = useMemo(() => orderedProperties(schema), [schema]);
  const required = useMemo(() => new Set(schema.required || []), [schema]);

  function setField(key: string, v: unknown) {
    const next = { ...value };
    if (v === undefined) delete next[key];
    else next[key] = v;
    onChange(next);
  }

  return (
    <div className="space-y-3">
      {props.map(([key, sub]) => {
        const kind = fieldKind(sub);
        const isRequired = required.has(key);
        const label = (
          <label className="text-xs font-medium flex items-center gap-1.5 mb-1">
            <span className="truncate">{sub.title || key}</span>
            <span className={`text-[9px] uppercase tracking-wide ${isRequired ? "text-amber-500" : "text-muted-foreground/60"}`}>
              {isRequired ? t("schemaForm.required") : t("schemaForm.optional")}
            </span>
          </label>
        );
        return (
          <div key={key}>
            {label}
            <Field
              schema={sub}
              kind={kind}
              value={value[key]}
              onChange={(v) => setField(key, v)}
            />
            {sub.description && (
              <p className="text-[10px] text-muted-foreground/70 mt-0.5">{sub.description}</p>
            )}
          </div>
        );
      })}
    </div>
  );
}

function Field({
  schema, kind, value, onChange,
}: {
  schema: JsonSchema;
  kind: ReturnType<typeof fieldKind>;
  value: unknown;
  onChange: (v: unknown) => void;
}) {
  const { t } = useTranslation("scriptPanels");

  if (kind === "boolean") {
    return (
      <label className="inline-flex items-center gap-2 cursor-pointer select-none">
        <input
          type="checkbox"
          checked={value === true}
          onChange={(e) => onChange(e.target.checked)}
          className="h-4 w-4 rounded border-border accent-primary"
        />
        <span className="text-xs text-muted-foreground">
          {value === true ? t("schemaForm.booleanTrue") : t("schemaForm.booleanFalse")}
        </span>
      </label>
    );
  }

  if (kind === "enum") {
    const opts = (schema.enum || []).map((o) => String(o));
    return (
      <Select value={value === undefined ? "" : String(value)} onValueChange={(v) => onChange(coerceEnum(v, schema.enum || []))}>
        <SelectTrigger className="h-8 text-xs">
          <SelectValue placeholder={t("schemaForm.selectPlaceholder")} />
        </SelectTrigger>
        <SelectContent>
          {opts.map((o) => (
            <SelectItem key={o} value={o} className="text-xs">{o}</SelectItem>
          ))}
        </SelectContent>
      </Select>
    );
  }

  if (kind === "integer" || kind === "number") {
    return (
      <Input
        type="number"
        className="h-8 text-xs"
        value={value === undefined || value === null ? "" : String(value)}
        min={typeof schema.minimum === "number" ? schema.minimum : undefined}
        max={typeof schema.maximum === "number" ? schema.maximum : undefined}
        step={kind === "integer" ? 1 : "any"}
        onChange={(e) => {
          const raw = e.target.value;
          if (raw === "") return onChange(undefined);
          const n = kind === "integer" ? parseInt(raw, 10) : parseFloat(raw);
          onChange(Number.isNaN(n) ? undefined : n);
        }}
      />
    );
  }

  if (kind === "string-array") {
    const text = Array.isArray(value) ? (value as unknown[]).join("\n") : "";
    return (
      <Textarea
        className="text-xs font-mono min-h-[54px] resize-y"
        placeholder={t("schemaForm.arrayHint")}
        value={text}
        onChange={(e) => {
          const lines = e.target.value.split("\n").map((s) => s.trim()).filter(Boolean);
          onChange(lines.length ? lines : undefined);
        }}
      />
    );
  }

  if (kind === "json") {
    // Nested object / mixed array / unknown → raw JSON field.
    return <JsonField value={value} onChange={onChange} placeholder={JSON.stringify(exampleForSchema(schema))} />;
  }

  // string (default)
  return (
    <Input
      className="h-8 text-xs"
      value={value === undefined || value === null ? "" : String(value)}
      placeholder={schema.format || ""}
      onChange={(e) => onChange(e.target.value === "" ? undefined : e.target.value)}
    />
  );
}

function JsonField({
  value, onChange, placeholder,
}: {
  value: unknown;
  onChange: (v: unknown) => void;
  placeholder?: string;
}) {
  const { t } = useTranslation("scriptPanels");
  // Keep the raw text locally so partial edits don't get clobbered by re-parse.
  const text = value === undefined ? "" : JSON.stringify(value, null, 2);
  let invalid = false;
  return (
    <div>
      <Textarea
        className="text-xs font-mono min-h-[54px] resize-y"
        defaultValue={text}
        placeholder={placeholder}
        spellCheck={false}
        onChange={(e) => {
          const raw = e.target.value;
          if (raw.trim() === "") return onChange(undefined);
          try {
            onChange(JSON.parse(raw));
            invalid = false;
          } catch {
            invalid = true;
          }
        }}
      />
      {invalid && <p className="text-[10px] text-destructive mt-0.5">{t("schemaForm.invalidJson")}</p>}
    </div>
  );
}

function coerceEnum(v: string, options: unknown[]): unknown {
  // Match back to the original typed value (numbers/booleans in the enum).
  const match = options.find((o) => String(o) === v);
  return match === undefined ? v : match;
}
