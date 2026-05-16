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
  const hasData = log.data !== undefined && log.data !== null;

  return (
    <div className="py-0.5 px-1 rounded hover:bg-accent/20">
      {/* meta row */}
      <div className="flex items-center gap-2 text-[10px] leading-none">
        <span className="text-muted-foreground/50 select-none tabular-nums">{time}</span>
        <span className={cn("select-none font-semibold", color)}>[{tag}]</span>
        {log.step && (
          <span className="text-muted-foreground/60 select-none">{log.step}</span>
        )}
      </div>
      {/* message row */}
      <div className={cn("text-xs break-words pl-[2px]", color)}>{log.message}</div>
      {hasData && (
        <details className="mt-0.5 pl-[2px]">
          <summary className="cursor-pointer text-muted-foreground/60 text-[10px]">data</summary>
          <pre className="mt-1 text-muted-foreground text-xs whitespace-pre-wrap break-words overflow-auto bg-secondary/30 rounded px-2 py-1">
            {JSON.stringify(log.data, null, 2)}
          </pre>
        </details>
      )}
    </div>
  );
}
