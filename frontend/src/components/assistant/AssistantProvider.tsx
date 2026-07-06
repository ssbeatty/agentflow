"use client";
import {
  createContext, useCallback, useContext, useEffect, useRef, useState,
  type MutableRefObject, type ReactNode,
} from "react";

/** One file the assistant changed in a turn (for the post-turn diff / revert). */
export interface ChangedFile { filename: string; before: string; after: string; }

/** The page-provided lifecycle hooks that bind the assistant to a script/skill. */
export interface AssistantHandlers {
  /** Context object handed to the assistant each turn (kind, ids, active file, selection…). */
  buildContext: () => Record<string, unknown>;
  /** Persist unsaved edits + snapshot a baseline before a turn. */
  onBeforeTurn: () => Promise<void>;
  /** Refetch after a turn and return the files the assistant changed. */
  onAfterTurn: () => Promise<ChangedFile[]>;
  /** Undo specific files back to the pre-turn baseline. */
  onRevert: (filenames: string[]) => Promise<void>;
  /** Open a file in the page's editor. */
  onOpenFile: (filename: string) => void;
}

/** What the floating widget needs to *display* about the bound target. */
export interface BoundTarget { kind: "script" | "skill"; id: string; label: string; }

/** Everything a page registers: display info + the live handlers. */
export interface AssistantTarget extends BoundTarget, AssistantHandlers {}

interface AssistantCtx {
  /** Currently-bound editing target, or null when no editor page is open. */
  boundTarget: BoundTarget | null;
  /** Always-fresh handlers of the bound page; read at send-time (never in render). */
  handlersRef: MutableRefObject<Partial<AssistantHandlers>>;
  registerTarget: (t: BoundTarget) => void;
  clearTarget: () => void;
}

const Ctx = createContext<AssistantCtx | null>(null);

/**
 * Holds the single, app-wide assistant binding. Editor pages register the
 * script/skill they're editing (see `useAssistantTarget`); the global
 * `FloatingAssistant` reads it to know what the assistant should operate on.
 */
export function AssistantProvider({ children }: { children: ReactNode }) {
  const [boundTarget, setBoundTarget] = useState<BoundTarget | null>(null);
  const handlersRef = useRef<Partial<AssistantHandlers>>({});

  const registerTarget = useCallback((t: BoundTarget) => {
    // Only re-render when the identity actually changes (kind/id/label).
    setBoundTarget(prev =>
      prev && prev.kind === t.kind && prev.id === t.id && prev.label === t.label ? prev : t);
  }, []);

  const clearTarget = useCallback(() => {
    handlersRef.current = {};
    setBoundTarget(null);
  }, []);

  return (
    <Ctx.Provider value={{ boundTarget, handlersRef, registerTarget, clearTarget }}>
      {children}
    </Ctx.Provider>
  );
}

export function useAssistant(): AssistantCtx {
  const c = useContext(Ctx);
  if (!c) throw new Error("useAssistant must be used within <AssistantProvider>");
  return c;
}

/**
 * Editor-page hook: bind the assistant to the script/skill this page is editing.
 * Pass `null` while loading (or when there's nothing to bind) to unbind.
 *
 * The page's callbacks are recreated every render (they close over live editor
 * state); we keep the latest ones in a ref (updated after every commit) so the
 * assistant always calls the current version — without re-registering (which
 * would churn) or reading stale closures.
 */
export function useAssistantTarget(target: AssistantTarget | null) {
  const { registerTarget, clearTarget, handlersRef } = useAssistant();

  // Keep the freshest handlers available to the widget after each commit.
  useEffect(() => {
    if (target) {
      handlersRef.current = {
        buildContext: target.buildContext,
        onBeforeTurn: target.onBeforeTurn,
        onAfterTurn: target.onAfterTurn,
        onRevert: target.onRevert,
        onOpenFile: target.onOpenFile,
      };
    }
  });

  const kind = target?.kind;
  const id = target?.id;
  const label = target?.label;
  useEffect(() => {
    if (!kind || !id) { clearTarget(); return; }
    registerTarget({ kind, id, label: label ?? "" });
    return () => clearTarget();
  }, [kind, id, label, registerTarget, clearTarget]);
}
