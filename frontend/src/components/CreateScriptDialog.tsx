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
import { FileCode, Search, Wrench, Globe, Zap, Workflow } from "lucide-react";
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
    description: "Basic run() starter",
    icon: <FileCode className="h-4 w-4" />,
    entryFunction: "run",
    mainPy: null,
  },
  {
    id: "search-agent",
    label: "Chat Agent",
    description: "Multi-turn chat with web search support",
    icon: <Search className="h-4 w-4" />,
    entryFunction: "run",
    mainPy:
`from agentflow import log, get_agent


def run(input: dict) -> dict:
    message = input.get("message", "")
    history = input.get("history", [])

    agent = get_agent(
        system_prompt=(
            "You are a helpful assistant. "
            "Use web_search to find current information and web_fetch to read specific pages."
        )
    )

    messages = [
        ("human" if m["role"] == "user" else "ai", m["content"])
        for m in history
    ]
    messages.append(("human", message))

    result = agent.invoke({"messages": messages})
    reply = result["messages"][-1].content

    log(f"Steps taken: {len(result['messages'])}", step="done")
    return {"reply": reply}
`,
  },
  {
    id: "tool-diagnostics",
    label: "Tool Diagnostics",
    description: "Verify built-in & MCP tools (no LLM needed)",
    icon: <Wrench className="h-4 w-4" />,
    entryFunction: "run",
    mainPy:
`from agentflow import log, get_tools


def run(input: dict) -> dict:
    """List available tools and run a quick smoke-test for each built-in."""
    tools = get_tools()
    names = [t.name for t in tools]
    log(f"Available tools: {names}", step="init")

    query = input.get("query", "LangGraph tutorial")
    search = next((t for t in tools if t.name == "web_search"), None)
    fetch  = next((t for t in tools if t.name == "web_fetch"),  None)

    results: dict = {"tools": names}

    if search:
        results["search_preview"] = search.invoke({"query": query, "max_results": 3})[:600]
        log("web_search OK", step="search")

    if fetch:
        results["fetch_preview"] = fetch.invoke({"url": "https://example.com"})[:300]
        log("web_fetch OK", step="fetch")

    return results
`,
  },
  {
    id: "webpage-summary",
    label: "Webpage Summary",
    description: "Fetch a URL and summarise with LLM",
    icon: <Globe className="h-4 w-4" />,
    entryFunction: "run",
    mainPy:
`from agentflow import log, get_agent


def run(input: dict) -> dict:
    url      = input.get("url", "https://example.com")
    question = input.get("question", "What is this page about?")

    log(f"Fetching: {url}", step="start")

    agent = get_agent(
        system_prompt="You are a concise summariser. Use web_fetch to read the given page."
    )
    result = agent.invoke({
        "messages": [("human", f"Fetch {url} and answer: {question}")]
    })

    answer = result["messages"][-1].content
    log("Done", step="done")
    return {"url": url, "question": question, "answer": answer}
`,
  },
  {
    id: "research-loop",
    label: "Research Loop",
    description: "Multi-node LangGraph with cycle + conditional edge",
    icon: <Workflow className="h-4 w-4" />,
    entryFunction: "run",
    mainPy:
`"""
Multi-node LangGraph demo.

Graph topology:
   START → planner → researcher → (count < max?) ──no──→ summarizer → END
                         ▲                   │
                         └────── yes ────────┘

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
    id: "async-agent",
    label: "Async Agent",
    description: "Async entry function with ainvoke",
    icon: <Zap className="h-4 w-4" />,
    entryFunction: "run",
    mainPy:
`from agentflow import log, get_agent


async def run(input: dict) -> dict:
    message = input.get("message", "")
    history = input.get("history", [])

    log("Starting async run", step="init")

    agent = get_agent()

    messages = [
        ("human" if m["role"] == "user" else "ai", m["content"])
        for m in history
    ]
    messages.append(("human", message))

    result = await agent.ainvoke({"messages": messages})
    reply = result["messages"][-1].content

    log(f"Steps: {len(result['messages'])}", step="done")
    return {"reply": reply}
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
