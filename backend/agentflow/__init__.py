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


# ── Secrets (externally-managed credentials) ──────────────────────────────────

def get_secret(key: str, default: str | None = None) -> str | None:
    """Return the value of a secret configured in the Secrets UI/API.

    Keys are matched case-insensitively (non-alphanumerics → "_"), so
    `get_secret("BARK_KEY")` and `get_secret("bark_key")` resolve to the same
    secret. Returns `default` (None) when the secret isn't set.

    Secrets are stored server-side and injected into this run's environment;
    they never appear in your source code, input data, or the frontend.

    Example:
        BARK_KEY = get_secret("BARK_KEY")
    """
    v = os.environ.get(f"AGENTFLOW_SECRET_{_norm(key)}")
    return v if v is not None and v != "" else default


def list_secrets() -> list[str]:
    """Return the names (keys) of all secrets available to this run.
    Values are never exposed — use get_secret(name) to read one."""
    raw = os.environ.get("AGENTFLOW_SECRET_NAMES")
    if raw:
        try:
            return json.loads(raw)
        except Exception:
            pass
    return []


# ── Skills (Agent Skills bound to this run) ────────────────────────────────────
#
# The engine materializes each bound skill to run_dir/skills/<name>/ and exposes a
# manifest via AGENTFLOW_SKILLS = [{name, description, dir, main}]. Skills follow
# the Agent Skills convention: a SKILL.md (instructions) plus supporting files.
# get_agent() advertises name+description in the system prompt; the agent reads a
# skill's full body on demand through the built-in `read_skill` tool.

def _skill_manifest() -> list[dict]:
    raw = os.environ.get("AGENTFLOW_SKILLS")
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return data
        except Exception:
            pass
    return []


def list_skills() -> list[dict]:
    """Return the skills bound to this run as ``[{name, description}]``."""
    return [{"name": s.get("name", ""), "description": s.get("description", "")}
            for s in _skill_manifest()]


def get_skill(name: str) -> str | None:
    """Return the full SKILL.md text of a bound skill, or None if not found.

    Matching is case-insensitive on the skill name. Use this (or the agent's
    built-in `read_skill` tool) to load a skill's instructions on demand."""
    want = (name or "").strip().lower()
    for s in _skill_manifest():
        if (s.get("name", "") or "").strip().lower() == want:
            main = Path(s["dir"]) / s.get("main", "SKILL.md")
            try:
                return main.read_text(encoding="utf-8")
            except Exception:
                return None
    return None


def skill_path(name: str) -> Path | None:
    """Return the on-disk directory of a bound skill (for reading its files)."""
    want = (name or "").strip().lower()
    for s in _skill_manifest():
        if (s.get("name", "") or "").strip().lower() == want:
            return Path(s["dir"])
    return None


# ── HTTP convenience (provider-agnostic, thin httpx wrapper) ───────────────────

def http_request(method: str, url: str, *, timeout: float = 30, raise_for_status: bool = True, **kwargs):
    """Thin wrapper over httpx so scripts don't re-implement timeout / redirect /
    error-raising boilerplate on every call.

    All other keyword args pass straight through to `httpx.request`
    (`json=`, `data=`, `params=`, `headers=`, `auth=`, ...). Returns the
    `httpx.Response` — use `.json()`, `.text`, `.status_code`. Pass
    `raise_for_status=False` to inspect 4xx/5xx yourself instead of raising.

    Example:
        r = http_post(
            "https://api.example.com/v1/messages",
            json={"text": "hello"},
            headers={"Authorization": f"Bearer {get_secret('SERVICE_TOKEN')}"},
        )
        data = r.json()
    """
    import httpx
    kwargs.setdefault("follow_redirects", True)
    resp = httpx.request(method, url, timeout=timeout, **kwargs)
    if raise_for_status:
        resp.raise_for_status()
    return resp


def http_get(url: str, **kwargs):
    """GET via http_request(); see http_request for options."""
    return http_request("GET", url, **kwargs)


def http_post(url: str, **kwargs):
    """POST via http_request(); see http_request for options."""
    return http_request("POST", url, **kwargs)


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


_REASONING_BUDGET = {"low": 1024, "medium": 4096, "high": 12000}


def _norm_reasoning(level) -> "str | None":
    """Normalise a reasoning/think request to None | 'low' | 'medium' | 'high'.

    Accepts a level string, a bool (True → 'medium'), or falsy/off values → None.
    """
    if level is None or level is False:
        return None
    if level is True:
        return "medium"
    s = str(level).strip().lower()
    if s in ("", "off", "none", "no", "false", "0", "disabled"):
        return None
    if s in ("low", "medium", "high"):
        return s
    if s in ("min", "minimal"):
        return "low"
    if s in ("max", "maximum"):
        return "high"
    return "medium"


def _apply_reasoning(extra: dict, provider: str, base_url: "str | None", level: str) -> None:
    """Translate one shared low/medium/high level into the provider-specific
    'think' knob (each vendor exposes reasoning differently):

      - anthropic  → thinking={'type':'enabled','budget_tokens': …}
                     (Claude also needs temperature=1 and max_tokens > budget)
      - openai o-series / gpt-5 (no base_url) → reasoning_effort=<level>
      - OpenAI-compatible gateway (base_url set) → extra_body={'enable_thinking': True}
                     (Qwen3 / GLM / vLLM style — a boolean toggle, so the level only
                     gates on/off here; tune per-gateway if it supports a budget)
      - deepseek   → nothing (deepseek-reasoner reasons natively; the text comes
                     back in additional_kwargs['reasoning_content'])
      - ollama     → reasoning=True
    """
    if provider == "anthropic":
        budget = _REASONING_BUDGET[level]
        extra["thinking"] = {"type": "enabled", "budget_tokens": budget}
        extra["temperature"] = 1
        if not extra.get("max_tokens") or extra["max_tokens"] <= budget:
            extra["max_tokens"] = budget + 4096
    elif provider == "deepseek":
        return
    elif provider == "ollama":
        extra.setdefault("reasoning", True)
    else:  # openai + OpenAI-compatible gateways
        if base_url:
            eb = dict(extra.get("extra_body") or {})
            eb.setdefault("enable_thinking", True)
            extra["extra_body"] = eb
        else:
            extra.setdefault("reasoning_effort", level)


def get_llm(name: str = "default", reasoning=None):
    """
    Return a LangChain chat model.

    - `get_llm()`              → the model flagged as default in Settings
    - `get_llm("gpt-4o")`      → the model by id (case-insensitive; non-alphanumerics
                                  normalised to `_`). When several channels serve the
                                  same model id, the highest-priority channel wins
                                  (ties → earliest); credentials come from that channel.
    - `reasoning=`             → turn on the model's thinking/chain-of-thought at a
                                  shared level: `"low"` / `"medium"` / `"high"` (or
                                  `True` = medium; `None`/`"off"` = disabled). Mapped
                                  per provider (Claude thinking budget, OpenAI
                                  reasoning_effort, gateway enable_thinking, …). The
                                  reasoning text streams back as `reasoning_content`
                                  or a `<think>` block — see the chat templates.

    Available model ids can be enumerated with `list_llms()`. Returns None outside
    the platform.
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

        _level = _norm_reasoning(reasoning)
        if _level:
            _apply_reasoning(extra, provider, base_url, _level)

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
#
# `web_search` / `web_fetch` pick a provider from AGENTFLOW_SEARCH_CONFIG (set by
# the engine from the Tools-page "Web search provider" config). Currently:
#   - Tavily (needs an API key) — best quality for agents; used when configured.
#   - DuckDuckGo (via `ddgs`, no key) — the always-on fallback.
# Any Tavily error / empty result transparently falls back to DuckDuckGo, so an
# unconfigured deployment still searches.

_TAVILY_SEARCH_URL = "https://api.tavily.com/search"
_TAVILY_EXTRACT_URL = "https://api.tavily.com/extract"
_FETCH_LIMIT = 8000


def _search_config() -> dict:
    raw = os.environ.get("AGENTFLOW_SEARCH_CONFIG")
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {}


def _tavily_key() -> str | None:
    key = (_search_config().get("tavily_api_key") or "").strip()
    return key or None


def _tavily_search(query: str, max_results: int, key: str) -> str:
    import httpx
    resp = httpx.post(
        _TAVILY_SEARCH_URL,
        headers={"Authorization": f"Bearer {key}"},
        json={"query": query, "max_results": max_results, "search_depth": "basic"},
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    results = data.get("results") or []
    if not results:
        return ""
    parts = []
    answer = (data.get("answer") or "").strip()
    if answer:
        parts.append(f"**Answer**\n{answer}")
    for r in results:
        parts.append(
            f"**{r.get('title', '')}**\n{r.get('url', '')}\n{(r.get('content') or '').strip()}"
        )
    return "\n\n".join(parts)


def _ddg_search(query: str, max_results: int) -> str:
    from ddgs import DDGS
    with DDGS() as ddgs:
        results = list(ddgs.text(query, max_results=max_results))
    if not results:
        return "No results found."
    return "\n\n".join(
        f"**{r['title']}**\n{r['href']}\n{r['body']}"
        for r in results
    )


def _tavily_extract(url: str, key: str) -> str:
    import httpx
    resp = httpx.post(
        _TAVILY_EXTRACT_URL,
        headers={"Authorization": f"Bearer {key}"},
        json={"urls": [url]},
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    results = data.get("results") or []
    if results:
        content = (results[0].get("raw_content") or "").strip()
        if content:
            return content[:_FETCH_LIMIT]
    return ""


def _httpx_fetch(url: str) -> str:
    import httpx
    resp = httpx.get(
        url, timeout=15, follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 AgentFlow/1.0"},
    )
    resp.raise_for_status()
    try:
        from bs4 import BeautifulSoup
        return BeautifulSoup(resp.text, "html.parser").get_text(separator="\n", strip=True)[:_FETCH_LIMIT]
    except ImportError:
        return resp.text[:_FETCH_LIMIT]


def _make_builtin_tools() -> list:
    """Create the built-in tool instances. Called lazily on first get_tools() call."""
    from langchain_core.tools import tool

    @tool
    def web_fetch(url: str) -> str:
        """Fetch the text content of a web page. Returns plain text (up to 8000 chars)."""
        key = _tavily_key()
        if key:
            # Tavily's extractor returns clean article text; fall back to a raw
            # httpx fetch on any failure so a bad key / unsupported page still works.
            try:
                content = _tavily_extract(url, key)
                if content:
                    return content
            except Exception:
                pass
        try:
            return _httpx_fetch(url)
        except Exception as e:
            return f"Error fetching {url}: {e}"

    @tool
    def web_search(query: str, max_results: int = 5) -> str:
        """Search the web and return titles, URLs, and snippets.

        Uses the provider configured in AgentFlow (Tavily when a key is set),
        falling back to DuckDuckGo otherwise."""
        cfg = _search_config()
        key = _tavily_key()
        if cfg.get("provider", "tavily") == "tavily" and key:
            try:
                out = _tavily_search(query, max_results, key)
                if out:
                    return out
                # empty Tavily result → try DuckDuckGo before giving up
            except Exception:
                pass  # fall through to DuckDuckGo
        try:
            return _ddg_search(query, max_results)
        except Exception as e:
            return f"Search error: {e}"

    return [web_fetch, web_search]


def _make_skill_tool():
    """Create the `read_skill` tool the agent uses to load a skill on demand.

    Returns None when no skills are bound to this run so plain agents are
    unchanged."""
    manifest = _skill_manifest()
    if not manifest:
        return None
    from langchain_core.tools import tool

    @tool
    def read_skill(name: str) -> str:
        """Load the full instructions (SKILL.md) of one of the available skills.
        Call this when the task matches a skill's description. Pass the skill name."""
        body = get_skill(name)
        if body is None:
            avail = ", ".join(s.get("name", "") for s in _skill_manifest()) or "none"
            # Surface misses in the log panel so authors can see the agent tried.
            log(f"read_skill: no skill named {name!r} (available: {avail})",
                level="warning", step="skill")
            return f"No skill named {name!r}. Available skills: {avail}."
        # Surface skill loads in the log panel — otherwise it's invisible whether
        # the agent actually used a skill.
        log(f"Loaded skill: {name}", data={"chars": len(body)}, step="skill")
        return body

    return read_skill


def _skill_preamble() -> str:
    """A system-prompt block listing bound skills (name + description). The agent
    pulls a skill's full body with the `read_skill` tool — progressive disclosure."""
    manifest = _skill_manifest()
    if not manifest:
        return ""
    lines = [
        "## Available skills",
        "You have access to the following skills. When a task matches a skill's "
        "description, call the `read_skill` tool with its name to load the full "
        "instructions, then follow them.",
        "",
    ]
    for s in manifest:
        desc = (s.get("description", "") or "").strip().replace("\n", " ")
        lines.append(f"- **{s.get('name', '')}**: {desc}")
    return "\n".join(lines)


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
    reasoning=None,
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

    llm = get_llm(llm_name, reasoning=reasoning)
    if llm is None:
        raise RuntimeError(
            "No LLM configured. Add one in AgentFlow Settings before calling get_agent()."
        )
    agent_tools = tools if tools is not None else get_tools()

    # Skills bound to this run are advertised in the system prompt (name +
    # description) and loaded on demand via the `read_skill` tool.
    skill_tool = _make_skill_tool()
    if skill_tool is not None and not any(
        getattr(t, "name", "") == "read_skill" for t in agent_tools
    ):
        agent_tools = list(agent_tools) + [skill_tool]
    preamble = _skill_preamble()
    if preamble:
        system_prompt = f"{system_prompt}\n\n{preamble}" if system_prompt else preamble

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


def _skills_root() -> "Path | None":
    """The directory holding this run's materialized skills (run_dir/skills)."""
    run_dir = os.environ.get("AGENTFLOW_RUN_DIR")
    if run_dir:
        root = Path(run_dir) / "skills"
        if root.is_dir():
            return root
    # Fallback: derive from the manifest (parent of any skill dir).
    for s in _skill_manifest():
        d = s.get("dir")
        if d and Path(d).parent.is_dir():
            return Path(d).parent
    return None


def get_deep_agent(
    system_prompt: str | None = None,
    llm_name: str = "default",
    tools: list | None = None,
    reasoning=None,
    **kwargs,
):
    """
    Return a LangChain **Deep Agent** (``deepagents.create_deep_agent``) with the
    skills bound to this run mounted from disk.

    Where ``get_agent()`` exposes a single ``read_skill`` tool over each skill's
    SKILL.md, a deep agent mounts ``run_dir/skills/`` through a
    ``FilesystemBackend`` — so the agent can browse and read *every* file in a
    skill itself (SKILL.md + supporting files + nested folders) via built-in
    filesystem tools, and additionally gets deepagents' planning + sub-agent
    machinery. Skill selection is the same: bind skills to the script
    (``script.skill_ids``); they're materialized to ``run_dir/skills/<name>/``.

    Requires the ``deepagents`` package (installed in the baseline venv). Extra
    keyword args (``subagents=``, ``middleware=``, ``checkpointer=``, …) pass
    straight through to ``create_deep_agent``.

    Example:
        async def run(input: dict) -> dict:
            agent = get_deep_agent(system_prompt="Use the available skills.")
            result = await agent.ainvoke({"messages": [("user", input["message"])]})
            return {"reply": result["messages"][-1].content}
    """
    import inspect
    try:
        from deepagents import create_deep_agent
        from deepagents.backends.filesystem import FilesystemBackend
    except ImportError as e:
        raise RuntimeError(
            "get_deep_agent() needs the 'deepagents' package. It ships in the "
            "baseline venv; if it's missing, add 'deepagents' to requirements.txt."
        ) from e

    llm = get_llm(llm_name, reasoning=reasoning)
    if llm is None:
        raise RuntimeError(
            "No LLM configured. Add one in AgentFlow Settings before calling get_deep_agent()."
        )

    # Advertise bound skills (name + description) in the prompt; the agent reads
    # the full files itself through the filesystem tools.
    preamble = _skill_preamble()
    if preamble:
        system_prompt = f"{system_prompt}\n\n{preamble}" if system_prompt else preamble

    # create_deep_agent's parameter names vary across versions; introspect and
    # only pass what this build actually accepts (it may also take **kwargs).
    params = inspect.signature(create_deep_agent).parameters
    accepts_kwargs = any(p.kind == p.VAR_KEYWORD for p in params.values())

    def _supports(key: str) -> bool:
        return accepts_kwargs or key in params

    call: dict = {"model": llm, **kwargs}

    if system_prompt:
        # newer deepagents: `system_prompt`; classic: `instructions`.
        if "system_prompt" in params:
            call.setdefault("system_prompt", system_prompt)
        elif "instructions" in params:
            call.setdefault("instructions", system_prompt)
        elif accepts_kwargs:
            call.setdefault("system_prompt", system_prompt)

    # Always expose the same `read_skill` tool as get_agent() — a reliable,
    # cross-platform way to load a skill's SKILL.md (plain file read). This is the
    # unified skill entry point across both agent modes; the deepagents filesystem
    # mount below additionally lets the agent browse a skill's *other* files.
    skill_tool = _make_skill_tool()
    merged_tools = list(tools) if tools else []
    if skill_tool is not None:
        merged_tools.append(skill_tool)
    if merged_tools and _supports("tools"):
        call.setdefault("tools", merged_tools)

    # Mount the run dir so the agent's filesystem tools + skills load from it.
    # The backend runs in **virtual mode**: the agent addresses files by POSIX
    # virtual paths (/skills/...) anchored at run_dir, not real OS paths. This is
    # REQUIRED on Windows — deepagents' path validator rejects drive-letter
    # absolute paths (e.g. D:\...\SKILL.md), so a non-virtual backend crashes the
    # moment the skills loader hands the agent a skill-file path. Virtual paths
    # behave identically on every platform. Skills are materialized to
    # run_dir/skills → the virtual source "/skills".
    run_dir = os.environ.get("AGENTFLOW_RUN_DIR")
    virtual = False
    if run_dir and _supports("backend"):
        be_params = inspect.signature(FilesystemBackend).parameters
        be_kwargs = {"root_dir": str(run_dir)}
        if "virtual_mode" in be_params:
            be_kwargs["virtual_mode"] = True
            virtual = True
        call.setdefault("backend", FilesystemBackend(**be_kwargs))
    if run_dir and _supports("skills") and (Path(run_dir) / "skills").is_dir():
        # Virtual backend → virtual source path; otherwise the real path (POSIX).
        src = "/skills" if virtual else str(Path(run_dir) / "skills")
        call.setdefault("skills", [src])

    return create_deep_agent(**call)
