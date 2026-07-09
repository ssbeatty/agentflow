/**
 * Catalog of the built-in `agentflow` SDK surface, used to power in-editor code
 * hints (completion + hover) in the Monaco script editor. Scripts run in an
 * isolated venv with `agentflow` injected on sys.path, so the editor otherwise
 * has no way to know what the module exposes — this table is that knowledge.
 *
 * Source of truth: `backend/agentflow/__init__.py` +
 * `backend/assets/skills/agentflow-scripting/SKILL.md`. Keep this in sync when
 * the SDK's public functions / signatures change (it's a static mirror — there
 * is no runtime introspection).
 */

export type AgentflowSymbolKind = "function" | "class" | "variable";

export interface AgentflowSymbol {
  /** Bare name, e.g. `get_llm`. */
  name: string;
  kind: AgentflowSymbolKind;
  /** One-line Python signature, shown inline and in the hover code block. */
  signature: string;
  /** Markdown documentation shown in the completion details / hover card. */
  doc: string;
  /** Snippet inserted on accept (member/bare context). Defaults to `name`. */
  insert?: string;
  /** Short group label shown after the signature, e.g. "agents". */
  group: string;
}

export interface AgentflowSnippet {
  /** Trigger label, prefixed `af:` so it never fires on ordinary typing. */
  label: string;
  detail: string;
  doc: string;
  /** Snippet body with ${1:...} placeholders. */
  body: string;
}

export const AGENTFLOW_API: AgentflowSymbol[] = [
  // ── LLMs ────────────────────────────────────────────────────────────────
  {
    name: "get_llm",
    kind: "function",
    group: "llm",
    signature: 'get_llm(name="default", reasoning=None, stream_reasoning=False)',
    insert: "get_llm(${1})",
    doc: [
      "Return a LangChain chat model.",
      "",
      "- `get_llm()` — the instance's **default** model.",
      "- `get_llm(\"gpt-4o\")` — by model id (case-insensitive; unknown id raises `ValueError`, check `list_llms()`).",
      "- `reasoning=` — thinking mode: `\"off\"` | `\"low\"` | `\"medium\"` | `\"high\"`.",
      "- `stream_reasoning=True` — auto-stream the chain-of-thought to the chat UI as a `<think>` block (no think logic needed in your script).",
      "",
      "```python",
      "llm = get_llm(reasoning=\"medium\")",
      "resp = llm.invoke([(\"user\", \"hi\")])",
      "```",
    ].join("\n"),
  },
  {
    name: "list_llms",
    kind: "function",
    group: "llm",
    signature: "list_llms() -> list[str]",
    doc: "List the model ids configured on this instance (usable with `get_llm(id)`).",
  },
  {
    name: "get_llm_with_tools",
    kind: "function",
    group: "llm",
    signature: 'get_llm_with_tools(name="default", tools=None)',
    insert: "get_llm_with_tools(${1})",
    doc: "Shorthand for `get_llm().bind_tools(get_tools())`. Pass `tools=` to override which tools are bound.",
  },

  // ── Tools & agents ──────────────────────────────────────────────────────
  {
    name: "get_tools",
    kind: "function",
    group: "agents",
    signature: "get_tools(servers=None, include_builtins=True)",
    insert: "get_tools(${1})",
    doc: [
      "Return available LangChain tools: the built-in `web_search` + `web_fetch` plus the MCP tools selected for this script (`script.mcp_server_ids`).",
      "",
      "- `include_builtins=False` — only MCP tools.",
      "- `servers=[\"tavily\"]` — filter to specific MCP servers.",
      "",
      "Sandboxed `bash`/`python` are **not** included — add `exec_tools()` explicitly.",
    ].join("\n"),
  },
  {
    name: "get_agent",
    kind: "function",
    group: "agents",
    signature:
      'get_agent(system_prompt=None, llm_name="default", tools=None, reasoning=None, stream_reasoning=False, checkpointer=None)',
    insert: "get_agent(${1})",
    doc: [
      "Return a ready-to-use LangGraph **ReAct agent** over `get_tools()` + bound skills (advertised in the prompt, read via the `read_skill` tool).",
      "",
      "In `/converse` it auto-attaches a durable per-conversation checkpointer, so a bound skill is read **once** and multi-turn memory just works. Drive it with `stream_agent()`.",
      "",
      "```python",
      "agent = get_agent(system_prompt=\"You are helpful.\")",
      "result = agent.invoke({\"messages\": [(\"user\", msg)]})",
      "reply = result[\"messages\"][-1].content",
      "```",
    ].join("\n"),
  },
  {
    name: "get_deep_agent",
    kind: "function",
    group: "agents",
    signature:
      'get_deep_agent(system_prompt=None, llm_name="default", tools=None, reasoning=None, stream_reasoning=False, **kwargs)',
    insert: "get_deep_agent(${1})",
    doc: [
      "Opt-in **deepagents** Deep Agent: planning, sub-agents, and full skill-file browsing (mounts `run_dir/skills/` via a FilesystemBackend).",
      "",
      "Extra kwargs (`subagents=`, `middleware=`, `checkpointer=`, …) pass through to `create_deep_agent`. Drive it with `stream_agent()` too.",
    ].join("\n"),
  },
  {
    name: "stream_agent",
    kind: "function",
    group: "agents",
    signature:
      "async stream_agent(agent, messages, *, stream=True, thread_id=None, checkpoint_id=None) -> str",
    insert: "stream_agent(${1:agent}, ${2:messages})",
    doc: [
      "**Recommended** way to stream a `get_agent()` / `get_deep_agent()` answer to the chat UI and return the full reply. Emits only the model's answer text (drops tool results), so raw tool output never leaks into the reply.",
      "",
      "In a threaded `/converse` run, send only the new turn — the checkpointer supplies the history.",
      "",
      "```python",
      "reply = await stream_agent(agent, [(\"human\", input[\"message\"])])",
      "```",
    ].join("\n"),
  },
  {
    name: "stream_agent_sync",
    kind: "function",
    group: "agents",
    signature:
      "stream_agent_sync(agent, messages, *, stream=True, thread_id=None, checkpoint_id=None) -> str",
    insert: "stream_agent_sync(${1:agent}, ${2:messages})",
    doc: "Synchronous `stream_agent()` for a non-async `def run(input)`. Same filtering and return contract.",
  },

  // ── Secrets & HTTP ──────────────────────────────────────────────────────
  {
    name: "get_secret",
    kind: "function",
    group: "secrets",
    signature: "get_secret(key, default=None) -> str | None",
    insert: 'get_secret(${1:"KEY"})',
    doc: "Read an admin-managed secret by key (case-insensitive). Returns `default` (None) if missing. Manage keys on the /secrets page.",
  },
  {
    name: "list_secrets",
    kind: "function",
    group: "secrets",
    signature: "list_secrets() -> list[str]",
    doc: "List the available secret keys (values are never exposed).",
  },
  {
    name: "http_get",
    kind: "function",
    group: "http",
    signature: "http_get(url, **kwargs) -> httpx.Response",
    insert: "http_get(${1:url})",
    doc: "Thin `httpx` GET wrapper (timeout, follow-redirects, raise-for-status). Returns an `httpx.Response`.",
  },
  {
    name: "http_post",
    kind: "function",
    group: "http",
    signature: "http_post(url, **kwargs) -> httpx.Response",
    insert: "http_post(${1:url})",
    doc: "Thin `httpx` POST wrapper. Pass `json={...}` / `data=` / `headers=`. Returns an `httpx.Response`.",
  },
  {
    name: "http_request",
    kind: "function",
    group: "http",
    signature:
      "http_request(method, url, *, timeout=30, raise_for_status=True, **kwargs) -> httpx.Response",
    insert: 'http_request(${1:"GET"}, ${2:url})',
    doc: "Generic `httpx` request wrapper backing `http_get`/`http_post`.",
  },

  // ── Output & logging ────────────────────────────────────────────────────
  {
    name: "log",
    kind: "function",
    group: "output",
    signature: 'log(message, data=None, level="info", step=None)',
    insert: 'log(${1:"message"})',
    doc: "Send a structured log line to the run's Logs panel (persisted per run). `data=` attaches a JSON payload; `level=` is `info`/`warning`/`error`.",
  },
  {
    name: "token",
    kind: "function",
    group: "output",
    signature: "token(content)",
    insert: "token(${1:content})",
    doc: "Stream a text token to the chat UI in real time (typewriter effect). Not persisted — the `run()` return value is the stored reply.",
  },
  {
    name: "markdown",
    kind: "function",
    group: "output",
    signature: "markdown(content, *, title=None)",
    insert: "markdown(${1:content})",
    doc: "Render a markdown block in the Artifacts tab. (```mermaid``` fences inside are auto-rendered as diagrams.)",
  },
  {
    name: "image",
    kind: "function",
    group: "output",
    signature: 'image(src, *, alt="", mime=None, title=None)',
    insert: "image(${1:src})",
    doc: "Show an image artifact. `src` may be a URL, a filesystem path/`Path`, or raw `bytes`.",
  },
  {
    name: "table",
    kind: "function",
    group: "output",
    signature: "table(rows, *, columns=None, title=None)",
    insert: "table(${1:rows})",
    doc: "Render a table. `rows` = `list[dict]` (keys become columns) or `list[list]` with `columns=`. Pandas: `df.to_dict(\"records\")` first.",
  },
  {
    name: "html",
    kind: "function",
    group: "output",
    signature: "html(snippet, *, title=None)",
    insert: "html(${1:snippet})",
    doc: "Render an HTML snippet in a sandboxed iframe (scripts/forms blocked). For static presentation only.",
  },
  {
    name: "mermaid",
    kind: "function",
    group: "output",
    signature: "mermaid(diagram, *, title=None)",
    insert: "mermaid(${1:diagram})",
    doc: "Render a Mermaid diagram (flowchart, sequence, class, ER, …). Pass raw Mermaid source, no ```` ```mermaid ```` fence.",
  },

  // ── Skills ──────────────────────────────────────────────────────────────
  {
    name: "list_skills",
    kind: "function",
    group: "skills",
    signature: "list_skills() -> list[dict]",
    doc: "List skills bound to this script (`script.skill_ids`); each is `{name, description, ...}`.",
  },
  {
    name: "get_skill",
    kind: "function",
    group: "skills",
    signature: "get_skill(name) -> str | None",
    insert: 'get_skill(${1:"name"})',
    doc: "Return a bound skill's full `SKILL.md` text.",
  },
  {
    name: "skill_path",
    kind: "function",
    group: "skills",
    signature: "skill_path(name) -> Path | None",
    insert: 'skill_path(${1:"name"})',
    doc: "Return the `Path` to a bound skill's folder (its supporting files).",
  },

  // ── Sandboxed exec (opt-in) ─────────────────────────────────────────────
  {
    name: "run_python",
    kind: "function",
    group: "sandbox",
    signature:
      "run_python(code, *, timeout=30, cwd=None, files=None, allow_network=True) -> dict",
    insert: "run_python(${1:code})",
    doc: "Run Python in an isolated sandbox (env-scrubbed; runs under the per-script venv python). Returns `{stdout, stderr, returncode, timed_out}`. Opt-in file access via `files={\"dest\": src}`.",
  },
  {
    name: "run_bash",
    kind: "function",
    group: "sandbox",
    signature:
      "run_bash(command, *, timeout=30, cwd=None, files=None, allow_network=True) -> dict",
    insert: "run_bash(${1:command})",
    doc: "Run a shell command in an isolated sandbox (venv `bin`/`Scripts` on PATH). Returns `{stdout, stderr, returncode, timed_out}`.",
  },
  {
    name: "bash_tool",
    kind: "function",
    group: "sandbox",
    signature: "bash_tool(*, timeout=None, cwd=None, files=None)",
    insert: "bash_tool(${1})",
    doc: "Return a LangChain `bash` tool for an agent: `get_agent(tools=get_tools() + [bash_tool()])`.",
  },
  {
    name: "python_tool",
    kind: "function",
    group: "sandbox",
    signature: "python_tool(*, timeout=None, cwd=None, files=None)",
    insert: "python_tool(${1})",
    doc: "Return a LangChain `python` tool for an agent: `get_agent(tools=get_tools() + [python_tool()])`.",
  },
  {
    name: "exec_tools",
    kind: "function",
    group: "sandbox",
    signature: "exec_tools(*, timeout=None, cwd=None, files=None) -> list",
    insert: "exec_tools(${1})",
    doc: "Both opt-in sandbox tools `[bash_tool(), python_tool()]`: `get_agent(tools=get_tools() + exec_tools())`.",
  },

  // ── Paths & files ───────────────────────────────────────────────────────
  {
    name: "paths",
    kind: "variable",
    group: "runtime",
    signature: "paths  # .run_dir .workspace .script_dir .uploads",
    doc: [
      "Runtime directories (`from agentflow import paths`):",
      "",
      "- `paths.run_dir` — cwd, wiped between runs.",
      "- `paths.workspace` — **persists** across runs (caches, sqlite, indexes).",
      "- `paths.script_dir` — the script's source files.",
      "- `paths.uploads` — uploaded files.",
    ].join("\n"),
  },
  {
    name: "AgentFlowFile",
    kind: "class",
    group: "runtime",
    signature: "AgentFlowFile  # .name .mime .size .path .read_text() .read_bytes() .open()",
    doc: "A file-input wrapper: `input_data` values shaped `{\"$file\": \"<id>\"}` arrive as an `AgentFlowFile` with `.name/.mime/.size/.path/.read_text()/.read_bytes()/.open()`.",
  },
];

export const AGENTFLOW_SNIPPETS: AgentflowSnippet[] = [
  {
    label: "af:run",
    detail: "AgentFlow entry point skeleton",
    doc: "A minimal `run(input)` entry point.",
    body: [
      "def run(input: dict) -> dict:",
      "    ${1:# your logic here}",
      "    return {${2}}",
    ].join("\n"),
  },
  {
    label: "af:llm",
    detail: "Call the default LLM",
    doc: "Import + call the configured default model.",
    body: [
      "from agentflow import get_llm",
      "",
      "def run(input: dict) -> dict:",
      "    llm = get_llm()",
      "    resp = llm.invoke([(\"user\", input[${1:\"message\"}])])",
      "    return {\"reply\": resp.content}",
    ].join("\n"),
  },
  {
    label: "af:agent",
    detail: "ReAct agent over tools + skills",
    doc: "A `get_agent()` that uses the script's tools and bound skills.",
    body: [
      "from agentflow import get_agent",
      "",
      "def run(input: dict) -> dict:",
      "    agent = get_agent(system_prompt=${1:\"You are a helpful assistant.\"})",
      "    result = agent.invoke({\"messages\": [(\"user\", input[${2:\"message\"}])]})",
      "    return {\"reply\": result[\"messages\"][-1].content}",
    ].join("\n"),
  },
  {
    label: "af:chat",
    detail: "Streaming chat agent (/converse)",
    doc: "Async streaming chat: `stream_agent` + `stream_reasoning` (platform surfaces the `<think>` block). Forwards the per-conversation reasoning level.",
    body: [
      "from agentflow import get_agent, stream_agent",
      "",
      "async def run(input: dict) -> dict:",
      "    agent = get_agent(",
      "        reasoning=input.get(\"reasoning\"),",
      "        stream_reasoning=True,",
      "    )",
      "    reply = await stream_agent(agent, [(\"human\", input[\"message\"])])",
      "    return {\"reply\": reply}",
    ].join("\n"),
  },
  {
    label: "af:schema",
    detail: "INPUT_SCHEMA input contract",
    doc: "Declare a typed JSON-Schema contract for `run()`'s input (validation + auto form + typed docs example).",
    body: [
      "INPUT_SCHEMA = {",
      "    \"type\": \"object\",",
      "    \"properties\": {",
      "        \"${1:city}\": {\"type\": \"${2:string}\", \"description\": \"${3:...}\"},",
      "    },",
      "    \"required\": [\"${1:city}\"],",
      "}",
    ].join("\n"),
  },
];
