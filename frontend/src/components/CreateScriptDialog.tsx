"use client";
import { useState } from "react";
import { toast } from "sonner";
import { scripts } from "@/lib/api";
import type { ScriptSummary } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import { FileCode, MessageSquare, Type, Sparkles, Bot, Puzzle, Brain, Workflow, KeyRound, FileInput } from "lucide-react";
import { cn } from "@/lib/utils";

// ── Templates ──────────────────────────────────────────────────────────────────

interface Template {
  id: string;
  label: string;
  description: string;
  icon: React.ReactNode;
  entryFunction: string;
  mainPy: string | null;   // null → use backend default
}

const TEMPLATES: Template[] = [
  {
    id: "blank",
    label: "Blank",
    description: "Empty run() starter",
    icon: <FileCode className="h-4 w-4" />,
    entryFunction: "run",
    mainPy: null,
  },
  {
    id: "simple-chat",
    label: "Simple Chat",
    description: "Minimal multi-turn chat for the Chat page",
    icon: <MessageSquare className="h-4 w-4" />,
    entryFunction: "run",
    mainPy:
`from agentflow import get_agent


def run(input: dict) -> dict:
    """Minimal multi-turn chat. Wire this script to the Chat page (/converse)."""
    message = input.get("message", "")
    history = input.get("history", [])

    agent = get_agent(
        system_prompt="You are a helpful assistant.",
        reasoning=input.get("reasoning"),   # conversation "Think" level (off/low/medium/high)
    )

    messages = [
        ("human" if m["role"] == "user" else "ai", m["content"])
        for m in history
    ]
    messages.append(("human", message))

    result = agent.invoke({"messages": messages})
    return {"reply": result["messages"][-1].content}
`,
  },
  {
    id: "streaming-chat",
    label: "Streaming Chat",
    description: "Streaming LLM, typewriter output, reasoning-aware",
    icon: <Type className="h-4 w-4" />,
    entryFunction: "run",
    mainPy:
`"""Streaming chat - direct LLM, typewriter output, with reasoning support.

token() streams each chunk to the Chat page in real time. The conversation's
"Think" level arrives as input["reasoning"] (off/low/medium/high) and is passed
to get_llm so the model reasons. Reasoning that comes back separately in
additional_kwargs["reasoning_content"] (e.g. DeepSeek official) is re-emitted as
<think>...</think> so the UI shows a collapsible "thought process"; it is kept
out of the returned reply. Use this over Simple Chat when you want streaming."""
from agentflow import token, get_llm


async def run(input: dict) -> dict:
    llm = get_llm(reasoning=input.get("reasoning"))
    history = input.get("history", [])

    messages = (
        [("system", "You are a helpful assistant.")]
        + [(m["role"], m["content"]) for m in history]
        + [("human", input["message"])]
    )

    full_reply = ""
    in_think = False
    async for chunk in llm.astream(messages):
        # Reasoning models may stream chain-of-thought separately; wrap it in
        # <think> for the UI, and keep it OUT of full_reply so it isn't persisted
        # or fed back into history.
        rc = (getattr(chunk, "additional_kwargs", None) or {}).get("reasoning_content")
        if rc:
            if not in_think:
                token("<think>")
                in_think = True
            token(rc)
        if chunk.content:
            if in_think:
                token("</think>")
                in_think = False
            token(chunk.content)
            full_reply += chunk.content
    if in_think:
        token("</think>")

    return {"reply": full_reply}
`,
  },
  {
    id: "rich-chat",
    label: "Rich Chat",
    description: "LLM tool-calls to render markdown / table / chart / image",
    icon: <Sparkles className="h-4 w-4" />,
    entryFunction: "run",
    mainPy:
`"""Chat where the LLM decides which artifact to render, via tool-calling.

Each @tool wraps an agentflow artifact emitter (markdown / table / image /
html / mermaid). The agent picks the right one from the user's request; its
text reply streams token-by-token next to the rendered card in the Artifacts
tab. Needs a tool-calling model (GPT-4o-mini / Claude Haiku / DeepSeek-V3)."""
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, AIMessage
from agentflow import token, log, get_agent, get_llm
from agentflow import (
    markdown as _markdown,
    image as _image,
    table as _table,
    html as _html,
    mermaid as _mermaid,
)


@tool
def show_markdown(content: str, title: str = "") -> str:
    """Render a markdown card: prose, lists, GFM tables, code blocks, links."""
    _markdown(content, title=title or None)
    return f"rendered markdown ({len(content)} chars)"


@tool
def show_table(rows: list[dict], title: str = "") -> str:
    """Render a data table. rows is a list of dicts; keys become the columns."""
    _table(rows, title=title or None)
    return f"rendered table ({len(rows)} rows)"


@tool
def show_image(url: str, alt: str = "", title: str = "") -> str:
    """Render an image from a public http(s) URL. No real URL? Use
    https://placehold.co/300x150/png?text=hello"""
    _image(url, alt=alt, title=title or None)
    return "rendered image"


@tool
def show_html(html_snippet: str, title: str = "") -> str:
    """Render an HTML snippet in a sandboxed iframe. Inline CSS only, no scripts."""
    _html(html_snippet, title=title or None)
    return "rendered html"


@tool
def show_mermaid(diagram: str, title: str = "") -> str:
    """Render a Mermaid diagram (flowchart / sequence / state / class / ER).
    Pass only the diagram source, without any surrounding code fence."""
    _mermaid(diagram, title=title or None)
    return "rendered mermaid"


TOOLS = [show_markdown, show_table, show_image, show_html, show_mermaid]

SYSTEM_PROMPT = (
    "You are a chat assistant that can render rich artifacts. When the user asks "
    "to see / show / draw / render / visualise something, call the matching tool "
    "(prefer show_mermaid for any flow / sequence / architecture diagram), then "
    "ALSO write a short 1-2 sentence reply. Invent plausible sample data when the "
    "user is only exploring. For plain conversation, don't call any tool."
)


async def run(input: dict) -> dict:
    message = (input.get("message") or "").strip()
    history = input.get("history") or []

    if get_llm() is None:
        token("No default LLM configured. Add one in Settings first.")
        return {"reply": "No default LLM configured."}

    agent = get_agent(system_prompt=SYSTEM_PROMPT, tools=TOOLS, reasoning=input.get("reasoning"))

    # /converse passes prior turns in input.history.
    msgs = []
    for m in history:
        if m.get("role") == "user":
            msgs.append(HumanMessage(m.get("content") or ""))
        elif m.get("role") == "assistant" and m.get("content"):
            msgs.append(AIMessage(m["content"]))
    msgs.append(HumanMessage(message))

    # Stream only the agent's own text (skip token streams from tool nodes).
    reply = ""
    async for chunk, meta in agent.astream({"messages": msgs}, stream_mode="messages"):
        if meta.get("langgraph_node") != "agent":
            continue
        text = getattr(chunk, "content", None)
        if text and isinstance(text, str):
            token(text)
            reply += text

    log("turn done", data={"reply_chars": len(reply)})
    return {"reply": reply}
`,
  },
  {
    id: "react-agent",
    label: "ReAct Agent",
    description: "get_agent with web_search + web_fetch",
    icon: <Bot className="h-4 w-4" />,
    entryFunction: "run",
    mainPy:
`from agentflow import get_agent, log


def run(input: dict) -> dict:
    """ReAct agent that can search the web and read pages (web_search / web_fetch)."""
    question = input.get("question") or input.get("message", "What is LangGraph?")
    log(f"Researching: {question}", step="start")

    agent = get_agent(
        system_prompt=(
            "You are a research assistant. Use web_search for current facts and "
            "web_fetch to read specific pages. Cite the sources you used."
        ),
    )
    result = agent.invoke({"messages": [("human", question)]})
    answer = result["messages"][-1].content

    log(f"Agent messages: {len(result['messages'])}", step="done")
    return {"question": question, "answer": answer}
`,
  },
  {
    id: "skills-mcp",
    label: "Skills + MCP",
    description: "Use bound skills and MCP server tools",
    icon: <Puzzle className="h-4 w-4" />,
    entryFunction: "run",
    mainPy:
`from agentflow import get_agent, get_tools, list_skills, log


def run(input: dict) -> dict:
    """Use skills + MCP tools. Bind them in the script's right-hand panel first:
    tick the MCP servers (mcp_server_ids) and skills (skill_ids)."""
    message = input.get("message", "Introduce the tools and skills you have.")

    # Introspect what this run has access to.
    skills = list_skills()
    log(f"Bound skills: {[s['name'] for s in skills]}", step="skills")

    tools = get_tools()  # built-ins + tools from the MCP servers ticked for this script
    # tools = get_tools(servers=["my-server"])  # or filter to one MCP server by name
    log(f"Available tools: {[t.name for t in tools]}", step="tools")

    # get_agent() auto-loads those tools, and for each bound skill it adds the
    # skill's name + description to the prompt plus a read_skill(name) tool.
    agent = get_agent(
        system_prompt="Use the available MCP tools and skills to help the user.",
    )
    result = agent.invoke({"messages": [("human", message)]})
    return {"reply": result["messages"][-1].content}
`,
  },
  {
    id: "deep-agent",
    label: "Deep Agent",
    description: "get_deep_agent: planning, sub-agents, skill filesystem",
    icon: <Brain className="h-4 w-4" />,
    entryFunction: "run",
    mainPy:
`from agentflow import get_deep_agent, log


async def run(input: dict) -> dict:
    """Deep Agent: built-in planning + sub-agents, and it mounts each bound skill
    as a browsable filesystem (reads every skill file, not just SKILL.md).
    Needs the deepagents package (already in the baseline venv)."""
    message = input.get("message", "")
    log("Building deep agent", step="init")

    agent = get_deep_agent(
        system_prompt="You are a capable assistant. Plan first, then use the mounted skills.",
    )
    result = await agent.ainvoke({"messages": [("human", message)]})
    return {"reply": result["messages"][-1].content}
`,
  },
  {
    id: "graph-loop",
    label: "LangGraph Loop",
    description: "Multi-node graph with a cycle + conditional edge",
    icon: <Workflow className="h-4 w-4" />,
    entryFunction: "run",
    mainPy:
`"""
Multi-node LangGraph demo.

Graph topology:
   START -> planner -> researcher -> (count < max?) --no--> summarizer -> END
                         ^                   |
                         +------- yes -------+

Loop is controlled purely by an iteration counter (no LLM-judge node), so the
number of rounds is deterministic and easy to reason about.
"""
from typing import TypedDict, Literal
from langgraph.graph import StateGraph, START, END
from agentflow import log, get_llm


class State(TypedDict):
    topic: str
    notes: list[str]
    iterations: int
    summary: str
    max_rounds: int


def planner(state: State) -> dict:
    log(f"Planning research on: {state['topic']} (max {state['max_rounds']} rounds)", step="planner")
    return {"notes": [], "iterations": 0}


def researcher(state: State) -> dict:
    """Ask the LLM for one new fact each loop."""
    llm = get_llm()
    prior = "\\n".join(f"- {n}" for n in state["notes"]) or "(none yet)"
    fact = llm.invoke(
        f"Topic: {state['topic']}\\n"
        f"Existing notes:\\n{prior}\\n\\n"
        "Give ONE concise new fact (one sentence) not already covered."
    ).content.strip()
    iteration = state["iterations"] + 1
    log(f"Round {iteration}: {fact[:80]}", step="researcher")
    return {"notes": state["notes"] + [fact], "iterations": iteration}


def summarizer(state: State) -> dict:
    llm = get_llm()
    notes = "\\n".join(f"- {n}" for n in state["notes"])
    summary = llm.invoke(
        f"Write a 3-sentence summary of {state['topic']} based on:\\n{notes}"
    ).content.strip()
    log("Summary ready", step="summarizer")
    return {"summary": summary}


def route(state: State) -> Literal["researcher", "summarizer"]:
    """Loop while we still have rounds left; otherwise finish."""
    if state["iterations"] >= state["max_rounds"]:
        return "summarizer"
    return "researcher"


def _build_graph():
    g = StateGraph(State)
    g.add_node("planner", planner)
    g.add_node("researcher", researcher)
    g.add_node("summarizer", summarizer)
    g.add_edge(START, "planner")
    g.add_edge("planner", "researcher")
    g.add_conditional_edges("researcher", route, {
        "researcher": "researcher",
        "summarizer": "summarizer",
    })
    g.add_edge("summarizer", END)
    return g.compile()


def run(input: dict) -> dict:
    app = _build_graph()
    result = app.invoke({
        "topic":      input.get("topic", "the LangGraph framework"),
        "max_rounds": input.get("max_rounds", 3),
    })
    return {
        "topic":      result["topic"],
        "summary":    result["summary"],
        "iterations": result["iterations"],
        "notes":      result["notes"],
    }
`,
  },
  {
    id: "secrets-http",
    label: "Secrets + HTTP",
    description: "Read a secret and call an external API",
    icon: <KeyRound className="h-4 w-4" />,
    entryFunction: "run",
    mainPy:
`from agentflow import get_secret, http_post, log


def run(input: dict) -> dict:
    """Call an external API using a secret. Add a secret named WEBHOOK_URL on the
    /secrets page (values are never hard-coded in the script)."""
    url = get_secret("WEBHOOK_URL")
    if not url:
        return {"error": "Create a secret named WEBHOOK_URL on the /secrets page first."}

    text = input.get("text", "Hello from AgentFlow!")

    # http_get / http_post / http_request are thin httpx wrappers (default timeout,
    # follow-redirects, raise_for_status) that return the httpx.Response.
    resp = http_post(url, json={"content": text})
    log(f"Posted, HTTP {resp.status_code}", step="done")
    return {"ok": True, "status": resp.status_code}
`,
  },
  {
    id: "file-workspace",
    label: "File + Workspace",
    description: "Handle an uploaded file + persist state across runs",
    icon: <FileInput className="h-4 w-4" />,
    entryFunction: "run",
    mainPy:
`from agentflow import paths, log, markdown


def run(input: dict) -> dict:
    """Process an uploaded file and persist state across runs.

    Upload a file in the run panel, then reference it in the input JSON, e.g.
        {"file": {"$file": "<id>"}}
    It arrives here as an AgentFlowFile. paths.workspace survives between runs
    (paths.run_dir is wiped each run), so use it for caches / accumulated state.
    """
    # Persistent run counter kept in the shared workspace dir.
    counter = paths.workspace / "run_count.txt"
    count = int(counter.read_text()) + 1 if counter.exists() else 1
    counter.write_text(str(count))

    f = input.get("file")
    if f is None:
        log('No file. Add {"file": {"$file": "<id>"}} to the input JSON.', level="warning")
        return {"runs_so_far": count, "hint": "Upload a file and reference it to process it."}

    # AgentFlowFile: .name / .mime / .size / .path / .read_bytes() / .read_text()
    log(f"File: {f.name} ({f.size} bytes, {f.mime})", step="file")
    try:
        preview = f.read_text(errors="replace")[:300]
        log(f"Preview: {preview}", step="preview")
    except Exception:
        pass

    # Keep a copy in the workspace so it outlives this (ephemeral) run.
    (paths.workspace / f.name).write_bytes(f.read_bytes())

    markdown(
        f"### {f.name}\\n\\n"
        f"- size: {f.size} bytes\\n"
        f"- type: {f.mime}\\n"
        f"- this script has run {count} time(s)",
        title="File info",
    )
    return {"name": f.name, "size": f.size, "runs_so_far": count}
`,
  },
];

// ── Component ──────────────────────────────────────────────────────────────────

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (script: ScriptSummary) => void;
}

export default function CreateScriptDialog({ open, onOpenChange, onCreated }: Props) {
  const [name, setName]               = useState("");
  const [description, setDescription] = useState("");
  const [templateId, setTemplateId]   = useState("blank");
  const [nameEdited, setNameEdited]   = useState(false);   // true once the user hand-edits the name
  const [loading, setLoading]         = useState(false);

  function selectTemplate(t: Template) {
    setTemplateId(t.id);
    // Auto-fill the name from the template label until the user hand-edits it.
    // Re-fills on every switch, so picking a different template updates the name
    // too (blank has no label → clear it).
    if (!nameEdited) {
      setName(t.id === "blank" ? "" : t.label);
    }
  }

  function reset() {
    setName("");
    setDescription("");
    setTemplateId("blank");
    setNameEdited(false);
  }

  async function handleCreate() {
    if (!name.trim()) return toast.error("Name is required");
    setLoading(true);
    try {
      const tpl = TEMPLATES.find(t => t.id === templateId) ?? TEMPLATES[0];

      // 1. create the script (backend generates default main.py)
      const s = await scripts.create({
        name: name.trim(),
        description,
        entry_function: tpl.entryFunction,
      });

      // 2. overwrite main.py with template content if not blank
      if (tpl.mainPy) {
        await scripts.upsertFile(s.id, {
          filename: "main.py",
          content: tpl.mainPy,
          is_main: true,
        });
      }

      onCreated(s);
      reset();
      toast.success("Script created");
    } catch (e: unknown) {
      toast.error(String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(v) => { onOpenChange(v); if (!v) reset(); }}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>New Script</DialogTitle>
        </DialogHeader>

        <div className="space-y-5 py-1">
          {/* Template picker */}
          <div className="space-y-2">
            <Label className="text-xs text-muted-foreground uppercase tracking-wide">Template</Label>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
              {TEMPLATES.map(t => (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => selectTemplate(t)}
                  className={cn(
                    "flex flex-col items-start gap-1 rounded-lg border p-3 text-left transition-colors hover:bg-secondary/60",
                    templateId === t.id
                      ? "border-primary bg-primary/5"
                      : "border-border bg-secondary/20",
                  )}
                >
                  <span className={cn("text-muted-foreground", templateId === t.id && "text-primary")}>
                    {t.icon}
                  </span>
                  <span className="text-xs font-medium leading-tight">{t.label}</span>
                  <span className="text-[10px] text-muted-foreground leading-tight">{t.description}</span>
                </button>
              ))}
            </div>
          </div>

          {/* Name + description */}
          <div className="space-y-3">
            <div className="space-y-1.5">
              <Label>Name</Label>
              <Input
                value={name}
                onChange={(e) => { setName(e.target.value); setNameEdited(e.target.value.trim().length > 0); }}
                placeholder="My LangGraph Agent"
                onKeyDown={(e) => e.key === "Enter" && handleCreate()}
                autoFocus
              />
            </div>
            <div className="space-y-1.5">
              <Label>Description <span className="text-muted-foreground">(optional)</span></Label>
              <Input
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="What does this agent do?"
              />
            </div>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => { onOpenChange(false); reset(); }}>Cancel</Button>
          <Button onClick={handleCreate} disabled={loading}>
            {loading ? "Creating…" : "Create"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
