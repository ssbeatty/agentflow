"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, BookOpen, Check, Copy } from "lucide-react";
import { toast } from "sonner";
import { scripts as scriptsApi } from "@/lib/api";
import type { ScriptSummary } from "@/lib/types";
import { Button } from "@/components/ui/button";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";

export default function DocsPage() {
  const [items, setItems] = useState<ScriptSummary[]>([]);
  const [scriptId, setScriptId] = useState<string>("<SCRIPT_ID>");
  const [origin, setOrigin] = useState("http://localhost:8000");

  useEffect(() => {
    setOrigin(window.location.origin);
    scriptsApi.list().then((list) => {
      setItems(list);
      if (list.length > 0) setScriptId(list[0].id);
    }).catch(() => null);
  }, []);

  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-border px-4 py-2.5 flex items-center gap-3 shrink-0">
        <Link href="/">
          <Button variant="ghost" size="icon" className="h-8 w-8">
            <ArrowLeft className="h-4 w-4" />
          </Button>
        </Link>
        <BookOpen className="h-4 w-4 text-primary" />
        <span className="text-sm font-medium">API Reference</span>

        <div className="ml-auto flex items-center gap-2">
          <span className="text-xs text-muted-foreground">Examples for:</span>
          <Select value={scriptId} onValueChange={setScriptId}>
            <SelectTrigger className="h-8 w-56 text-xs">
              <SelectValue placeholder="Pick a script" />
            </SelectTrigger>
            <SelectContent>
              {items.map((s) => (
                <SelectItem key={s.id} value={s.id} className="text-xs">
                  {s.name}
                </SelectItem>
              ))}
              {items.length === 0 && (
                <div className="px-2 py-1 text-xs text-muted-foreground">No scripts yet</div>
              )}
            </SelectContent>
          </Select>
        </div>
      </header>

      <main className="flex-1 max-w-4xl mx-auto w-full px-6 py-8 space-y-10">
        <Intro origin={origin} />

        <Section
          title="Run synchronously"
          desc="Blocks until the script finishes and returns the final output_data. Best for external service-to-service calls."
        >
          <Endpoint method="POST" path="/api/executions/run?timeout=120" />
          <Code
            label="curl"
            code={`curl -X POST '${origin}/api/executions/run?timeout=120' \\
  -H 'Content-Type: application/json' \\
  -d '{
    "script_id": "${scriptId}",
    "input_data": {"message": "hello"}
  }'`}
          />
          <Code
            label="response"
            code={`{
  "id": "uuid…",
  "status": "completed",         // or "failed" / "cancelled"
  "output_data": { ... },         // whatever the script returned
  "error": null,
  "started_at": "...",
  "finished_at": "..."
}`}
          />
        </Section>

        <Section
          title="Upload a file"
          desc="Upload arbitrary binaries (PDFs, CSVs, images, etc.) that scripts can read by reference. Files persist until you delete them. Optionally tag with script_id for filtering."
        >
          <Endpoint method="POST" path="/api/files/upload" />
          <Code
            label="curl"
            code={`# upload + tag to a script (script_id is optional)
curl -X POST ${origin}/api/files/upload \\
  -F 'file=@./report.pdf' \\
  -F 'script_id=${scriptId}'

# → {"id":"<FILE_ID>","original_name":"report.pdf","mime":"application/pdf","size":12345,...}`}
          />
        </Section>

        <Section
          title="Run a script with file input"
          desc='Pass a file reference anywhere in input_data using the marker {"$file": "<FILE_ID>"}. The execution engine resolves it before launch; your script receives an AgentFlowFile object in its place. Markers can be nested in objects / arrays.'
        >
          <Endpoint method="POST" path="/api/executions/run" />
          <Code
            label="curl"
            code={`curl -X POST ${origin}/api/executions/run \\
  -H 'Content-Type: application/json' \\
  -d '{
    "script_id": "${scriptId}",
    "input_data": {
      "doc":   {"$file": "<FILE_ID>"},
      "extras": [{"$file": "<FILE_ID_2>"}, {"$file": "<FILE_ID_3>"}],
      "query": "summarise the doc"
    }
  }'`}
          />
          <Code
            label="python (script side)"
            code={`from agentflow import paths, AgentFlowFile

def run(input):
    doc: AgentFlowFile = input["doc"]
    text = doc.read_text()                   # or .read_bytes() / .open("rb")
    print(doc.name, doc.mime, doc.size)

    # Persistent cache shared across runs of this script:
    (paths.workspace / "index.json").write_text("...")

    # Per-execution scratch dir (cwd; isolated between runs, auto-pruned):
    open("scratch.txt", "w").write("...")

    return {"reply": text[:200]}`}
          />
        </Section>

        <Section
          title="List / delete files"
          desc="Filter by script_id to show files tagged to a script plus untagged globals."
        >
          <Endpoint method="GET" path="/api/files?script_id=..." />
          <Endpoint method="GET" path="/api/files/{file_id}" />
          <Endpoint method="GET" path="/api/files/{file_id}/meta" />
          <Endpoint method="DELETE" path="/api/files/{file_id}" />
          <Code
            label="curl"
            code={`curl '${origin}/api/files?script_id=${scriptId}'
curl ${origin}/api/files/<FILE_ID> -o downloaded.bin
curl -X DELETE ${origin}/api/files/<FILE_ID>`}
          />
        </Section>

        <Section
          title="Run asynchronously"
          desc="Returns immediately with an execution id; poll GET /executions/{id} or subscribe via WebSocket for logs. Better for long jobs and fan-out."
        >
          <Endpoint method="POST" path="/api/executions" />
          <Code
            label="curl"
            code={`curl -X POST ${origin}/api/executions \\
  -H 'Content-Type: application/json' \\
  -d '{"script_id":"${scriptId}","input_data":{}}'

# → {"id":"<EXECUTION_ID>","status":"pending",...}

# poll
curl ${origin}/api/executions/<EXECUTION_ID>

# live logs (WebSocket)
# ws://${origin.replace(/^https?:\/\//, "")}/ws/executions/<EXECUTION_ID>`}
          />
        </Section>

        <Section
          title="Stop a running execution"
          desc="Force-stops the subprocess and marks the execution as cancelled. Always returns 200."
        >
          <Endpoint method="POST" path="/api/executions/{id}/stop" />
          <Code
            label="curl"
            code={`curl -X POST ${origin}/api/executions/<EXECUTION_ID>/stop
# → {"stopped": true, "status": "cancelled"}`}
          />
        </Section>

        <Section
          title="List executions"
          desc="Optionally filtered by script_id. Newest first."
        >
          <Endpoint method="GET" path="/api/executions?script_id=...&limit=50" />
          <Code
            label="curl"
            code={`curl '${origin}/api/executions?script_id=${scriptId}&limit=20'`}
          />
        </Section>

        <Section
          title="Python example"
          desc="Anything that speaks HTTP works. Here's a minimal chat loop hitting /executions/run with client-side history."
        >
          <Code
            label="python"
            code={`import requests

SCRIPT_ID = "${scriptId}"
BASE = "${origin}"

history = []
while True:
    msg = input("You: ").strip()
    if not msg: break
    r = requests.post(
        f"{BASE}/api/executions/run",
        params={"timeout": 120},
        json={"script_id": SCRIPT_ID, "input_data": {"message": msg, "history": history}},
        timeout=130,
    ).json()
    if r["status"] != "completed":
        print("ERR:", r.get("error"))
        break
    reply = r["output_data"].get("reply", str(r["output_data"]))
    print("Bot:", reply)
    history.append({"role": "user", "content": msg})
    history.append({"role": "assistant", "content": reply})`}
          />
        </Section>

        <Section
          title="Script contract"
          desc="What the platform passes in and expects back."
        >
          <ul className="text-sm space-y-2 text-muted-foreground list-disc pl-5">
            <li>
              <b className="text-foreground">Entry function</b>: receives one dict argument
              (whatever you put in <code className="text-foreground">input_data</code>) and returns any
              JSON-serialisable value.
            </li>
            <li>
              <b className="text-foreground">Conventions for the /converse chat page</b>: input has
              <code className="text-foreground"> {"{message, history}"}</code>; return
              <code className="text-foreground"> {"{reply}"}</code>. Other return shapes
              still work — the chat UI falls back to <code className="text-foreground">message</code> /
              <code className="text-foreground">response</code> / <code className="text-foreground">result</code>,
              and then to a JSON dump.
            </li>
            <li>
              <b className="text-foreground">LLMs</b>: <code className="text-foreground">get_llm()</code>
              returns the one with <code className="text-foreground">is_default=True</code>.
              <code className="text-foreground"> get_llm(&quot;name&quot;)</code> picks by config name (case insensitive).
              <code className="text-foreground"> list_llms()</code> enumerates available names.
            </li>
            <li>
              <b className="text-foreground">Logging</b>: use
              <code className="text-foreground"> from agentflow import log</code>. Structured logs go to the Logs panel
              and are persisted to the run history.
            </li>
            <li>
              <b className="text-foreground">File inputs</b>: upload via
              <code className="text-foreground"> /api/files/upload</code>, then reference in
              <code className="text-foreground"> input_data</code> as
              <code className="text-foreground"> {`{"$file": "<id>"}`}</code> at any depth.
              The script receives an <code className="text-foreground">AgentFlowFile</code> with
              <code className="text-foreground"> .name / .mime / .size / .path / .read_text() / .read_bytes() / .open()</code>.
            </li>
            <li>
              <b className="text-foreground">Working directories</b>: import
              <code className="text-foreground"> paths</code> from <code className="text-foreground">agentflow</code>.
              <code className="text-foreground"> paths.run_dir</code> is this run&apos;s cwd (fresh each run, auto-pruned);
              <code className="text-foreground"> paths.workspace</code> persists across runs of the same script
              (good for caches, vector indexes, sqlite files).
            </li>
          </ul>
        </Section>
      </main>
    </div>
  );
}

// ── helpers ─────────────────────────────────────────────────────────────────

function Intro({ origin }: { origin: string }) {
  return (
    <section>
      <h1 className="text-2xl font-semibold mb-2">API Reference</h1>
      <p className="text-sm text-muted-foreground">
        HTTP endpoints are served from
        <code className="font-mono text-foreground mx-1 px-1 py-0.5 rounded bg-secondary/40">{origin}</code>.
        Pick a script in the top-right to substitute its real id into the examples below.
      </p>
    </section>
  );
}

function Section({
  title, desc, children,
}: { title: string; desc?: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3">
      <div>
        <h2 className="text-lg font-medium">{title}</h2>
        {desc && <p className="text-xs text-muted-foreground mt-1">{desc}</p>}
      </div>
      {children}
    </section>
  );
}

function Endpoint({ method, path }: { method: string; path: string }) {
  const color = method === "GET" ? "text-emerald-400" : method === "POST" ? "text-blue-400" : "text-amber-400";
  return (
    <div className="flex items-center gap-2 text-xs font-mono">
      <span className={`font-semibold ${color}`}>{method}</span>
      <span className="text-foreground">{path}</span>
    </div>
  );
}

function Code({ label, code }: { label: string; code: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="rounded-lg border border-border bg-secondary/20 overflow-hidden">
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-border/60 text-[10px] uppercase tracking-wider text-muted-foreground">
        <span>{label}</span>
        <button
          onClick={() => {
            navigator.clipboard.writeText(code);
            toast.success("Copied");
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          }}
          className="hover:text-foreground transition-colors flex items-center gap-1"
        >
          {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
          {copied ? "copied" : "copy"}
        </button>
      </div>
      <pre className="p-3 text-xs font-mono text-foreground overflow-x-auto whitespace-pre">{code}</pre>
    </div>
  );
}
