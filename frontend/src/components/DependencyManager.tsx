"use client";
import { useState, useRef } from "react";
import { toast } from "sonner";
import { Download, RefreshCw, CheckCircle2, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";

interface Props {
  scriptId: string;
  requirements: string;
  onRequirementsChange: (v: string) => void;
}

type InstallState = "idle" | "working" | "done" | "error";

export default function DependencyManager({ scriptId, requirements, onRequirementsChange }: Props) {
  const [state, setState] = useState<InstallState>("idle");
  const [lines, setLines] = useState<string[]>([]);
  const logsRef = useRef<HTMLDivElement>(null);

  async function stream(endpoint: "venv" | "install") {
    setState("working");
    setLines([]);
    try {
      const res = await fetch(`/api/scripts/${scriptId}/${endpoint}`, { method: "POST" });
      if (!res.ok) {
        const msg = await res.text();
        throw new Error(msg);
      }
      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let buf = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const parts = buf.split("\n");
        buf = parts.pop() ?? "";
        for (const line of parts) {
          if (!line) continue;
          setLines((p) => [...p, line]);
          if (logsRef.current) {
            logsRef.current.scrollTop = logsRef.current.scrollHeight;
          }
          if (line.startsWith("ERROR:")) {
            setState("error");
            toast.error(line);
            return;
          }
          if (line === "DONE") {
            setState("done");
            toast.success(endpoint === "venv" ? "Venv created" : "Packages installed");
            return;
          }
        }
      }
      setState("done");
    } catch (e: unknown) {
      setState("error");
      toast.error(String(e));
    }
  }

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center gap-2 px-3 py-2 border-b border-border shrink-0">
        <Button
          variant="outline"
          size="sm"
          className="h-7 text-xs gap-1.5"
          onClick={() => stream("venv")}
          disabled={state === "working"}
        >
          <RefreshCw className={`h-3 w-3 ${state === "working" ? "animate-spin" : ""}`} />
          Create venv
        </Button>
        <Button
          variant="outline"
          size="sm"
          className="h-7 text-xs gap-1.5"
          onClick={() => stream("install")}
          disabled={state === "working"}
        >
          <Download className="h-3 w-3" />
          Install
        </Button>
        {state === "done" && <CheckCircle2 className="h-4 w-4 text-emerald-400" />}
        {state === "error" && <XCircle className="h-4 w-4 text-destructive" />}
      </div>

      <div className="flex flex-1 min-h-0 overflow-hidden">
        {/* requirements.txt editor */}
        <div className="flex-1 min-w-0">
          <textarea
            value={requirements}
            onChange={(e) => onRequirementsChange(e.target.value)}
            className="h-full w-full bg-transparent px-3 py-2 text-xs font-mono text-foreground resize-none focus:outline-none placeholder:text-muted-foreground"
            placeholder={"langgraph\nlangchain-openai\n# add packages..."}
            spellCheck={false}
          />
        </div>

        {/* install output */}
        {lines.length > 0 && (
          <div className="w-52 border-l border-border shrink-0">
            <ScrollArea className="h-full">
              <div ref={logsRef} className="p-2 font-mono text-xs space-y-0.5">
                {lines.map((l, i) => (
                  <div
                    key={i}
                    className={
                      l.startsWith("ERROR") ? "text-red-400" :
                      l === "DONE" ? "text-emerald-400" :
                      "text-muted-foreground"
                    }
                  >
                    {l}
                  </div>
                ))}
              </div>
            </ScrollArea>
          </div>
        )}
      </div>
    </div>
  );
}
