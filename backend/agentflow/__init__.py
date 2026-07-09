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

_PREFIX = "__AGENTFLOW__"
_IN_PLATFORM = bool(os.environ.get("AGENTFLOW_EXECUTION_ID"))

# Sandboxed exec (see agentflow/_sandbox.py). Re-exported so scripts can call
# them directly (like markdown()/image()). They are OPT-IN — NOT part of the
# default tool set; hand them to an agent via exec_tools()/bash_tool()/
# python_tool() (defined below).
from agentflow._sandbox import (  # noqa: E402
    run_bash,
    run_python,
)

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


class _Paths:
    """Run paths, resolved lazily on **every access** (never snapshotted).

    This must not be a value snapshotted at import time. Under the warm-worker
    pool (services/worker_pool.py) this module is imported ONCE at worker boot —
    before any job's per-run env (AGENTFLOW_RUN_DIR / AGENTFLOW_WORKSPACE_DIR)
    exists — and then reused for every subsequent job. A snapshot would freeze
    all paths to the boot-time cwd (the script dir) for the whole life of the
    worker, so `paths.run_dir` / `paths.workspace` would silently point at the
    wrong directory on every reused run (and `image()` / artifacts, which write
    under `paths.run_dir`, would land out of the served dir and 404). Resolving
    on access keeps them correct for both the one-shot runner and the worker.
    """

    @property
    def run_dir(self) -> Path:
        return _p("AGENTFLOW_RUN_DIR")

    @property
    def workspace(self) -> Path:
        return _p("AGENTFLOW_WORKSPACE_DIR")

    @property
    def script_dir(self) -> Path:
        return _p("AGENTFLOW_SCRIPT_DIR")

    @property
    def uploads(self) -> Path:
        return _p("AGENTFLOW_UPLOADS_DIR")


paths = _Paths()


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
            # Unlike Anthropic's budget_tokens, this gateway toggle has no explicit
            # thinking budget — the whole completion (thinking + answer) shares one
            # max_tokens pool. Reasoning models (Qwen3/GLM/…) can burn through a
            # small/default max_tokens entirely on the hidden <think> section,
            # leaving no room for the visible answer. Give it the same floor as the
            # Anthropic budget so a long think doesn't starve the answer.
            budget = _REASONING_BUDGET[level]
            if not extra.get("max_tokens") or extra["max_tokens"] <= budget:
                extra["max_tokens"] = budget + 4096
        else:
            extra.setdefault("reasoning_effort", level)


# ── Auto-stream chain-of-thought as <think> (opt-in via stream_reasoning=) ──────
#
# A reasoning model returns its chain-of-thought on a channel separate from the
# answer — DeepSeek in `additional_kwargs["reasoning_content"]`, Anthropic in
# `thinking` content blocks. Surfacing it in /converse means wrapping it in a
# `<think>…</think>` block in the token stream. Making each script do that by hand
# is error-prone (open once / close once / keep it out of the reply), so instead
# `get_llm(stream_reasoning=True)` (and get_agent/get_deep_agent) attach this
# callback: it watches the model's streamed tokens and emits the reasoning as a
# single <think> block automatically, so scripts contain NO think-handling logic.

def _chunk_reasoning(chunk) -> str:
    """Reasoning delta carried by a streamed chunk, if any (provider-agnostic)."""
    msg = getattr(chunk, "message", None)
    if msg is None:
        return ""
    ak = getattr(msg, "additional_kwargs", None) or {}
    rc = ak.get("reasoning_content")
    if rc:
        return rc if isinstance(rc, str) else str(rc)
    content = getattr(msg, "content", None)  # Anthropic: thinking blocks
    if isinstance(content, list):
        parts = [
            (b.get("thinking") or b.get("text") or "")
            for b in content
            if isinstance(b, dict) and b.get("type") in ("thinking", "redacted_thinking")
        ]
        if any(parts):
            return "".join(parts)
    return ""


def _final_reasoning_content(response) -> str:
    """Reasoning from a *non-streamed* LLMResult (the invoke() fallback path)."""
    try:
        for batch in (getattr(response, "generations", None) or []):
            for g in (batch if isinstance(batch, list) else [batch]):
                rc = _chunk_reasoning(g)
                if rc:
                    return rc
    except Exception:
        pass
    return ""


def _neutralize_think_tags(s: str) -> str:
    """Defang any literal ``<think>``/``</think>`` (or ``<thinking>``) inside the
    model's reasoning so it can't close the wrapper early in the frontend's
    splitThink (which splits on the first ``</think>``). A zero-width space after
    ``<`` breaks the tag match while rendering identically (the block shows the
    reasoning as plain pre-wrapped text)."""
    if not s or "<" not in s:
        return s
    zwsp = chr(0x200b)  # invisible in the rendered block; breaks the tag regex match
    return re.sub(r"</?think(?:ing)?>", lambda m: m.group(0).replace("<", "<" + zwsp), s,
                  flags=re.IGNORECASE)


try:
    from langchain_core.callbacks import BaseCallbackHandler as _BaseCB  # type: ignore
except ImportError:  # pragma: no cover
    _BaseCB = object  # type: ignore


class _ReasoningStreamer(_BaseCB):
    """Emit a model's separate chain-of-thought to the chat UI as one
    ``<think>…</think>`` block, so a script never handles reasoning tags itself.
    Sync + ``run_inline`` so it fires (in order) for both ``.stream()`` and
    ``.astream()``, exactly like the global tracer. State is keyed per LLM run,
    so an agent's tool-loop (many LLM calls) closes each block cleanly."""

    raise_error = False
    run_inline = True

    def __init__(self) -> None:
        self._open: dict[str, bool] = {}      # run_id → <think> currently open
        self._streamed: dict[str, bool] = {}  # run_id → emitted any reasoning live

    def _close(self, rid: str) -> None:
        if self._open.get(rid):
            token("</think>")
            self._open[rid] = False

    def on_llm_new_token(self, *args, **kwargs):
        # LangChain passes the token text positionally in some paths and as the
        # keyword `token=` in others; accept both without shadowing the module's
        # own token() emitter (hence *args/**kwargs, not a `token` parameter).
        text = kwargs.get("token")
        if text is None and args:
            text = args[0]
        chunk = kwargs.get("chunk")
        rid = str(kwargs.get("run_id"))
        rc = _chunk_reasoning(chunk) if chunk is not None else ""
        if rc:
            if not self._open.get(rid):
                token("<think>")
                self._open[rid] = True
            token(_neutralize_think_tags(rc))
            self._streamed[rid] = True
            # A single chunk can carry BOTH the reasoning delta and answer text
            # (transition deltas / aggregated chunks on vLLM/OpenRouter/relays).
            # The script emits that answer text right after us, so close the block
            # now — otherwise the answer is trapped inside <think>.
            if text:
                self._close(rid)
            return
        if text:   # pure answer text → close the block once if still open
            self._close(rid)

    def on_llm_end(self, response, *, run_id=None, **kwargs):
        rid = str(run_id)
        if self._open.pop(rid, False):
            token("</think>")
        elif not self._streamed.get(rid):
            # Non-streaming (invoke): reasoning arrived whole in the final message.
            rc = _final_reasoning_content(response)
            if rc:
                token(f"<think>{_neutralize_think_tags(rc)}</think>")
        self._streamed.pop(rid, None)

    def on_llm_error(self, error, *, run_id=None, **kwargs):
        rid = str(run_id)
        if self._open.pop(rid, False):
            token("</think>")
        self._streamed.pop(rid, None)


def _reasoning_callbacks(stream_reasoning: bool) -> list:
    """[_ReasoningStreamer()] when opted in and langchain is importable, else []."""
    if not stream_reasoning or _BaseCB is object:
        return []
    return [_ReasoningStreamer()]


def get_llm(name: str = "default", reasoning=None, stream_reasoning: bool = False):
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
    - `stream_reasoning=True`  → auto-surface that chain-of-thought in the chat UI as
                                  a collapsible `<think>` block, with NO think logic in
                                  your script: just `token(chunk.content)` for the
                                  answer. The platform emits the reasoning for you and
                                  keeps it out of your returned reply. No-op if the
                                  model isn't reasoning. Pair with `reasoning=`.

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
        # A specific model was asked for but isn't configured: fail loudly with the
        # real cause (typo'd / unconfigured id) instead of returning None and
        # letting the caller hit a confusing `'NoneType' has no attribute 'invoke'`
        # later. `get_llm()` (default) still returns None when no LLM exists at all.
        if name != "default":
            available = list_llms()
            raise ValueError(
                f"LLM model {name!r} is not configured on this AgentFlow instance"
                + (f"; available models: {available}" if available else "")
                + ". Check the model id (see list_llms()) or configure a channel in Settings."
            )
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

        # Opt-in: attach the callback that auto-streams reasoning as <think>.
        _cbs = _reasoning_callbacks(stream_reasoning)
        if _cbs:
            extra["callbacks"] = list(extra.get("callbacks") or []) + _cbs

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


# ── Opt-in sandboxed exec tools (bash + python) ────────────────────────────────
#
# These are deliberately NOT in get_tools()/get_agent() by default, because they
# run arbitrary commands/code. A script opts in — either calling run_bash() /
# run_python() directly, or handing the tools to an agent:
#
#     agent = get_agent(tools=get_tools() + exec_tools())
#     agent = get_agent(tools=get_tools() + [bash_tool()])   # bash only
#
# Isolation (env-scrub of all AGENTFLOW_* secrets, rlimits, timeout, throwaway
# cwd) lives in agentflow/_sandbox.py. By default the sandbox cwd is an empty
# throwaway dir; bind the tools to real data with `files=` (copy inputs into
# the sandbox cwd) or `cwd=` (run in a persistent dir, e.g. the workspace):
#
#     ws = os.environ["AGENTFLOW_WORKSPACE_DIR"]
#     agent = get_agent(tools=get_tools() + exec_tools(cwd=ws))

def _cwd_hint(cwd: str | None) -> str:
    if not cwd:
        return ""
    return (f'\n\nYour working directory is "{cwd}"; it is persistent, and '
            f"relative paths resolve there — read and write files in it directly.")


def bash_tool(*, timeout: float | None = None, cwd: str | None = None,
              files: dict | None = None):
    """Return a LangChain `bash` tool that runs a shell command in the sandbox.

    Opt-in: add it to an agent's tools yourself (it is never auto-included)::

        agent = get_agent(tools=get_tools() + [bash_tool()])

    ``cwd=`` runs every call in that persistent directory (advertised to the
    agent in the tool description); ``files=`` copies inputs into the sandbox
    cwd before each call (see `run_bash`).
    """
    from langchain_core.tools import tool
    from agentflow._sandbox import run_bash, format_exec_result, DEFAULT_TIMEOUT
    _to = timeout if timeout is not None else DEFAULT_TIMEOUT

    @tool
    def bash(command: str) -> str:
        """Run a shell command in a sandbox and return its output (stdout, then
        stderr / exit code on failure). The sandbox has a working directory of
        its own, a timeout, resource limits, and no access to platform secrets.
        Use it to inspect files, run CLIs, or shell out to other tools.

        Example: bash("ls -la && python3 -c 'print(2**10)'")
        """
        try:
            return format_exec_result(
                run_bash(command, timeout=_to, cwd=cwd, files=files), timeout=_to)
        except Exception as e:
            return f"Sandbox error: {e}"

    bash.description += _cwd_hint(cwd)
    return bash


def python_tool(*, timeout: float | None = None, cwd: str | None = None,
                files: dict | None = None):
    """Return a LangChain `python` tool that runs Python code in the sandbox.

    Opt-in: add it to an agent's tools yourself (it is never auto-included)::

        agent = get_agent(tools=get_tools() + [python_tool()])

    ``cwd=`` runs every call in that persistent directory (advertised to the
    agent in the tool description); ``files=`` copies inputs into the sandbox
    cwd before each call (see `run_python`).
    """
    from langchain_core.tools import tool
    from agentflow._sandbox import run_python, format_exec_result, DEFAULT_TIMEOUT
    _to = timeout if timeout is not None else DEFAULT_TIMEOUT

    @tool
    def python(code: str) -> str:
        """Run Python code in a sandbox and return its output. Use this for
        computation, data wrangling, parsing, or simulation — anything better
        solved by running code than by reasoning it out. Packages installed for
        this script (numpy, pandas, …) are importable. `print(...)` to show
        output; a bare final expression is echoed automatically (notebook-style).
        The sandbox has a timeout, resource limits, and no access to secrets.

        Example: python("import statistics; statistics.stdev([2,4,4,4,5,5,7,9])")
        """
        try:
            return format_exec_result(
                run_python(code, timeout=_to, cwd=cwd, files=files), timeout=_to)
        except Exception as e:
            return f"Sandbox error: {e}"

    python.description += _cwd_hint(cwd)
    return python


def exec_tools(*, timeout: float | None = None, cwd: str | None = None,
               files: dict | None = None) -> list:
    """Return both opt-in sandbox tools ``[bash_tool(), python_tool()]``.

    Convenience for the common case::

        agent = get_agent(tools=get_tools() + exec_tools())

    Pass ``cwd=os.environ["AGENTFLOW_WORKSPACE_DIR"]`` to let the agent work on
    persistent workspace files, or ``files={...}`` to copy inputs into each
    sandbox call's cwd.
    """
    return [bash_tool(timeout=timeout, cwd=cwd, files=files),
            python_tool(timeout=timeout, cwd=cwd, files=files)]


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
    - Sandboxed exec tools (`bash`, `python`) are OPT-IN — not included here;
      add them explicitly with `exec_tools()` (see `bash_tool` / `python_tool`)
    - MCP tools are injected automatically from platform-configured MCP servers
    - `servers`: filter to specific MCP server names (by tool name prefix)
    - `include_builtins=False`: skip web_fetch / web_search

    Example:
        tools = get_tools()                     # all tools
        tools = get_tools(include_builtins=False)   # only MCP tools
        tools = get_tools(servers=["tavily"])    # specific server only
    """
    result = list(_get_builtin_tools()) if include_builtins else []
    # `_injected_tools` is normally a list (empty when no MCP server is bound).
    # Guard against None so get_tools()/get_agent() never crash with "NoneType is
    # not iterable": the warm worker resets this global per job and a no-MCP run
    # leaves it unset, so a bound-to-nothing agent must still get the builtins.
    injected = _injected_tools or []
    if servers is None:
        to_inject = injected
    else:
        server_set = set(servers)
        to_inject = [
            t for t in injected
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


# ── Conversation threading (durable per-conversation agent state) ──────────────
#
# A /converse conversation IS a LangGraph thread: its conversation_id is the
# thread_id. For a chat run the engine sets AGENTFLOW_THREAD_ID (== the
# conversation id) and AGENTFLOW_THREAD_CHECKPOINT (the checkpoint to resume /
# roll back from). get_agent() / get_deep_agent() then attach a durable SQLite
# checkpointer at workspace/threads.db, so the FULL agent state — including a
# skill's body once it's been read, and every tool result — persists across
# turns. The agent reads a skill ONCE instead of every turn, and multi-turn
# memory just works. Nothing here runs when there is no thread env (a normal
# script run) → the classic stateless path is byte-for-byte unchanged.

# Reused across a warm worker's jobs (agentflow is imported once at boot): one
# aiosqlite connection per workspace-db path. Keyed by path so it's always the
# right thread store even if a process somehow serves more than one workspace.
_THREAD_CHECKPOINTERS: dict = {}


def _thread_id() -> "str | None":
    return os.environ.get("AGENTFLOW_THREAD_ID") or None


def _thread_checkpoint_anchor() -> "str | None":
    return os.environ.get("AGENTFLOW_THREAD_CHECKPOINT") or None


def _threads_db_path() -> "Path | None":
    ws = os.environ.get("AGENTFLOW_WORKSPACE_DIR")
    if not ws:
        return None
    try:
        p = Path(ws)
        p.mkdir(parents=True, exist_ok=True)
        return p / "threads.db"
    except Exception:
        return None


def _thread_checkpointer():
    """The durable ``AsyncSqliteSaver`` for this run's conversation, or ``None``.

    Best-effort: returns ``None`` (→ classic stateless run) when this isn't a
    chat run (no ``AGENTFLOW_THREAD_ID`` / workspace) or the checkpoint package
    is unavailable — a persistence failure must never fail a run. Cached per
    workspace-db path so a warm worker reuses one connection across jobs."""
    if not _thread_id():
        return None
    db_path = _threads_db_path()
    if db_path is None:
        return None
    key = str(db_path)
    saver = _THREAD_CHECKPOINTERS.get(key)
    if saver is not None:
        return saver
    try:
        import asyncio
        import aiosqlite
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        # get_agent() is always called from inside the runner's event loop
        # (asyncio.run(_main()) one-shot, or the worker's _LOOP), and the runner
        # applies nest_asyncio — so run_until_complete on the live loop is safe.
        loop = asyncio.get_event_loop()
        conn = loop.run_until_complete(aiosqlite.connect(key))

        async def _prep():
            # WAL + busy_timeout so concurrent conversations of the SAME script
            # (separate subprocess, shared threads.db) don't collide on writes.
            await conn.execute("PRAGMA journal_mode=WAL")
            await conn.execute("PRAGMA busy_timeout=5000")

        loop.run_until_complete(_prep())
        saver = AsyncSqliteSaver(conn)
        _THREAD_CHECKPOINTERS[key] = saver
        return saver
    except Exception as e:
        print(f"[agentflow] conversation thread persistence unavailable: {e}",
              file=sys.stderr)
        return None


# Per-turn model-input token budget. The FULL thread is always persisted; this
# only bounds what the model SEES each turn so a long chat can't overflow the
# context window. The system prompt is always kept (skill menu lives there), and
# a recently-read skill stays in-window.
_THREAD_MAX_TOKENS = 24000


def _make_trim_hook():
    """A ``create_react_agent`` ``pre_model_hook`` that bounds the per-turn model
    input to the most recent ``_THREAD_MAX_TOKENS`` tokens while ALWAYS keeping
    the system message. Returns ``llm_input_messages`` (ephemeral) so the full
    thread stays persisted — nothing is permanently dropped; a later turn
    re-trims from the complete history. Returns ``None`` if ``trim_messages`` is
    unavailable (older langchain-core) → no hook, unbounded (old behavior)."""
    try:
        from langchain_core.messages.utils import (
            trim_messages, count_tokens_approximately,
        )
    except Exception:
        return None

    budget = _THREAD_MAX_TOKENS
    try:
        budget = int(os.environ.get("AGENTFLOW_THREAD_MAX_TOKENS") or budget)
    except Exception:
        pass

    def _hook(state):
        msgs = state.get("messages") if isinstance(state, dict) else None
        if not msgs:
            return {}
        try:
            trimmed = trim_messages(
                msgs,
                max_tokens=budget,
                token_counter=count_tokens_approximately,
                strategy="last",
                include_system=True,
                start_on="human",
                allow_partial=False,
            )
            if trimmed and len(trimmed) < len(msgs):
                return {"llm_input_messages": trimmed}
        except Exception:
            pass
        return {}

    return _hook


def _agent_checkpointer(agent):
    """The checkpointer an agent was compiled with (None if stateless)."""
    return getattr(agent, "checkpointer", None)


def _is_human_message(m) -> bool:
    if isinstance(m, (tuple, list)) and m:
        return str(m[0]).lower() in ("human", "user")
    return type(m).__name__ in ("HumanMessage", "HumanMessageChunk")


def _latest_turn(messages):
    """In threaded mode the checkpointer already holds the prior turns, so we
    send only the CURRENT turn — every message from the last human message
    onward. This makes a script that still prepends ``history`` (``history +
    [new]``) correct automatically: the prepended history is dropped and the
    checkpointer supplies it, so context is never counted twice."""
    if not isinstance(messages, list) or not messages:
        return messages
    for i in range(len(messages) - 1, -1, -1):
        if _is_human_message(messages[i]):
            return messages[i:]
    return messages


def get_agent(
    system_prompt: str | None = None,
    llm_name: str = "default",
    tools: list | None = None,
    reasoning=None,
    stream_reasoning: bool = False,
    checkpointer=None,
):
    """
    Return a ready-to-use ReAct agent (LangGraph create_react_agent).

    The agent has all platform-configured tools pre-loaded (web_fetch,
    web_search, and any MCP server tools). Pass `tools` to override.

    `stream_reasoning=True` auto-surfaces the model's chain-of-thought in the chat
    UI as a `<think>` block — the platform handles it, so your streaming loop needs
    no reasoning logic (see `get_llm`). Pair with `reasoning=`.

    Conversation threading (automatic in /converse): when the run belongs to a
    conversation the agent gets a durable checkpointer keyed by the conversation
    id, so its full state — including a skill's body once read, and every tool
    result — persists across turns. The agent reads a bound skill ONCE instead of
    every turn, and multi-turn memory just works. Drive it with `stream_agent`,
    which sends only the new message (the checkpointer supplies the history) — so
    you don't prepend `input["history"]`. Pass `checkpointer=False` to opt out
    (classic stateless agent), or a saver instance to bring your own.

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

    llm = get_llm(llm_name, reasoning=reasoning, stream_reasoning=stream_reasoning)
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

    params = inspect.signature(create_react_agent).parameters
    _has_varkw = any(p.kind == p.VAR_KEYWORD for p in params.values())

    def _accepts(k: str) -> bool:
        return _has_varkw or k in params

    # ── Durable conversation threading ────────────────────────────────────────
    # `checkpointer`:  None → auto (attach when this is a chat run:
    # AGENTFLOW_THREAD_ID set); False → force the classic stateless agent; a
    # saver instance → use it. When a checkpointer is active the agent's full
    # state persists across turns, so a bound skill is read ONCE, not per turn.
    if checkpointer is False:
        saver = None
    elif checkpointer is not None:
        saver = checkpointer
    else:
        saver = _thread_checkpointer()

    extra: dict = {}
    if saver is not None and _accepts("checkpointer"):
        extra["checkpointer"] = saver
        hook = _make_trim_hook() if _accepts("pre_model_hook") else None
        if hook is not None:
            extra["pre_model_hook"] = hook
    threaded = "checkpointer" in extra

    if threaded:
        # Threaded path: use a STATIC system prompt (a string → prepended
        # SystemMessage), NOT a callable that reads state["messages"] — a
        # callable would re-inject the FULL untrimmed history and defeat the
        # pre_model_hook trim. The trim hook governs the model input; the
        # SystemMessage is always kept.
        if system_prompt:
            if "prompt" in params:
                extra["prompt"] = system_prompt
            elif "state_modifier" in params:
                extra["state_modifier"] = system_prompt
        return create_react_agent(llm, agent_tools, **extra)

    # ── Classic stateless path (unchanged) ────────────────────────────────────
    if not system_prompt:
        return create_react_agent(llm, agent_tools)

    # Parameter was renamed across LangGraph versions:
    #   < 0.2.x  → state_modifier
    #   >= 0.2.x → prompt
    from langchain_core.messages import SystemMessage
    def _prompt_fn(state):
        msgs = state["messages"] if isinstance(state, dict) else list(state)
        return [SystemMessage(content=system_prompt)] + msgs

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
    stream_reasoning: bool = False,
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

    ``reasoning=`` / ``stream_reasoning=True`` behave as on ``get_agent`` (see
    ``get_llm``): the latter auto-surfaces the chain-of-thought as a ``<think>``
    block with no reasoning logic in your script.

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

    llm = get_llm(llm_name, reasoning=reasoning, stream_reasoning=stream_reasoning)
    if llm is None:
        raise RuntimeError(
            "No LLM configured. Add one in AgentFlow Settings before calling get_deep_agent()."
        )

    # create_deep_agent's parameter names vary across versions; introspect first
    # so we can tell whether deepagents will handle skills NATIVELY.
    params = inspect.signature(create_deep_agent).parameters
    accepts_kwargs = any(p.kind == p.VAR_KEYWORD for p in params.values())

    def _supports(key: str) -> bool:
        return accepts_kwargs or key in params

    run_dir = os.environ.get("AGENTFLOW_RUN_DIR")
    have_skills_dir = bool(run_dir and (Path(run_dir) / "skills").is_dir())
    # deepagents' own SkillsMiddleware (activated by passing skills=[...] with a
    # mounted backend) already injects the bound-skill list + progressive-
    # disclosure "read_file the SKILL.md path (limit=1000)" guidance into the
    # system prompt on every turn. When it's active, adding OUR read_skill tool +
    # skill preamble on top is not just redundant — it hands the model a second,
    # CONFLICTING way to read a skill (read_skill-by-name vs read_file-by-path),
    # and because our read_skill returns the whole SKILL.md as one blob, deepagents
    # offloads it to /large_tool_results and makes the model read_file it back (a
    # clunky double read that looks like the agent "keeps re-reading the skill").
    # So let deepagents own the skill UX here; only fall back to read_skill/preamble
    # when it can't (older deepagents without `skills=`, or no backend mount).
    native_skills = bool(have_skills_dir and _supports("backend") and _supports("skills"))

    call: dict = {"model": llm, **kwargs}

    # Durable conversation threading (same as get_agent): attach a checkpointer
    # keyed by the conversation id so the deep agent's state persists across
    # turns. Only when this is a chat run, the caller didn't bring their own, and
    # this deepagents build accepts `checkpointer`. deepagents owns its own
    # context management, so we don't add a trim hook here.
    if "checkpointer" not in call and _supports("checkpointer"):
        saver = _thread_checkpointer()
        if saver is not None:
            call["checkpointer"] = saver

    merged_tools = list(tools) if tools else []
    if not native_skills:
        # Fallback path: advertise skills in the prompt + expose read_skill,
        # exactly like get_agent() (deepagents won't do it for us on this build).
        preamble = _skill_preamble()
        if preamble:
            system_prompt = f"{system_prompt}\n\n{preamble}" if system_prompt else preamble
        skill_tool = _make_skill_tool()
        if skill_tool is not None and not any(
            getattr(t, "name", "") == "read_skill" for t in merged_tools
        ):
            merged_tools.append(skill_tool)

    if system_prompt:
        # newer deepagents: `system_prompt`; classic: `instructions`.
        if "system_prompt" in params:
            call.setdefault("system_prompt", system_prompt)
        elif "instructions" in params:
            call.setdefault("instructions", system_prompt)
        elif accepts_kwargs:
            call.setdefault("system_prompt", system_prompt)

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
    virtual = False
    if run_dir and _supports("backend"):
        be_params = inspect.signature(FilesystemBackend).parameters
        be_kwargs = {"root_dir": str(run_dir)}
        if "virtual_mode" in be_params:
            be_kwargs["virtual_mode"] = True
            virtual = True
        call.setdefault("backend", FilesystemBackend(**be_kwargs))
    if native_skills:
        # Virtual backend → virtual source path; otherwise the real path (POSIX).
        src = "/skills" if virtual else str(Path(run_dir) / "skills")
        call.setdefault("skills", [src])

    return create_deep_agent(**call)


# ── Agent answer streaming (correct-by-construction) ───────────────────────────

def _ai_message_text(chunk) -> str:
    """Answer text carried by a streamed message — **only** when it is an AI
    message.

    ``agent.stream(..., stream_mode="messages")`` yields *every* message the graph
    produces: AI messages (the answer), **ToolMessages (raw tool output)**, and
    intermediate human/system messages. Emitting a ToolMessage's content as answer
    text is the classic bug where a tool's raw output — a ``bash``/CLI dump, a JSON
    blob, a file's contents — gets spliced into the chat bubble (e.g. a ``python``
    tool returning ``56088`` ends up glued to the front of the real reply). We keep
    only AI text here.

    Filtering by **message type** (not by ``langgraph_node`` name) is deliberate:
    the model node is called ``"agent"`` in a ReAct agent but ``"model"`` in a deep
    agent (plus middleware nodes), so a node-name filter silently breaks on
    ``get_deep_agent()``. The type check works across both and every middleware.

    Reasoning (Anthropic ``thinking`` blocks / DeepSeek ``reasoning_content``) is
    intentionally excluded — the platform surfaces it as a ``<think>`` block when
    ``stream_reasoning=True``; it must never enter the reply.
    """
    # Match by class name to avoid an eager langchain import / version skew.
    # AIMessage(Chunk) → keep; ToolMessage / HumanMessage / SystemMessage → drop.
    if type(chunk).__name__ not in ("AIMessageChunk", "AIMessage"):
        return ""
    content = getattr(chunk, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # provider content blocks (e.g. Anthropic)
        return "".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") in (None, "text")
        )
    return ""


def _thread_run_config(agent, messages, thread_id, checkpoint_id):
    """Resolve the LangGraph run config + the messages to send for a threaded
    agent. Threading applies only when a thread id is in effect AND the agent was
    compiled with a checkpointer — otherwise a plain (stateless) run, unchanged.

    Returns ``(config, messages)``. When threaded, ``messages`` is reduced to the
    current turn (the checkpointer supplies the history) and ``config`` carries
    the thread id (+ optional checkpoint anchor to resume / roll back from)."""
    tid = thread_id if thread_id is not None else _thread_id()
    if not tid or _agent_checkpointer(agent) is None:
        return None, messages
    cp = checkpoint_id if checkpoint_id is not None else _thread_checkpoint_anchor()
    cfg: dict = {"thread_id": str(tid)}
    if cp:
        cfg["checkpoint_id"] = str(cp)
    reduced = messages if isinstance(messages, dict) else _latest_turn(messages)
    return {"configurable": cfg}, reduced


async def stream_agent(
    agent, messages, *, stream: bool = True, thread_id=None, checkpoint_id=None,
) -> str:
    """Stream a LangChain/LangGraph agent's answer to the chat UI **correctly**,
    and return the full reply string.

    This is the recommended way to drive ``get_agent()`` / ``get_deep_agent()`` from
    a chat script. It runs the agent with ``stream_mode="messages"`` but emits (via
    ``token()``) **only the model's answer text** — tool results and other non-AI
    messages are dropped, so a tool's raw output never leaks into the reply. It
    works the same for a ReAct agent and a deep agent (see ``_ai_message_text``),
    replacing the hand-rolled ``for chunk, meta in agent.stream(...)`` loop that is
    easy to get wrong (that yields tool messages too, and the ``langgraph_node``
    filter people reach for breaks on deep agents).

    Chain-of-thought is **not** part of the reply: pass ``stream_reasoning=True`` to
    ``get_agent`` / ``get_deep_agent`` and the platform renders it as a collapsible
    ``<think>`` block automatically.

    Args:
        agent:    an object returned by ``get_agent()`` / ``get_deep_agent()``.
        messages: the chat messages — a list of ``(role, content)`` tuples or
                  message objects — or a full state dict ``{"messages": [...]}``.
        stream:   ``False`` runs to completion without live tokens and returns only
                  the final (tool-filtered) answer.
        thread_id / checkpoint_id: usually omitted — for a chat run they default
                  from the conversation env (``AGENTFLOW_THREAD_ID`` /
                  ``AGENTFLOW_THREAD_CHECKPOINT``). When a thread is in effect and
                  the agent has a checkpointer, only the *current* turn is sent
                  (the checkpointer holds the history), so prepending
                  ``input["history"]`` is harmless — it's dropped automatically.

    Returns:
        The full answer text (the same string that was streamed).

    Example::

        async def run(input: dict) -> dict:
            agent = get_agent(system_prompt=SYS, stream_reasoning=True)
            # Threaded in /converse: send only the new message; the checkpointer
            # supplies prior turns. (Prepending input["history"] also works — it's
            # deduplicated automatically.)
            reply = await stream_agent(agent, [("human", input["message"])])
            return {"reply": reply}
    """
    config, messages = _thread_run_config(agent, messages, thread_id, checkpoint_id)
    state = messages if isinstance(messages, dict) else {"messages": messages}
    if stream:
        parts: list[str] = []
        async for chunk, _meta in agent.astream(state, config=config, stream_mode="messages"):
            text = _ai_message_text(chunk)
            if text:
                token(text)
                parts.append(text)
        if parts:
            return "".join(parts)
        # Some agent configs don't stream token-by-token → fall back to the result.
    result = await agent.ainvoke(state, config=config)
    msgs = result.get("messages") if isinstance(result, dict) else None
    return _ai_message_text(msgs[-1]) if msgs else ""


def stream_agent_sync(
    agent, messages, *, stream: bool = True, thread_id=None, checkpoint_id=None,
) -> str:
    """Synchronous ``stream_agent()`` for a sync ``def run(input)``.

    Same filtering and return contract; uses ``agent.stream()`` / ``agent.invoke()``
    instead of the async variants. Prefer the async :func:`stream_agent` in an
    ``async def run``.

    Conversation threading works here too: it defaults from the conversation env
    like :func:`stream_agent`. Because the durable checkpointer is async-only
    (aiosqlite), a threaded agent is driven through the async path via the
    runner's event loop (``nest_asyncio`` makes this reentrant); a plain
    (non-threaded) agent keeps the sync ``.stream()`` / ``.invoke()`` path.
    """
    tid = thread_id if thread_id is not None else _thread_id()
    cp = _agent_checkpointer(agent)
    if tid and cp is not None and type(cp).__name__ == "AsyncSqliteSaver":
        import asyncio
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(
            stream_agent(agent, messages, stream=stream,
                         thread_id=thread_id, checkpoint_id=checkpoint_id)
        )

    config, messages = _thread_run_config(agent, messages, thread_id, checkpoint_id)
    state = messages if isinstance(messages, dict) else {"messages": messages}
    if stream:
        parts: list[str] = []
        for chunk, _meta in agent.stream(state, config=config, stream_mode="messages"):
            text = _ai_message_text(chunk)
            if text:
                token(text)
                parts.append(text)
        if parts:
            return "".join(parts)
    result = agent.invoke(state, config=config)
    msgs = result.get("messages") if isinstance(result, dict) else None
    return _ai_message_text(msgs[-1]) if msgs else ""
