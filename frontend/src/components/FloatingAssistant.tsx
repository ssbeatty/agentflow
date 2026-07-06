"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { Sparkles } from "lucide-react";
import AssistantPanel from "@/components/AssistantPanel";
import { useAssistant } from "@/components/assistant/AssistantProvider";
import { cn } from "@/lib/utils";

// Public routes never show the assistant (AuthGate still renders children there
// while logged out, so we must guard explicitly).
const PUBLIC_ROUTES = ["/login", "/setup"];
const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

/**
 * App-wide AI assistant: a bottom-right bubble that expands into a non-modal,
 * resizable floating card. Always mounted (inside the authed layout), so an
 * in-flight run keeps streaming and the chat survives collapsing / navigation.
 * It binds to the current script/skill editor page via AssistantProvider, and
 * otherwise operates in "global" mode (create/edit anything, no diff).
 */
export default function FloatingAssistant() {
  const raw = usePathname();
  const pathname = raw !== "/" ? raw.replace(/\/$/, "") : raw;
  const { boundTarget, handlersRef } = useAssistant();

  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [unseen, setUnseen] = useState(false);

  // Card size (persisted). Init to defaults; hydrate from localStorage on mount.
  const [w, setW] = useState(400);
  const [h, setH] = useState(580);
  const [dragging, setDragging] = useState(false);
  const dragStart = useRef<{ x: number; y: number; w: number; h: number } | null>(null);

  useEffect(() => {
    const sw = Number(localStorage.getItem("ag.assistantW"));
    const sh = Number(localStorage.getItem("ag.assistantH"));
    if (sw) setW(sw);
    if (sh) setH(sh);
  }, []);
  useEffect(() => { localStorage.setItem("ag.assistantW", String(w)); }, [w]);
  useEffect(() => { localStorage.setItem("ag.assistantH", String(h)); }, [h]);

  // Corner-drag resize (card is anchored bottom-right → drag up/left grows it).
  useEffect(() => {
    if (!dragging) return;
    const move = (e: PointerEvent) => {
      const s = dragStart.current;
      if (!s) return;
      setW(clamp(s.w + (s.x - e.clientX), 340, Math.min(760, window.innerWidth - 24)));
      setH(clamp(s.h + (s.y - e.clientY), 380, window.innerHeight - 24));
    };
    const up = () => setDragging(false);
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
  }, [dragging]);

  const handleBusy = useCallback((b: boolean) => {
    setBusy(b);
    if (!b) setUnseen((prev) => (open ? prev : true));  // answered while collapsed → mark unseen
  }, [open]);

  const openCard = () => { setOpen(true); setUnseen(false); };

  if (PUBLIC_ROUTES.includes(pathname)) return null;

  const mode = boundTarget ? "bound" : "global";
  const buildContext = () =>
    (boundTarget && handlersRef.current.buildContext ? handlersRef.current.buildContext() : { kind: "none" });
  const onBeforeTurn = boundTarget
    ? () => handlersRef.current.onBeforeTurn?.() ?? Promise.resolve()
    : undefined;
  const onAfterTurn = boundTarget
    ? () => handlersRef.current.onAfterTurn?.() ?? Promise.resolve([])
    : undefined;
  const onRevert = boundTarget
    ? (fs: string[]) => handlersRef.current.onRevert?.(fs) ?? Promise.resolve()
    : undefined;
  const onOpenFile = boundTarget
    ? (f: string) => handlersRef.current.onOpenFile?.(f)
    : undefined;

  return (
    <>
      {/* Floating card — always mounted; hidden (not unmounted) when collapsed. */}
      <div
        className={cn(
          "fixed bottom-5 right-5 z-50 flex flex-col rounded-xl border border-border bg-[#1e1e1e] shadow-2xl overflow-hidden",
          !open && "hidden",
        )}
        style={{ width: w, height: h, maxWidth: "calc(100vw - 24px)", maxHeight: "calc(100vh - 24px)" }}
      >
        <div
          onPointerDown={(e) => {
            dragStart.current = { x: e.clientX, y: e.clientY, w, h };
            setDragging(true);
            e.preventDefault();
          }}
          title="Drag to resize"
          className="absolute top-0 left-0 z-10 h-5 w-5 cursor-nwse-resize"
        >
          <span className="absolute top-1 left-1 h-2 w-2 border-l-2 border-t-2 border-muted-foreground/40 rounded-tl-sm" />
        </div>
        <AssistantPanel
          mode={mode}
          boundKind={boundTarget?.kind}
          boundLabel={boundTarget?.label}
          boundId={boundTarget?.id}
          buildContext={buildContext}
          onBeforeTurn={onBeforeTurn}
          onAfterTurn={onAfterTurn}
          onRevert={onRevert}
          onOpenFile={onOpenFile}
          onClose={() => setOpen(false)}
          onBusyChange={handleBusy}
        />
      </div>

      {/* Collapsed bubble */}
      {!open && (
        <button
          onClick={openCard}
          title="AI Assistant"
          className="fixed bottom-5 right-5 z-50 h-12 w-12 rounded-full bg-primary text-primary-foreground shadow-lg flex items-center justify-center hover:scale-105 transition-transform"
        >
          <Sparkles className="h-5 w-5" />
          {(busy || unseen) && (
            <span className="absolute -top-0.5 -right-0.5 h-3 w-3 rounded-full bg-emerald-400 ring-2 ring-[#1e1e1e] animate-pulse" />
          )}
        </button>
      )}
    </>
  );
}
