"use client";
import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";
import { AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";

interface ConfirmOpts {
  confirmLabel?: string;
  cancelLabel?: string;
  /** Styles the confirm button red and shows a warning icon (delete-style actions). */
  destructive?: boolean;
}

/** App-wide replacement for `window.confirm()`, themed to match the rest of the UI. */
type ConfirmFn = (message: string, opts?: ConfirmOpts) => Promise<boolean>;

const Ctx = createContext<ConfirmFn | null>(null);

export function ConfirmDialogProvider({ children }: { children: ReactNode }) {
  const [message, setMessage] = useState<string | null>(null);
  const [opts, setOpts] = useState<ConfirmOpts>({});
  const resolveRef = useRef<((v: boolean) => void) | null>(null);

  const confirm = useCallback<ConfirmFn>((msg, o) => {
    return new Promise((resolve) => {
      resolveRef.current = resolve;
      setOpts(o ?? {});
      setMessage(msg);
    });
  }, []);

  const finish = (result: boolean) => {
    resolveRef.current?.(result);
    resolveRef.current = null;
    setMessage(null);
  };

  return (
    <Ctx.Provider value={confirm}>
      {children}
      <Dialog open={message !== null} onOpenChange={(o) => { if (!o) finish(false); }}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle className="text-sm flex items-start gap-2">
              {opts.destructive && <AlertTriangle className="h-4 w-4 text-destructive shrink-0 mt-0.5" />}
              <span>{message}</span>
            </DialogTitle>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" size="sm" onClick={() => finish(false)}>
              {opts.cancelLabel || "Cancel"}
            </Button>
            <Button variant={opts.destructive ? "destructive" : "default"} size="sm" onClick={() => finish(true)}>
              {opts.confirmLabel || "Confirm"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Ctx.Provider>
  );
}

export function useConfirm(): ConfirmFn {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useConfirm must be used within <ConfirmDialogProvider>");
  return ctx;
}
