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
