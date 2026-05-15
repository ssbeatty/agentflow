"use client";
import { useEffect, useRef } from "react";
import type { ExecutionLog } from "@/lib/types";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";

const LEVEL_STYLES: Record<string, string> = {
  info:    "text-blue-400",
  node:    "text-violet-400",
  warning: "text-amber-400",
  error:   "text-red-400",
  debug:   "text-muted-foreground",
  raw:     "text-foreground/70",
};

const LEVEL_TAG: Record<string, string> = {
  info:    "INFO",
  node:    "NODE",
  warning: "WARN",
  error:   "ERR ",
  debug:   "DBG ",
  raw:     "OUT ",
};

interface Props {
  logs: ExecutionLog[];
}

export default function LogPanel({ logs }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);

  return (
    <ScrollArea className="h-full">
      <div className="px-3 py-2 space-y-0.5 font-mono text-xs">
        {logs.length === 0 ? (
          <p className="text-muted-foreground py-4 text-center">Run the script to see logs</p>
        ) : (
          logs.map((log) => (
            <LogEntry key={log.id} log={log} />
          ))
        )}
        <div ref={bottomRef} />
      </div>
    </ScrollArea>
  );
}

function LogEntry({ log }: { log: ExecutionLog }) {
  const color = LEVEL_STYLES[log.level] ?? "text-foreground";
  const tag = LEVEL_TAG[log.level] ?? log.level.toUpperCase().slice(0, 4).padEnd(4);
  const time = new Date(log.timestamp).toLocaleTimeString("en-US", {
    hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit",
  });

  return (
    <div className="flex items-start gap-2 py-0.5 hover:bg-accent/20 px-1 rounded">
      <span className="text-muted-foreground/50 shrink-0 select-none">{time}</span>
      <span className={cn("shrink-0 select-none font-semibold", color)}>[{tag}]</span>
      {log.step && (
        <span className="shrink-0 text-muted-foreground/60 select-none">{log.step} →</span>
      )}
      <span className={cn("break-words min-w-0", color)}>{log.message}</span>
      {log.data !== undefined && log.data !== null && (
        <details className="mt-0.5 w-full">
          <summary className="cursor-pointer text-muted-foreground/60 text-xs">data</summary>
          <pre className="mt-1 text-muted-foreground text-xs whitespace-pre-wrap overflow-auto">
            {JSON.stringify(log.data, null, 2)}
          </pre>
        </details>
      )}
    </div>
  );
}
