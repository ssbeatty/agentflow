"""
agentflow SDK — import this inside your LangGraph scripts.

Usage:
    from agentflow import log, get_llm, get_tools, get_agent

    def run(input: dict):
        agent = get_agent()
        result = agent.invoke({"messages": [("user", input["message"])]})
        return {"reply": result["messages"][-1].content}
"""
import os
import re
import sys
import json
import uuid as _uuid
from pathlib import Path
from types import SimpleNamespace

_PREFIX = "__AGENTFLOW__"
_IN_PLATFORM = bool(os.environ.get("AGENTFLOW_EXECUTION_ID"))

# Populated by the runner before user code runs when MCP servers are configured.
_injected_tools: list = []


# ── Paths exposed to user scripts ──────────────────────────────────────────────
#
#   paths.run_dir     — cwd of this execution (fresh per run, auto-pruned)
#   paths.workspace   — persistent dir shared across runs of the same script
#   paths.script_dir  — root of the script (main.py lives here)
#   paths.uploads     — read-only global uploads pool (rarely needed; use file refs)
#
# Outside the platform these all fall back to the current working directory so
# scripts can still be smoke-tested locally with `python main.py`.

def _p(env_key: str) -> Path:
    v = os.environ.get(env_key)
    return Path(v) if v else Path.cwd()


paths = SimpleNamespace(
    run_dir=_p("AGENTFLOW_RUN_DIR"),
    workspace=_p("AGENTFLOW_WORKSPACE_DIR"),
    script_dir=_p("AGENTFLOW_SCRIPT_DIR"),
    uploads=_p("AGENTFLOW_UPLOADS_DIR"),
)


# ── Uploaded-file wrapper ──────────────────────────────────────────────────────

class AgentFlowFile:
    """Handle for a file uploaded via /api/files/upload and referenced from
    input_data via {"$file": "<id>"}.

    The execution engine resolves the reference before launch; user code
    receives an AgentFlowFile in place of the marker dict.
    """

    __slots__ = ("id", "name", "mime", "size", "path")

    def __init__(self, *, id: str, name: str, mime: str, size: int, path: str):
        self.id = id
        self.name = name
        self.mime = mime
        self.size = size
        self.path = Path(path)

    def read_bytes(self) -> bytes:
        return self.path.read_bytes()

    def read_text(self, encoding: str = "utf-8", errors: str = "strict") -> str:
        return self.path.read_text(encoding=encoding, errors=errors)

    def open(self, mode: str = "rb"):
        return self.path.open(mode)

    def __repr__(self) -> str:  # pragma: no cover
        return f"AgentFlowFile(id={self.id!r}, name={self.name!r}, size={self.size})"


_FILE_MARKER = "__agentflow_file__"


def _hydrate_file_refs(value):
    """Recursively replace engine-planted file marker dicts with AgentFlowFile
    instances. Called by the runner before invoking user code."""
    if isinstance(value, dict):
        if value.get(_FILE_MARKER) is True:
            return AgentFlowFile(
                id=value["id"], name=value["name"], mime=value.get("mime", ""),
                size=value.get("size", 0), path=value["path"],
            )
        return {k: _hydrate_file_refs(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_hydrate_file_refs(v) for v in value]
    return value


def _norm(name: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", (name or "").upper()).strip("_") or "UNNAMED"


def list_llms() -> list[str]:
    """Return the original names of all LLM configs available to this run."""
    raw = os.environ.get("AGENTFLOW_LLM_NAMES")
    if raw:
        try:
            return json.loads(raw)
        except Exception:
            pass
    return []


def _json_default(o):
    if isinstance(o, AgentFlowFile):
        return {"$file": o.id, "name": o.name, "mime": o.mime, "size": o.size}
    if isinstance(o, Path):
        return str(o)
    return repr(o)  # last resort so log() never crashes on weird types


def _emit(data: dict) -> None:
    print(_PREFIX + json.dumps(data, ensure_ascii=False, default=_json_default), flush=True)


def log(
    message: str,
    data=None,
    level: str = "info",
    step: str | None = None,
) -> None:
    """Send a structured log entry to the platform log panel."""
    _emit({"type": "log", "level": level, "message": str(message), "data": data, "step": step})
    if not _IN_PLATFORM:
        tag = f"[{level.upper()}]" + (f"[{step}]" if step else "")
        print(f"{tag} {message}", file=sys.stderr)


def token(content: str) -> None:
    """Stream a text token to the frontend in real time (for typewriter effect).

    Call this inside your run() function as you receive chunks from the LLM.
    Tokens are broadcast via WebSocket and are NOT stored in the database.
    The final return value of run() is still used as the persisted reply.

    Example:
        async for chunk in llm.astream(messages):
            if chunk.content:
                token(chunk.content)
                full_reply += chunk.content
        return {"reply": full_reply}
    """
    _emit({"type": "token", "content": content})
    if not _IN_PLATFORM:
        sys.stdout.write(content)
        sys.stdout.flush()


# ── Artifact emitters (rich rendering in the Artifacts tab) ────────────────────

_ARTIFACTS_SUBDIR = "_artifacts"
_MIME_EXT = {
    "image/png": ".png", "image/jpeg": ".jpg", "image/jpg": ".jpg",
    "image/gif": ".gif", "image/webp": ".webp", "image/svg+xml": ".svg",
}


def _exec_id() -> str | None:
    return os.environ.get("AGENTFLOW_EXECUTION_ID")


def _save_artifact_bytes(data: bytes, mime: str | None, suffix_hint: str = "") -> str | None:
    """Save bytes under run_dir/_artifacts/, return the filename. None outside platform."""
    eid = _exec_id()
    if not eid:
        print("[agentflow] artifact outside platform: cannot save bytes", file=sys.stderr)
        return None
    ext = _MIME_EXT.get((mime or "").lower(), suffix_hint or ".bin")
    fname = f"{_uuid.uuid4().hex}{ext}"
    out_dir = paths.run_dir / _ARTIFACTS_SUBDIR
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / fname).write_bytes(data)
    return fname


def _artifact_url(filename: str) -> str | None:
    eid = _exec_id()
    return f"/api/executions/{eid}/artifacts/{filename}" if eid else None


def markdown(content: str, *, title: str | None = None) -> None:
    """Render a markdown block in the Artifacts tab."""
    _emit({"type": "artifact", "kind": "markdown", "content": str(content), "title": title})


def image(src, *, alt: str = "", mime: str | None = None, title: str | None = None) -> None:
    """Show an image artifact.

    `src` can be:
        - URL string (http://… / https://… / /…)
        - filesystem path (str or Path) — file is copied into the run's artifacts dir
        - raw bytes — saved under the run's artifacts dir with a generated name

    Example:
        image("https://example.com/chart.png", alt="last week")
        image(paths.workspace / "plot.png")
        with open("plot.png", "rb") as fh: image(fh.read(), mime="image/png")
    """
    url: str | None = None

    if isinstance(src, (bytes, bytearray)):
        fname = _save_artifact_bytes(bytes(src), mime)
        if fname:
            url = _artifact_url(fname)
    elif isinstance(src, (str, Path)):
        if isinstance(src, str) and (src.startswith("http://") or src.startswith("https://") or src.startswith("/")):
            url = src
        else:
            p = Path(src)
            if not p.is_file():
                print(f"[agentflow] image(): file not found: {src}", file=sys.stderr)
                return
            fname = _save_artifact_bytes(p.read_bytes(), mime, suffix_hint=p.suffix)
            if fname:
                url = _artifact_url(fname)
    else:
        print(f"[agentflow] image(): unsupported src type {type(src).__name__}", file=sys.stderr)
        return

    if url:
        _emit({"type": "artifact", "kind": "image", "url": url, "alt": alt, "mime": mime, "title": title})


def table(rows, *, columns: list[str] | None = None, title: str | None = None) -> None:
    """Render a table artifact.

    `rows` may be:
        - list[dict]  → keys form columns (insertion order, unioned across rows)
        - list[list]  → must pass `columns=` for headers
    Pandas users: call `df.to_dict("records")` first.

    Example:
        table([{"name": "alice", "score": 92}, {"name": "bob", "score": 81}])
        table([[1, 2], [3, 4]], columns=["a", "b"], title="Sample")
    """
    rows_list = list(rows)
    cols: list[str] = list(columns) if columns is not None else []
    norm: list[list] = []

    if rows_list and isinstance(rows_list[0], dict):
        if not cols:
            cols = list(rows_list[0].keys())
            seen = set(cols)
            for r in rows_list[1:]:
                for k in r.keys():
                    if k not in seen:
                        cols.append(k); seen.add(k)
        norm = [[r.get(c) for c in cols] for r in rows_list]
    else:
        if not cols:
            width = len(rows_list[0]) if rows_list else 0
            cols = [f"col{i+1}" for i in range(width)]
        norm = [list(r) for r in rows_list]

    _emit({"type": "artifact", "kind": "table", "columns": cols, "rows": norm, "title": title})


def html(snippet: str, *, title: str | None = None) -> None:
    """Render an arbitrary HTML snippet inside a sandboxed iframe.

    The iframe blocks scripts and forms by default; use this only for static
    presentation (styled cards, custom layouts, embed widgets that ship inline).
    """
    _emit({"type": "artifact", "kind": "html", "html": str(snippet), "title": title})


def mermaid(diagram: str, *, title: str | None = None) -> None:
    """Render a Mermaid diagram (flowchart, sequence, class, state, ER, etc).

    Pass the raw Mermaid source (without the surrounding ```mermaid fence).

    Example:
        mermaid('''
            flowchart LR
                A[Start] --> B{Decide}
                B -->|yes| C[Do thing]
                B -->|no|  D[Skip]
        ''', title="my flow")

    You can also embed ```mermaid``` fenced blocks inside markdown() — the
    renderer auto-detects and converts them to diagrams.
    """
    _emit({"type": "artifact", "kind": "mermaid", "code": str(diagram), "title": title})


def get_llm(name: str = "default"):
    """
    Return a LangChain chat model.

    - `get_llm()`              → the LLM with `is_default=True`
    - `get_llm("my-config")`   → the LLM whose `name` field matches (case-insensitive,
                                  non-alphanumerics are normalised to `_`)

    Available names can be enumerated with `list_llms()`. Returns None outside the platform.
    """
    if name == "default":
        env_key = "AGENTFLOW_LLM_DEFAULT"
    else:
        env_key = f"AGENTFLOW_LLM_{_norm(name)}"

    raw = os.environ.get(env_key)
    if not raw and name == "default":
        # no default flagged: fall back to the first available config
        candidates = sorted(
            k for k in os.environ
            if k.startswith("AGENTFLOW_LLM_") and k not in ("AGENTFLOW_LLM_DEFAULT", "AGENTFLOW_LLM_NAMES")
        )
        if candidates:
            raw = os.environ.get(candidates[0])
            print(f"[agentflow] no default LLM flagged; using {candidates[0]}", file=sys.stderr)
    if not raw:
        return None
    try:
        cfg = json.loads(raw)
        provider = cfg.get("provider", "openai")
        api_key = cfg.get("api_key")
        base_url = cfg.get("base_url")
        model = cfg.get("model", "")
        extra = cfg.get("extra_config", {})

        extra.setdefault("timeout", 60)
        extra.setdefault("max_retries", 1)

        if provider == "anthropic":
            from langchain_anthropic import ChatAnthropic
            return ChatAnthropic(model=model, api_key=api_key, **extra)
        if provider == "ollama":
            from langchain_ollama import ChatOllama
            extra.pop("max_retries", None)
            return ChatOllama(model=model, base_url=base_url or "http://localhost:11434", **extra)
        if provider == "deepseek":
            from langchain_deepseek import ChatDeepSeek
            from langchain_core.messages import AIMessage as _AIMsg

            class _ChatDeepSeekFixed(ChatDeepSeek):
                # langchain_openai's _convert_message_to_dict ignores additional_kwargs
                # that aren't explicitly handled (tool_calls, audio, etc.).
                # DeepSeek-R1 stores reasoning_content in additional_kwargs and REQUIRES
                # it to be echoed back in subsequent calls; we inject it here so the
                # serialised payload includes it.
                def _get_request_payload(self, input_, *, stop=None, **kwargs):
                    payload = super()._get_request_payload(input_, stop=stop, **kwargs)
                    if "messages" not in payload:
                        return payload
                    orig = self._convert_input(input_).to_messages()
                    for msg, d in zip(orig, payload["messages"]):
                        if isinstance(msg, _AIMsg):
                            rc = msg.additional_kwargs.get("reasoning_content")
                            if rc:
                                d["reasoning_content"] = rc
                    return payload

            kw = {"model": model, "api_key": api_key, **extra}
            if base_url:
                kw["base_url"] = base_url
            return _ChatDeepSeekFixed(**kw)
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model, api_key=api_key, base_url=base_url, **extra)
    except ImportError as e:
        print(f"[agentflow] Cannot load provider {provider!r}: {e}", file=sys.stderr)
    return None


# ── Built-in tools ─────────────────────────────────────────────────────────────

def _make_builtin_tools() -> list:
    """Create the built-in tool instances. Called lazily on first get_tools() call."""
    from langchain_core.tools import tool

    @tool
    def web_fetch(url: str) -> str:
        """Fetch the text content of a web page. Returns plain text (up to 8000 chars)."""
        try:
            import httpx
            resp = httpx.get(
                url, timeout=15, follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 AgentFlow/1.0"},
            )
            resp.raise_for_status()
            try:
                from bs4 import BeautifulSoup
                return BeautifulSoup(resp.text, "html.parser").get_text(separator="\n", strip=True)[:8000]
            except ImportError:
                return resp.text[:8000]
        except Exception as e:
            return f"Error fetching {url}: {e}"

    @tool
    def web_search(query: str, max_results: int = 5) -> str:
        """Search the web using DuckDuckGo. Returns titles, URLs, and snippets."""
        try:
            from ddgs import DDGS
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=max_results))
            if not results:
                return "No results found."
            return "\n\n".join(
                f"**{r['title']}**\n{r['href']}\n{r['body']}"
                for r in results
            )
        except Exception as e:
            return f"Search error: {e}"

    return [web_fetch, web_search]


_builtin_tools: list | None = None


def _get_builtin_tools() -> list:
    global _builtin_tools
    if _builtin_tools is None:
        _builtin_tools = _make_builtin_tools()
    return _builtin_tools


# ── Public tool API ────────────────────────────────────────────────────────────

def _ensure_sync(tool):
    """
    Add sync support to async-only MCP tools so they work with agent.invoke().

    langchain-mcp-adapters creates StructuredTool instances with only `coroutine`
    set (no `func`).  LangGraph's ToolNode calls tool._run() in sync context,
    which raises NotImplementedError.  We add a sync wrapper that delegates to
    the async implementation via the event loop; nest_asyncio (applied in the
    runner) allows this nested call even inside an already-running loop.
    """
    import asyncio
    from langchain_core.tools import StructuredTool

    if not isinstance(tool, StructuredTool) or getattr(tool, "func", None) is not None:
        return tool
    coro_fn = getattr(tool, "coroutine", None)
    if coro_fn is None:
        return tool

    def _sync_run(**kw):
        return asyncio.get_event_loop().run_until_complete(coro_fn(**kw))

    return StructuredTool(
        name=tool.name,
        description=tool.description or "",
        func=_sync_run,
        coroutine=coro_fn,
        args_schema=getattr(tool, "args_schema", None),
        return_direct=getattr(tool, "return_direct", False),
    )


def get_tools(
    servers: list[str] | None = None,
    include_builtins: bool = True,
) -> list:
    """
    Return available LangChain tools.

    - Built-ins always included: `web_fetch`, `web_search`
    - MCP tools are injected automatically from platform-configured MCP servers
    - `servers`: filter to specific MCP server names (by tool name prefix)
    - `include_builtins=False`: skip web_fetch / web_search

    Example:
        tools = get_tools()                     # all tools
        tools = get_tools(include_builtins=False)   # only MCP tools
        tools = get_tools(servers=["tavily"])    # specific server only
    """
    result = list(_get_builtin_tools()) if include_builtins else []
    if servers is None:
        to_inject = _injected_tools
    else:
        server_set = set(servers)
        to_inject = [
            t for t in _injected_tools
            # langchain-mcp-adapters prefixes tool names with "<server>__<tool>"
            if (getattr(t, "name", "") or "").split("__")[0] in server_set
        ]
    result.extend(_ensure_sync(t) for t in to_inject)
    return result


def get_llm_with_tools(name: str = "default", tools: list | None = None):
    """
    Return the configured LLM with tools bound.

    Shorthand for `get_llm().bind_tools(get_tools())`.
    Pass `tools` to override which tools are bound.
    """
    llm = get_llm(name)
    if llm is None:
        return None
    bound_tools = tools if tools is not None else get_tools()
    return llm.bind_tools(bound_tools) if bound_tools else llm


def get_agent(
    system_prompt: str | None = None,
    llm_name: str = "default",
    tools: list | None = None,
):
    """
    Return a ready-to-use ReAct agent (LangGraph create_react_agent).

    The agent has all platform-configured tools pre-loaded (web_fetch,
    web_search, and any MCP server tools). Pass `tools` to override.

    Example:
        def run(input: dict) -> dict:
            agent = get_agent()
            result = agent.invoke({"messages": [("user", input["message"])]})
            return {"reply": result["messages"][-1].content}

        # With a custom system prompt:
        agent = get_agent(system_prompt="You are a research assistant.")

        # Async:
        async def run(input: dict) -> dict:
            agent = get_agent()
            result = await agent.ainvoke({"messages": [("user", input["message"])]})
            return {"reply": result["messages"][-1].content}
    """
    import inspect
    from langgraph.prebuilt import create_react_agent

    llm = get_llm(llm_name)
    if llm is None:
        raise RuntimeError(
            "No LLM configured. Add one in AgentFlow Settings before calling get_agent()."
        )
    agent_tools = tools if tools is not None else get_tools()
    if not system_prompt:
        return create_react_agent(llm, agent_tools)

    # Parameter was renamed across LangGraph versions:
    #   < 0.2.x  → state_modifier
    #   >= 0.2.x → prompt
    from langchain_core.messages import SystemMessage
    def _prompt_fn(state):
        msgs = state["messages"] if isinstance(state, dict) else list(state)
        return [SystemMessage(content=system_prompt)] + msgs

    params = inspect.signature(create_react_agent).parameters
    if "prompt" in params:
        return create_react_agent(llm, agent_tools, prompt=_prompt_fn)
    if "state_modifier" in params:
        return create_react_agent(llm, agent_tools, state_modifier=_prompt_fn)
    print(
        "[agentflow] Warning: this LangGraph version does not support system_prompt in get_agent(); ignoring.",
        file=sys.stderr,
    )
    return create_react_agent(llm, agent_tools)
