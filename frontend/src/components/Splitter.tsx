"use client";
import { useEffect, useRef, useState, useCallback } from "react";

interface Props {
  /** "vertical" = drag horizontally to resize a side panel; "horizontal" = drag vertically to resize a top/bottom panel. */
  direction: "vertical" | "horizontal";
  /** initial size in pixels (width or height) */
  initial: number;
  min?: number;
  max?: number;
  /** persist size under this key in localStorage */
  storageKey?: string;
  /** which side is being resized — "start" means the panel before the divider, "end" after */
  side?: "start" | "end";
  /** rendered size value */
  onChange?: (size: number) => void;
  className?: string;
}

/**
 * Tiny VS Code-style splitter handle. Render it inline; consumer reads the
 * current size via onChange (or the `size` it pushes back).
 */
export function useResizable(opts: Props): [number, React.ReactElement] {
  const { direction, initial, min = 100, max = 2000, storageKey, side = "start", onChange } = opts;
  const [size, setSize] = useState<number>(() => {
    if (typeof window !== "undefined" && storageKey) {
      const v = Number(localStorage.getItem(storageKey));
      if (!Number.isNaN(v) && v >= min && v <= max) return v;
    }
    return initial;
  });
  const startRef = useRef<{ pos: number; size: number } | null>(null);

  useEffect(() => {
    onChange?.(size);
    if (storageKey) localStorage.setItem(storageKey, String(size));
  }, [size, onChange, storageKey]);

  const onMove = useCallback((e: MouseEvent) => {
    if (!startRef.current) return;
    const pos = direction === "vertical" ? e.clientX : e.clientY;
    const delta = pos - startRef.current.pos;
    const signed = side === "start" ? delta : -delta;
    const next = Math.max(min, Math.min(max, startRef.current.size + signed));
    setSize(next);
  }, [direction, side, min, max]);

  const onUp = useCallback(() => {
    startRef.current = null;
    document.body.style.cursor = "";
    document.body.style.userSelect = "";
    window.removeEventListener("mousemove", onMove);
    window.removeEventListener("mouseup", onUp);
  }, [onMove]);

  const onDown = (e: React.MouseEvent) => {
    e.preventDefault();
    startRef.current = {
      pos: direction === "vertical" ? e.clientX : e.clientY,
      size,
    };
    document.body.style.cursor = direction === "vertical" ? "col-resize" : "row-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  };

  const handle = (
    <div
      onMouseDown={onDown}
      className={
        direction === "vertical"
          ? "w-1 cursor-col-resize bg-transparent hover:bg-primary/40 active:bg-primary/60 transition-colors shrink-0"
          : "h-1 cursor-row-resize bg-transparent hover:bg-primary/40 active:bg-primary/60 transition-colors shrink-0"
      }
      role="separator"
      aria-orientation={direction === "vertical" ? "vertical" : "horizontal"}
    />
  );

  return [size, handle];
}
