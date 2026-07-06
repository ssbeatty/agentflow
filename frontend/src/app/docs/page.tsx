"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, BookOpen, Check, Copy } from "lucide-react";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import { scripts as scriptsApi } from "@/lib/api";
import type { ScriptSummary } from "@/lib/types";
import { exampleForSchema } from "@/lib/schemaForm";
import { Button } from "@/components/ui/button";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";

export default function DocsPage() {
  const { t } = useTranslation("docs");
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

  // Typed call example: when the selected script declares an INPUT_SCHEMA, build
  // a representative input_data from it; else the generic {"message": "hello"}.
  const selected = items.find((s) => s.id === scriptId);
  const exampleInput = selected?.input_schema
    ? JSON.stringify(exampleForSchema(selected.input_schema))
    : '{"message": "hello"}';

  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-border px-4 py-2.5 flex items-center gap-3 shrink-0">
        <Link href="/">
          <Button variant="ghost" size="icon" className="h-8 w-8">
            <ArrowLeft className="h-4 w-4" />
          </Button>
        </Link>
        <BookOpen className="h-4 w-4 text-primary" />
        <span className="text-sm font-medium">{t("header.title")}</span>

        <div className="ml-auto flex items-center gap-2">
          <span className="text-xs text-muted-foreground">{t("header.examplesFor")}</span>
          <Select value={scriptId} onValueChange={setScriptId}>
            <SelectTrigger className="h-8 w-56 text-xs">
              <SelectValue placeholder={t("header.pickScriptPlaceholder")} />
            </SelectTrigger>
            <SelectContent>
              {items.map((s) => (
                <SelectItem key={s.id} value={s.id} className="text-xs">
                  {s.name}
                </SelectItem>
              ))}
              {items.length === 0 && (
                <div className="px-2 py-1 text-xs text-muted-foreground">{t("header.noScripts")}</div>
              )}
            </SelectContent>
          </Select>
        </div>
      </header>

      <main className="flex-1 max-w-4xl mx-auto w-full px-6 py-8 space-y-10">
        <Intro origin={origin} />

        <Section
          title={t("mcp.title")}
          desc={t("mcp.desc")}
        >
          <Endpoint method="POST" path="/mcp  (Streamable HTTP)" />
          <Code
            label={t("mcp.labelClaudeCode")}
            code={`claude mcp add --transport http agentflow ${origin}/mcp \\
  --header "X-API-Key: af_…"`}
          />
          <Code
            label={t("mcp.labelCursorJson")}
            code={`{
  "mcpServers": {
    "agentflow": {
      "url": "${origin}/mcp",
      "headers": { "X-API-Key": "af_…" }
    }
  }
}`}
          />
          <Code
            label={t("mcp.labelInstallSkill")}
            code={`mkdir -p ~/.claude/skills/agentflow-scripting
curl -s ${origin}/mcp/skill \\
  -o ~/.claude/skills/agentflow-scripting/SKILL.md`}
          />
          <p className="text-xs text-muted-foreground">
            {t("mcp.toolsExposedLabel")} <code className="text-foreground">get_platform_context</code>,{" "}
            <code className="text-foreground">get_scripting_guide</code>,{" "}
            <code className="text-foreground">list_scripts</code>,{" "}
            <code className="text-foreground">get_script</code>,{" "}
            <code className="text-foreground">create_script</code>,{" "}
            <code className="text-foreground">update_script</code>,{" "}
            <code className="text-foreground">read_script_file</code>,{" "}
            <code className="text-foreground">write_script_file</code>,{" "}
            <code className="text-foreground">delete_script_file</code>,{" "}
            <code className="text-foreground">setup_script_env</code>,{" "}
            <code className="text-foreground">run_script</code>,{" "}
            <code className="text-foreground">list_executions</code>,{" "}
            <code className="text-foreground">get_execution_logs</code>. {t("mcp.toolsExposedTrailing1")}{" "}
            <code className="text-foreground">get_scripting_guide</code>{t("mcp.toolsExposedTrailing2")}
          </p>
        </Section>

        <Section
          title={t("runSync.title")}
          desc={t("runSync.desc")}
        >
          <Endpoint method="POST" path="/api/executions/run?timeout=120" />
          <Code
            label="curl"
            code={`curl -X POST '${origin}/api/executions/run?timeout=120' \\
  -H 'Content-Type: application/json' \\
  -H 'X-API-Key: af_…' \\
  -d '{
    "script_id": "${scriptId}",
    "input_data": ${exampleInput}
  }'`}
          />
          {selected?.input_schema && (
            <Code
              label={t("runSync.labelInputSchema")}
              code={JSON.stringify(selected.input_schema, null, 2)}
            />
          )}
          <Code
            label={t("runSync.labelResponse")}
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
          title={t("uploadFile.title")}
          desc={t("uploadFile.desc")}
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
          title={t("runWithFile.title")}
          desc={t("runWithFile.desc")}
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
            label={t("runWithFile.labelPythonScriptSide")}
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
          title={t("listDeleteFiles.title")}
          desc={t("listDeleteFiles.desc")}
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
          title={t("runAsync.title")}
          desc={t("runAsync.desc")}
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

# live logs (WebSocket — sends the admin session cookie on same-origin)
# ${origin.replace(/^http/, "ws")}/ws/executions/<EXECUTION_ID>`}
          />
        </Section>

        <Section
          title={t("stopExecution.title")}
          desc={t("stopExecution.desc")}
        >
          <Endpoint method="POST" path="/api/executions/{id}/stop" />
          <Code
            label="curl"
            code={`curl -X POST ${origin}/api/executions/<EXECUTION_ID>/stop
# → {"stopped": true, "status": "cancelled"}`}
          />
        </Section>

        <Section
          title={t("listExecutions.title")}
          desc={t("listExecutions.desc")}
        >
          <Endpoint method="GET" path="/api/executions?script_id=...&limit=50" />
          <Code
            label="curl"
            code={`curl '${origin}/api/executions?script_id=${scriptId}&limit=20'`}
          />
        </Section>

        <Section
          title={t("pythonExample.title")}
          desc={t("pythonExample.desc")}
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
        headers={"X-API-Key": "af_…"},   # create on the /security page
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
          title={t("contract.title")}
          desc={t("contract.desc")}
        >
          <ul className="text-sm space-y-2 text-muted-foreground list-disc pl-5">
            <li>
              <b className="text-foreground">{t("contract.entryFunction.label")}</b>{t("contract.entryFunction.pre")}{" "}
              <code className="text-foreground">input_data</code>{t("contract.entryFunction.post")}
            </li>
            <li>
              <b className="text-foreground">{t("contract.converseConventions.label")}</b>{t("contract.converseConventions.t1")}
              <code className="text-foreground"> {"{message, history}"}</code>{t("contract.converseConventions.t2")}
              <code className="text-foreground"> {"{reply}"}</code>{t("contract.converseConventions.t3")}{" "}
              <code className="text-foreground">message</code> /{" "}
              <code className="text-foreground">response</code> / <code className="text-foreground">result</code>
              {t("contract.converseConventions.t4")}
            </li>
            <li>
              <b className="text-foreground">{t("contract.llms.label")}</b>{t("contract.llms.t1")}
              <code className="text-foreground"> get_llm()</code> {t("contract.llms.t2")}
              <code className="text-foreground"> get_llm(&quot;model-id&quot;)</code> {t("contract.llms.t3")}
              <code className="text-foreground"> list_llms()</code> {t("contract.llms.t4")}
            </li>
            <li>
              <b className="text-foreground">{t("contract.toolsAgents.label")}</b>{t("contract.toolsAgents.t1")}
              <code className="text-foreground"> get_tools()</code> {t("contract.toolsAgents.t2")}
              <code className="text-foreground"> web_search</code> /{" "}
              <code className="text-foreground"> web_fetch</code> {t("contract.toolsAgents.t3")}{" "}
              <code className="text-foreground">get_agent()</code> {t("contract.toolsAgents.t4")}
              <code className="text-foreground"> read_skill</code> {t("contract.toolsAgents.t5")}{" "}
              <code className="text-foreground">/tools</code> {t("contract.toolsAgents.t6")}
            </li>
            <li>
              <b className="text-foreground">{t("contract.logging.label")}</b>{t("contract.logging.t1")}
              <code className="text-foreground"> from agentflow import log</code>{t("contract.logging.t2")}
            </li>
            <li>
              <b className="text-foreground">{t("contract.secrets.label")}</b>{t("contract.secrets.t1")}
              <code className="text-foreground"> /secrets</code> {t("contract.secrets.t2")}
              <code className="text-foreground"> get_secret(&quot;BARK_KEY&quot;)</code> {t("contract.secrets.t3")}{" "}
              <code className="text-foreground"> list_secrets()</code> {t("contract.secrets.t4")}
            </li>
            <li>
              <b className="text-foreground">{t("contract.httpHelpers.label")}</b>{t("contract.httpHelpers.t1")}
              <code className="text-foreground"> http_get(url)</code> /{" "}
              <code className="text-foreground"> http_post(url, json=…)</code> /{" "}
              <code className="text-foreground"> http_request(method, url, …)</code> {t("contract.httpHelpers.t2")}
              <code className="text-foreground"> httpx</code> {t("contract.httpHelpers.t3")}
              <code className="text-foreground"> httpx.Response</code> {t("contract.httpHelpers.t4")}
              <code className="text-foreground"> json= / params= / headers= / auth=</code> {t("contract.httpHelpers.t5")}
            </li>
            <li>
              <b className="text-foreground">{t("contract.fileInputs.label")}</b>{t("contract.fileInputs.t1")}
              <code className="text-foreground"> /api/files/upload</code>{t("contract.fileInputs.t2")}
              <code className="text-foreground"> input_data</code> {t("contract.fileInputs.t3")}
              <code className="text-foreground"> {`{"$file": "<id>"}`}</code> {t("contract.fileInputs.t4")}{" "}
              <code className="text-foreground">AgentFlowFile</code> {t("contract.fileInputs.t5")}
              <code className="text-foreground"> .name / .mime / .size / .path / .read_text() / .read_bytes() / .open()</code>.
            </li>
            <li>
              <b className="text-foreground">{t("contract.workingDirs.label")}</b>{t("contract.workingDirs.t1")}
              <code className="text-foreground"> paths</code> {t("contract.workingDirs.t2")} <code className="text-foreground">agentflow</code>.
              <code className="text-foreground"> paths.run_dir</code> {t("contract.workingDirs.t3")}
              <code className="text-foreground"> paths.workspace</code> {t("contract.workingDirs.t4")}
            </li>
          </ul>
        </Section>
      </main>
    </div>
  );
}

// ── helpers ─────────────────────────────────────────────────────────────────

function Intro({ origin }: { origin: string }) {
  const { t } = useTranslation("docs");
  return (
    <section>
      <h1 className="text-2xl font-semibold mb-2">{t("intro.title")}</h1>
      <p className="text-sm text-muted-foreground">
        {t("intro.servedFrom")}
        <code className="font-mono text-foreground mx-1 px-1 py-0.5 rounded bg-secondary/40">{origin}</code>.
        {t("intro.pickScript")}
      </p>
      <p className="text-sm text-muted-foreground mt-3">
        <b className="text-foreground">{t("intro.authLabel")}</b> {t("intro.authText1")}
        <code className="font-mono text-foreground mx-1 px-1 py-0.5 rounded bg-secondary/40">Authorization: Bearer &lt;admin-token&gt;</code>.
        {t("intro.authText2")}
        <code className="font-mono text-foreground mx-1 px-1 py-0.5 rounded bg-secondary/40">POST /api/executions/run</code>,
        {t("intro.authText3")}
        <code className="font-mono text-foreground mx-1 px-1 py-0.5 rounded bg-secondary/40">X-API-Key: af_…</code> —
        {t("intro.authText4")}
        <code className="font-mono text-foreground mx-1 px-1 py-0.5 rounded bg-secondary/40">/security</code> {t("intro.pageSuffix")}
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
  const { t } = useTranslation("docs");
  const [copied, setCopied] = useState(false);
  return (
    <div className="rounded-lg border border-border bg-secondary/20 overflow-hidden">
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-border/60 text-[10px] uppercase tracking-wider text-muted-foreground">
        <span>{label}</span>
        <button
          onClick={() => {
            navigator.clipboard.writeText(code);
            toast.success(t("code.copied"));
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          }}
          className="hover:text-foreground transition-colors flex items-center gap-1"
        >
          {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
          {copied ? t("code.copiedLabel") : t("code.copyLabel")}
        </button>
      </div>
      <pre className="p-3 text-xs font-mono text-foreground overflow-x-auto whitespace-pre">{code}</pre>
    </div>
  );
}
