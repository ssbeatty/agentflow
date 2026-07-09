---
name: agentflow-scripting
description: Write, run and debug AgentFlow scripts (LangGraph/LangChain Python automations) through the AgentFlow MCP server. Use when the user asks to create or modify a script, agent, chat bot, or automation on their AgentFlow instance, or to debug a failing AgentFlow run.
---

# AgentFlow scripting

AgentFlow is a self-hosted platform that runs user-written Python scripts (usually
LangGraph/LangChain agents) in per-script isolated virtualenvs. You interact with it
through the `agentflow` MCP server: create scripts, edit their files, set up their
environment, run them, and read logs.

## The development loop

1. `get_platform_context` — see which LLM models, secrets, MCP servers and skills the
   instance offers. Do this once before writing code that references any of them.
2. `create_script` (or `list_scripts` + `get_script` to find an existing one).
3. `write_script_file` — upsert `main.py` (and any other files). The response includes
   syntax-lint issues; fix them before running.
4. If the script needs extra pip packages: `update_script(requirements=...)`, then
   `setup_script_env`. Also call `setup_script_env` once for any brand-new script —
   without a venv the run falls back to the backend interpreter, which lacks the
   LangChain stack. First-time setup installs the baseline packages and can take
   a few minutes; be patient, do not retry while it runs.
5. `run_script` with a test `input_data` — it blocks until the run finishes and
   returns `output_data`, `error`, and error logs (traceback) on failure.
6. On failure, read the traceback, fix the file, run again. `get_execution_logs`
   returns the full log stream of a past run if you need more context.

## Eval / regression (test a script's quality)

A script can have an **eval dataset** — a set of test cases (an input + assertions)
that grade its output into a pass/fail score, so you can tell whether a change
helped or regressed. Tools:

- `list_eval_cases(script_id)` — see the current dataset (returns each case's id).
- `add_eval_case(script_id, name, input_json, assertions)` — add one case.
- `update_eval_case(case_id, …)` / `delete_eval_case(case_id)` — edit or remove a
  case by id (from `list_eval_cases`).
  `input_json` is the input object; `assertions` is a list of checks, each
  `{"type": ..., "value": ..., "threshold"?: int}`:
  `contains` / `not_contains` (substring), `regex`, `equals` (exact), or `judge`
  (an LLM scores the output 0–10 against `value` as a criterion, passing at
  `>= threshold`, default 7).
- `run_eval(script_id)` — run every case through the engine, grade it, and return
  `passed`/`total` plus per-case detail (which assertion failed and why).

Typical loop: `add_eval_case` a few cases → `run_eval` → if it regresses, fix the
script and re-run. Users can also view/edit the dataset in the script's **Eval tab**.

## Script contract

- Entry point: `def run(input: dict) -> Any` (name configurable per script via
  `entry_function`). The return value must be JSON-serializable; it becomes the
  execution's `output_data`. `async def` entry points are supported.
- The subprocess cwd is an ephemeral per-run directory. `from agentflow import paths`:
  `paths.run_dir` (cwd, wiped between runs), `paths.workspace` (persists across runs
  of the script — caches, sqlite, indexes), `paths.script_dir` (source files).
- Scripts import the platform SDK with `from agentflow import ...` — it is injected
  via `sys.path`, never add `agentflow` to requirements.

### Declaring an input contract (`INPUT_SCHEMA`)

Give `run()`'s input a typed contract by defining a **module-level `INPUT_SCHEMA`**
— a JSON Schema `dict`. When present the platform (a) **validates input before
running** (a mismatch fails fast with a 422 / a `failed` run, never reaching your
code), (b) generates a **typed call example** on the /docs page, and (c) renders an
**auto form** on the run page. A script with no `INPUT_SCHEMA` accepts any dict
(legacy behaviour). The schema is derived from the code automatically on save
(and via the `sync_script_schema` MCP tool).

```python
INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "city": {"type": "string", "description": "City to look up"},
        "days": {"type": "integer", "default": 3, "minimum": 1},
        "units": {"type": "string", "enum": ["metric", "imperial"], "default": "metric"},
    },
    "required": ["city"],
}

def run(input: dict) -> dict:
    ...
```

Or reuse a Pydantic model (the platform imports the module to resolve it):

```python
from pydantic import BaseModel

class Input(BaseModel):
    city: str
    days: int = 3

INPUT_SCHEMA = Input.model_json_schema()

def run(input: dict) -> dict:
    data = Input(**input)     # validate + get typed access
    ...
```

For **chat scripts** the input shape is fixed (`{message, history}`) — don't add an
`INPUT_SCHEMA` there.

## SDK quick reference (`from agentflow import ...`)

LLMs (configured as channels by the platform admin; see `get_platform_context`):

```python
llm = get_llm()                     # the instance's default model
llm = get_llm("gpt-4o")             # by model id, case-insensitive (an
                                    # unconfigured id raises ValueError — check list_llms())
llm = get_llm(reasoning="medium")   # thinking mode: "off"|"low"|"medium"|"high"
llm = get_llm(reasoning="medium", stream_reasoning=True)  # + auto-stream the
                                    # chain-of-thought to the chat UI as <think>
models = list_llms()                # available model ids
```

Tools & agents:

```python
tools = get_tools()                 # built-in web_search + web_fetch + the MCP tools
                                    # selected for this script (script.mcp_server_ids)
agent = get_agent()                 # LangGraph ReAct agent over get_tools() + bound
                                    # skills (advertised in prompt, read via read_skill)
agent = get_agent(system_prompt="You are...", llm_name="default", reasoning="low")
agent = get_agent(reasoning="high", stream_reasoning=True)  # auto <think> in chat
result = agent.invoke({"messages": [("user", msg)]})
reply = result["messages"][-1].content

agent = get_deep_agent()            # opt-in deepagents Deep Agent: planning,
                                    # sub-agents, full skill-file browsing
llm = get_llm_with_tools()          # get_llm().bind_tools(get_tools())
```

Sandboxed execution (opt-in, never in default get_tools()):

```python
from agentflow import run_bash, run_python, bash_tool, python_tool, exec_tools
r = run_python("2**10")             # {"stdout","stderr","returncode","timed_out"}
agent = get_agent(tools=get_tools() + exec_tools())   # give the agent bash+python

# The sandbox cwd is an empty throwaway dir and AGENTFLOW_* env vars are
# scrubbed, so sandboxed code can't see the run's files by default. Opt in:
r = run_python("open('data.csv').read()", files={"data.csv": some_path})
r = run_bash("ls", cwd=os.environ["AGENTFLOW_WORKSPACE_DIR"])  # persistent dir
agent = get_agent(tools=get_tools()                            # agent works on
                  + exec_tools(cwd=os.environ["AGENTFLOW_WORKSPACE_DIR"]))  # workspace
```

Both tools reach the **per-script venv**: `run_python` runs under the venv python
(so `import numpy`/etc. work), and the venv's `bin`/`Scripts` dir is on the bash
`PATH` too, so `run_bash("python …")`, `run_bash("pip install …")` and venv
**console scripts** (e.g. a CLI a skill installs) resolve to the venv. Install a
skill's deps into the venv (add them to the script `requirements.txt`, or
`run_bash("pip install <pkg>")` once) before invoking its CLI.

> **Windows dev note:** on Windows the `bash` tool needs a real **Git bash**; if
> only WSL's `bash.exe` is present it runs in a separate Linux environment that
> can't see the Windows venv (its `python`/CLIs won't resolve). Prefer the
> `python` tool there, or test bash-driven CLIs in the Linux Docker image.

Secrets & HTTP (secrets are stored by the admin; list keys via `get_platform_context`):

```python
token = get_secret("MY_API_TOKEN")  # case-insensitive; None if missing
keys = list_secrets()
resp = http_get(url)                # thin httpx wrappers: timeout, redirects,
resp = http_post(url, json={...})   # raise_for_status; returns httpx.Response
```

Output & logging (all render in the AgentFlow UI and are persisted per run):

```python
log("step done", data={...})        # structured log line
token("partial text")               # stream a token to the chat UI
markdown("## report"); image(png_bytes); table(rows); mermaid("graph TD; a-->b")
```

Skills bound to the script (`script.skill_ids`):

```python
names = [s["name"] for s in list_skills()]
instructions = get_skill("pdf-tools")     # full SKILL.md text
folder = skill_path("pdf-tools")          # Path to the skill's files
```

## Reusable code modules (share code across scripts)

A **module** is reusable Python *code* other scripts import — think shared
helpers/clients, distinct from a skill (which shares prompt instructions). A
module is a script of `kind="module"`: it has files + a `requirements` list but
**no `run()` and no venv of its own**, and it never runs directly. A script opts
in (like skills/MCP) via its `module_ids`, then imports the module by its
**package name**:

```python
# module "Text Utilities", package name "textutils", file clean.py:
def strip_tags(html: str) -> str:
    ...

# a script that binds this module (Config panel → Resources → add the module):
from textutils import strip_tags       # from <module_package> import ...

def run(input: dict) -> dict:
    return {"clean": strip_tags(input["html"])}
```

- The module's files are materialized into the importing script's
  `script_dir/modules/<package>/` at run time and put on `sys.path` — no install,
  no copy-paste. Module code can `import agentflow` too.
- The module's **`requirements` are installed into the *importing* script's venv**
  (merged with that script's own). So after binding a module (or when its deps
  change), **re-run the importing script's env setup** (`setup_script_env`) to pull
  the new deps in.
- Modules are flat: a module can't itself bind other modules (v1).

## Chat scripts (the /converse page)

Input arrives as `{"message": str, "history": [{"role","content"}], "reasoning": str}`;
return `{"reply": str}`. Forward the reasoning level: `get_agent(reasoning=input.get("reasoning"))`.
Stream with `token(...)` for a live-typing UI.

**Reasoning / "thought process": do NOT handle it in your script.** Pass
`stream_reasoning=True` to `get_agent` / `get_llm` and the platform surfaces the
model's chain-of-thought (DeepSeek `reasoning_content`, Claude thinking, …) in the UI
as a collapsible `<think>` block, kept out of your returned `reply` automatically. Your
loop only ever streams the answer — never emit `<think>` tags or read
`reasoning_content` yourself (that's the error-prone path the flag exists to remove).

**Streaming an agent: use `stream_agent()`, do NOT hand-roll the loop.** When an
agent uses tools, `agent.stream(stream_mode="messages")` yields the **tool results**
(bash/CLI dumps, JSON, file contents) alongside the answer — emit those and they get
spliced into the chat bubble (e.g. a `python` tool's `56088` glued to the front of the
reply). The `meta.get("langgraph_node") == "agent"` filter people reach for only works
for `get_agent()` (its model node is `"agent"`); a **deep agent's node is `"model"`**,
so that filter silently breaks it. `stream_agent()` filters by **message type** (AI
only), so it is correct for both agent kinds and returns the full reply:

```python
from agentflow import get_agent, stream_agent

async def run(input: dict) -> dict:
    agent = get_agent(reasoning=input.get("reasoning"), stream_reasoning=True)
    # Threaded in /converse (see below): send only the new message.
    reply = await stream_agent(agent, [("human", input["message"])])
    return {"reply": reply}
```

Same call for `get_deep_agent()`. In a sync `def run`, use `stream_agent_sync(...)`.
A **direct** `get_llm().astream(...)` (no tools) has no tool messages, so streaming its
`chunk.content` is fine without `stream_agent`.

**Conversation memory is automatic — don't re-feed `history` to an agent.** In
/converse a conversation is a durable LangGraph **thread** (`thread_id` == the
conversation id). `get_agent()` / `get_deep_agent()` auto-attach a per-conversation
checkpointer (persisted to `workspace/threads.db`), so the agent's full state —
**including a bound skill's body once it's been read, and every tool result** —
persists across turns. Consequences:
- **A bound skill is read ONCE, not every turn** (the original reason this exists).
- **Send only the new message** to `stream_agent` — the checkpointer supplies prior
  turns. Prepending `input["history"]` still works (it's deduplicated), but it's
  redundant for an agent. A **non-agent** chat (driving `get_llm()` directly) can't
  use the thread, so it still builds context from `input["history"]`.
- Old context is bounded automatically (recent-token window, system prompt always
  kept). Deleting the last turn in the UI rolls the thread back to the previous
  turn. Pass `get_agent(checkpointer=False)` to opt out (classic stateless agent).

## Gotchas

- A script only sees MCP tools whose server ids are in its `mcp_server_ids`,
  skills whose directory names are in `skill_ids`, and code modules whose ids are
  in `module_ids` — set them with `update_script`. A bound module's dependencies
  install into THIS script's venv, so re-run `setup_script_env` after binding one.
- Baseline venv packages: langchain-core, langchain-openai, langchain-deepseek,
  langgraph, httpx, ddgs, beautifulsoup4, langchain-mcp-adapters, nest-asyncio,
  deepagents. Anything else goes in `requirements` + `setup_script_env`.
- `run_script` has a timeout (default 300s) — pass a larger one for long jobs.
- File inputs: upload via `POST /api/files/upload` (admin), then reference anywhere
  in `input_data` as `{"$file": "<id>"}`; the script receives an `AgentFlowFile`
  (`.name/.mime/.size/.path/.read_text()/.read_bytes()/.open()`).
- Sync `agent.invoke()` works even with async MCP tools (the platform applies
  nest_asyncio and wraps async-only tools); plain `asyncio.run(...)` inside a sync
  entry also works.
- Returned values must be JSON-serializable — convert DataFrames/objects yourself.
