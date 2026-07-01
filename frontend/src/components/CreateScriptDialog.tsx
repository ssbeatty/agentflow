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
import { FileCode, MessageSquare, Sparkles, Bot, Puzzle, Brain, Workflow, KeyRound } from "lucide-react";
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

    agent = get_agent(system_prompt="You are a helpful assistant.")

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
    id: "rich-chat",
    label: "Rich Chat",
    description: "Streaming reply + Artifacts (md / table / chart / image)",
    icon: <Sparkles className="h-4 w-4" />,
    entryFunction: "run",
    mainPy:
`from agentflow import get_llm, token, markdown, table, mermaid, image, log


def run(input: dict) -> dict:
    """Streaming chat that also renders rich blocks in the Artifacts tab."""
    message = input.get("message", "")
    history = input.get("history", [])

    llm = get_llm()
    messages = [
        ("human" if m["role"] == "user" else "ai", m["content"])
        for m in history
    ]
    messages.append(("human", message))

    # Stream the answer token-by-token (typewriter effect on the Chat page).
    reply = ""
    for chunk in llm.stream(messages):
        if chunk.content:
            token(chunk.content)
            reply += chunk.content

    # Everything below renders in the "Artifacts" tab, independent of \`reply\`.
    markdown(
        "### Recap\\n"
        f"You asked: **{message}**\\n\\n"
        f"The reply is {len(reply)} characters long.",
        title="Summary",
    )
    table(
        [{"metric": "reply_chars", "value": len(reply)},
         {"metric": "turns", "value": len(history) + 1}],
        title="Stats",
    )
    mermaid(
        """
        flowchart LR
            U[User] --> A[LLM] --> R[Reply]
        """.strip(),
        title="Flow",
    )
    # image() accepts a URL, a file path, or raw bytes. Here we build an SVG
    # in-memory; it is saved under the run's _artifacts dir and served back.
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="260" height="60">'
        '<rect width="260" height="60" rx="8" fill="#4f46e5"/>'
        f'<text x="16" y="38" fill="white" font-size="20">{len(reply)} chars</text>'
        '</svg>'
    )
    image(svg.encode(), mime="image/svg+xml", alt="reply size", title="Generated SVG")

    log("Artifacts emitted", step="done")
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
  const [loading, setLoading]         = useState(false);

  function selectTemplate(t: Template) {
    setTemplateId(t.id);
    if (!name.trim() && t.id !== "blank") {
      setName(t.label);
    }
  }

  function reset() {
    setName("");
    setDescription("");
    setTemplateId("blank");
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
                onChange={(e) => setName(e.target.value)}
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
