import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Backend stores naive UTC; treat strings without timezone as UTC, then format local. */
export function toLocalDate(d: string | Date): Date {
  if (d instanceof Date) return d;
  // ISO string with no timezone suffix → assume UTC
  const hasTz = /([zZ]|[+-]\d{2}:?\d{2})$/.test(d);
  return new Date(hasTz ? d : d + "Z");
}

export function formatDate(d: string | Date): string {
  return toLocalDate(d).toLocaleString(undefined, {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Compact, locale-aware number for token/usage badges: 1234 → "1.2K". */
export function compactNumber(n: number): string {
  return new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(n || 0);
}

/**
 * Collapse a long/multi-line error (e.g. a Python traceback) into one short
 * line for toast display. The last non-empty line is normally the actual
 * `ExceptionType: message` — Python's own traceback convention — so it's a
 * better summary than the first line ("Traceback (most recent call last):").
 * Full detail belongs in a log panel, not a toast.
 */
export function summarizeError(text: string, maxLen = 160): string {
  const lines = text.split("\n").map((l) => l.trim()).filter(Boolean);
  const line = lines[lines.length - 1] ?? text.trim();
  return line.length > maxLen ? `${line.slice(0, maxLen - 1)}…` : line;
}
