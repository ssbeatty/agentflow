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

_PREFIX = "__AGENTFLOW__"
_IN_PLATFORM = bool(os.environ.get("AGENTFLOW_EXECUTION_ID"))

# Populated by the runner before user code runs when MCP servers are configured.
_injected_tools: list = []


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


def _emit(data: dict) -> None:
    print(_PREFIX + json.dumps(data, ensure_ascii=False), flush=True)


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
        result.extend(_injected_tools)
    else:
        server_set = set(servers)
        for t in _injected_tools:
            # langchain-mcp-adapters prefixes tool names with "<server>__<tool>"
            prefix = (getattr(t, "name", "") or "").split("__")[0]
            if prefix in server_set:
                result.append(t)
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
