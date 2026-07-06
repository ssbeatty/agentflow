import type { JsonSchema } from "./types";

// Build a representative example value for a JSON Schema — used for the /docs
// typed call example and as a form's initial value. Prefers an explicit
// `default`/`example`, then `enum[0]`, then a type-based placeholder.
export function exampleForSchema(schema: JsonSchema | null | undefined): unknown {
  if (!schema || typeof schema !== "object") return {};
  if ("default" in schema) return schema.default;
  if ("example" in schema) return (schema as Record<string, unknown>).example;
  if (Array.isArray(schema.enum) && schema.enum.length > 0) return schema.enum[0];

  const type = Array.isArray(schema.type) ? schema.type[0] : schema.type;
  switch (type) {
    case "object": {
      const out: Record<string, unknown> = {};
      const props = schema.properties || {};
      for (const [key, sub] of Object.entries(props)) {
        out[key] = exampleForSchema(sub);
      }
      return out;
    }
    case "array":
      return schema.items ? [exampleForSchema(schema.items)] : [];
    case "integer":
    case "number":
      return typeof schema.minimum === "number" ? schema.minimum : 0;
    case "boolean":
      return false;
    case "string":
      if (schema.format === "date") return "2024-01-01";
      if (schema.format === "date-time") return "2024-01-01T00:00:00Z";
      return schema.description ? "" : "string";
    case "null":
      return null;
    default:
      // untyped / anyOf / etc. — a permissive empty object is the safest sample
      return schema.properties ? exampleForSchema({ ...schema, type: "object" }) : "";
  }
}

// Order the top-level properties: required fields first, then declared order.
export function orderedProperties(schema: JsonSchema): Array<[string, JsonSchema]> {
  const props = schema.properties || {};
  const required = new Set(schema.required || []);
  const entries = Object.entries(props);
  return entries.sort((a, b) => {
    const ra = required.has(a[0]) ? 0 : 1;
    const rb = required.has(b[0]) ? 0 : 1;
    return ra - rb;
  });
}

// Is this schema a flat-ish object we can render as a form? (top-level object
// whose fields are scalars / enums / string-arrays). Nested objects fall back
// to the raw-JSON editor.
export function isFormRenderable(schema: JsonSchema | null | undefined): boolean {
  if (!schema || typeof schema !== "object") return false;
  const type = Array.isArray(schema.type) ? schema.type[0] : schema.type;
  if (type !== "object" || !schema.properties) return false;
  return true;
}

export type FieldKind = "string" | "number" | "integer" | "boolean" | "enum" | "string-array" | "json";

export function fieldKind(schema: JsonSchema): FieldKind {
  if (Array.isArray(schema.enum) && schema.enum.length > 0) return "enum";
  const type = Array.isArray(schema.type) ? schema.type[0] : schema.type;
  if (type === "boolean") return "boolean";
  if (type === "integer") return "integer";
  if (type === "number") return "number";
  if (type === "string") return "string";
  if (type === "array") {
    const items = schema.items;
    const itemType = items && (Array.isArray(items.type) ? items.type[0] : items.type);
    if (itemType === "string") return "string-array";
  }
  return "json"; // object / mixed array / unknown → raw JSON field
}
