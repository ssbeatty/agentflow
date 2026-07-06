"""
Zero-intrusion LangChain/LangGraph callback handler that emits structured
trace events to AgentFlow's frontend.

The handler is installed globally via `langchain_core.tracers.context.register_configure_hook`
so every chain/graph/agent invocation automatically picks it up — user scripts
need no changes.

Events emitted (each prefixed with __AGENTFLOW__ on stdout):

    {"type":"trace","kind":"node","phase":"start|end|error",
     "name":"agent","run_id":"...","parent_run_id":"...","step":3,
     "input":{...},"output":{...},"error":"...","ts":1234567890.123}

    {"type":"trace","kind":"tool"|"skill"|"agent_action"|"agent_finish", ...}

    (`kind:"skill"` is a `tool` event whose call is a skill interaction — the
    built-in `read_skill` tool, or a deep-agent filesystem read under `skills/`.)

    {"type":"graph","mermaid":"graph TD; ..."}     # emitted once per graph
"""
from __future__ import annotations

import json
import sys
import threading
import time
from contextvars import ContextVar
from typing import Any
from uuid import UUID

_PREFIX = "__AGENTFLOW__"

# ── LLM token-usage accumulation ──────────────────────────────────────────────
# The tracer sees every LLM round-trip (on_llm_end), so it's the natural place to
# tally token usage across a whole run. Totals accumulate here; the runner reads
# them once at the end via get_usage_totals() and emits a single "usage" event
# that the engine persists onto the Execution row (powers the cost dashboard).
# Guarded by a lock: the handler is run_inline (usually single-threaded per run),
# but async agents can interleave callbacks, so keep the read-modify-write atomic.
_usage_lock = threading.Lock()
_usage_totals: dict[str, int] = {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0,
    "llm_calls": 0,
}


def _coerce_int(v: Any) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _extract_usage(response: Any) -> tuple[int, int, int]:
    """Pull (prompt, completion, total) token counts out of an LLMResult,
    normalizing across providers. Prefers per-message `usage_metadata` (the
    langchain-standard field set by ChatOpenAI/ChatAnthropic/…), summed across
    generations; falls back to `llm_output['token_usage']` (OpenAI) /
    `['usage']` (Anthropic). Missing/garbled usage → zeros (never raises)."""
    prompt = completion = total = 0
    try:
        for gen_list in (getattr(response, "generations", None) or []):
            for gen in (gen_list or []):
                msg = getattr(gen, "message", None)
                um = getattr(msg, "usage_metadata", None) if msg is not None else None
                if isinstance(um, dict):
                    prompt += _coerce_int(um.get("input_tokens"))
                    completion += _coerce_int(um.get("output_tokens"))
                    total += _coerce_int(um.get("total_tokens"))
    except Exception:
        pass
    if prompt or completion or total:
        return prompt, completion, (total or prompt + completion)
    try:
        llm_output = getattr(response, "llm_output", None)
        if isinstance(llm_output, dict):
            u = llm_output.get("token_usage") or llm_output.get("usage") or {}
            if isinstance(u, dict):
                prompt = _coerce_int(u.get("prompt_tokens") or u.get("input_tokens"))
                completion = _coerce_int(u.get("completion_tokens") or u.get("output_tokens"))
                total = _coerce_int(u.get("total_tokens")) or prompt + completion
    except Exception:
        pass
    return prompt, completion, total


def _accumulate_usage(response: Any) -> None:
    """Record one LLM round-trip: bump the call counter and add its tokens."""
    p, c, t = _extract_usage(response)
    with _usage_lock:
        _usage_totals["llm_calls"] += 1
        _usage_totals["prompt_tokens"] += p
        _usage_totals["completion_tokens"] += c
        _usage_totals["total_tokens"] += t


def get_usage_totals() -> dict[str, int]:
    """Snapshot of the run's accumulated token usage (read by the runner)."""
    with _usage_lock:
        return dict(_usage_totals)
_MAX_PAYLOAD = 262_144  # chars per node/tool input/output blob before truncation.
# This is a *safety ceiling*, not a display limit — it only exists so a pathological
# state (a giant document / embedding sitting in the graph state) can't push tens of
# MB through the WS and into the DB on every node step (the WS replay buffer holds
# every event in memory for 5 min). The old 4096 was far too aggressive: a normal
# multi-turn {messages:[...]} state blew past it, so "truncated" fired constantly in
# the common case. At 256KB it effectively never fires for real runs, while still
# bounding a runaway. When it does fire the payload becomes
# {__truncated__, preview, original_bytes}, which the Flow panel renders as readable
# (cut-off) JSON. The frontend collapses long-but-untruncated blobs visually anyway.
# LLM payloads get a higher ceiling (a single generation is one blob, not per-step).
_MAX_LLM_PAYLOAD = 1_000_000


def _emit(event: dict) -> None:
    print(_PREFIX + json.dumps(event, ensure_ascii=False, default=str), flush=True)


def _truncate(obj: Any, cap: int = _MAX_PAYLOAD) -> Any:
    """Make obj JSON-safe and cap its serialized size."""
    try:
        s = json.dumps(obj, ensure_ascii=False, default=_default)
    except Exception:
        s = str(obj)
    if len(s) <= cap:
        try:
            return json.loads(s)
        except Exception:
            return s
    return {"__truncated__": True, "preview": s[:cap], "original_bytes": len(s)}


def _flatten_chat_messages(messages: Any) -> list[dict]:
    """Convert LangChain `messages` (list[list[BaseMessage]]) into a flat
    list of {role, content} dicts so the frontend can render them readably."""
    out: list[dict] = []
    if not messages:
        return out
    for batch in messages:
        seq = batch if isinstance(batch, list) else [batch]
        for m in seq:
            role = getattr(m, "type", None) or getattr(m, "role", None) or "message"
            content = getattr(m, "content", None)
            if content is None:
                content = str(m)
            out.append({"role": role, "content": content})
    return out


def _extract_llm_output(response: Any) -> Any:
    """Best-effort: pull the text + any tool calls out of an LLMResult."""
    try:
        gens = getattr(response, "generations", None) or []
        if not gens or not gens[0]:
            return str(response)
        first = gens[0][0]
        text = getattr(first, "text", "") or ""
        msg = getattr(first, "message", None)
        msg_content = getattr(msg, "content", None) if msg is not None else None
        tool_calls = getattr(msg, "tool_calls", None) if msg is not None else None
        usage = None
        llm_output = getattr(response, "llm_output", None)
        if isinstance(llm_output, dict):
            usage = llm_output.get("token_usage") or llm_output.get("usage")
        result: dict = {"text": msg_content if msg_content else text}
        if tool_calls:
            result["tool_calls"] = tool_calls
        if usage:
            result["usage"] = usage
        return result
    except Exception:
        return str(response)


def _default(o: Any) -> Any:
    # langchain Message objects, pydantic models, etc.
    for attr in ("model_dump", "dict", "to_json"):
        fn = getattr(o, attr, None)
        if callable(fn):
            try:
                return fn()
            except Exception:
                continue
    if hasattr(o, "__dict__"):
        return {k: v for k, v in vars(o).items() if not k.startswith("_")}
    return str(o)


def _is_langgraph_node(metadata: dict | None) -> bool:
    return bool(metadata and metadata.get("langgraph_node"))


# Filesystem-style tools a deep agent uses to read a skill's files.
_SKILL_FS_TOOLS = {"read_file", "read_files", "ls", "list_files", "list_dir", "glob", "grep", "view_file"}


def _is_skill_interaction(name: str, payload: Any) -> bool:
    """True when a tool call is really a skill being loaded — the built-in
    `read_skill` tool, or a deep-agent filesystem read whose path is under a
    `skills/` directory. Purely additive: a non-match stays a plain `tool`."""
    if name == "read_skill":
        return True
    if name in _SKILL_FS_TOOLS:
        try:
            blob = payload if isinstance(payload, str) else json.dumps(payload, default=str)
        except Exception:
            blob = str(payload)
        return "skills/" in blob or "/skills" in blob
    return False


def _node_name(metadata: dict | None, serialized: dict | None, default: str = "chain") -> str:
    if metadata and metadata.get("langgraph_node"):
        return str(metadata["langgraph_node"])
    if serialized:
        name = serialized.get("name") or (serialized.get("id") or [None])[-1]
        if name:
            return str(name)
    return default


try:
    from langchain_core.callbacks import BaseCallbackHandler  # type: ignore
except ImportError:  # pragma: no cover
    BaseCallbackHandler = object  # type: ignore


class AgentflowTracer(BaseCallbackHandler):
    """Filters LangChain callbacks down to events users actually want to see."""

    # Don't dedupe by ignoring the parent — we want to capture every node visit
    raise_error = False
    run_inline = True

    def __init__(self) -> None:
        self._starts: dict[str, float] = {}
        self._step = 0
        # run_id → "tool" | "skill", so on_tool_end pairs the same kind it started
        self._tool_kind: dict[str, str] = {}
        # (langgraph_step, node_name) → run_id that "owns" this slot. LangGraph
        # tags the conditional-edge routing function with the SOURCE node's
        # `langgraph_node` metadata, so without dedupe each branch evaluation
        # would emit a phantom second visit of the source node.
        self._step_node_owner: dict[tuple[int, str], str] = {}

    # ── helpers ─────────────────────────────────────────────────────────────
    def _start(self, kind: str, name: str, *, run_id: UUID, parent_run_id: UUID | None,
               input_data: Any = None, extra: dict | None = None) -> None:
        rid = str(run_id)
        self._starts[rid] = time.time()
        self._step += 1
        event = {
            "type": "trace",
            "kind": kind,
            "phase": "start",
            "name": name,
            "run_id": rid,
            "parent_run_id": str(parent_run_id) if parent_run_id else None,
            "step": self._step,
            "ts": time.time(),
        }
        if input_data is not None:
            event["input"] = _truncate(input_data)
        if extra:
            event.update(extra)
        _emit(event)

    def _end(self, kind: str, name: str, *, run_id: UUID, parent_run_id: UUID | None,
             output_data: Any = None, error: str | None = None, extra: dict | None = None) -> None:
        rid = str(run_id)
        started = self._starts.pop(rid, None)
        duration_ms = int((time.time() - started) * 1000) if started else None
        event = {
            "type": "trace",
            "kind": kind,
            "phase": "error" if error else "end",
            "name": name,
            "run_id": rid,
            "parent_run_id": str(parent_run_id) if parent_run_id else None,
            "duration_ms": duration_ms,
            "ts": time.time(),
        }
        if output_data is not None:
            event["output"] = _truncate(output_data)
        if error:
            event["error"] = error
        if extra:
            event.update(extra)
        _emit(event)

    # ── chain (LangGraph nodes ride this) ───────────────────────────────────
    def on_chain_start(self, serialized, inputs, *, run_id, parent_run_id=None,
                       tags=None, metadata=None, **kwargs):
        if not _is_langgraph_node(metadata):
            return
        name = _node_name(metadata, serialized)
        step = metadata.get("langgraph_step") if metadata else None
        # Dedupe: skip if we've already emitted this (step, node) — the second
        # event is the conditional-edge router running under the source node's tag.
        if step is not None:
            key = (step, name)
            existing = self._step_node_owner.get(key)
            if existing is not None and existing != str(run_id):
                return
            self._step_node_owner[key] = str(run_id)
        self._start(
            "node", name,
            run_id=run_id, parent_run_id=parent_run_id,
            input_data=inputs,
            extra={"langgraph_step": step},
        )

    def on_chain_end(self, outputs, *, run_id, parent_run_id=None, **kwargs):
        if str(run_id) not in self._starts:
            return  # we never started this one (filtered out)
        self._end("node", "", run_id=run_id, parent_run_id=parent_run_id, output_data=outputs)

    def on_chain_error(self, error, *, run_id, parent_run_id=None, **kwargs):
        if str(run_id) not in self._starts:
            return
        self._end("node", "", run_id=run_id, parent_run_id=parent_run_id, error=str(error))

    # ── LLM calls (chat + completion) ───────────────────────────────────────
    def on_chat_model_start(self, serialized, messages, *, run_id, parent_run_id=None,
                            invocation_params=None, metadata=None, **kwargs):
        name = (serialized or {}).get("name") or (invocation_params or {}).get("model") or "chat_model"
        extra: dict = {}
        ip = invocation_params or {}
        if ip.get("model"):
            extra["model"] = ip["model"]
        if ip.get("temperature") is not None:
            extra["temperature"] = ip["temperature"]
        self._start(
            "llm", str(name),
            run_id=run_id, parent_run_id=parent_run_id,
            input_data=_truncate(_flatten_chat_messages(messages), _MAX_LLM_PAYLOAD),
            extra=extra or None,
        )

    def on_llm_start(self, serialized, prompts, *, run_id, parent_run_id=None,
                     invocation_params=None, metadata=None, **kwargs):
        name = (serialized or {}).get("name") or (invocation_params or {}).get("model") or "llm"
        self._start(
            "llm", str(name),
            run_id=run_id, parent_run_id=parent_run_id,
            input_data=_truncate(prompts, _MAX_LLM_PAYLOAD),
        )

    def on_llm_end(self, response, *, run_id, parent_run_id=None, **kwargs):
        # Tally token usage for every LLM round-trip, even ones we didn't "start"
        # (filtered), so the run's cost total is complete.
        _accumulate_usage(response)
        if str(run_id) not in self._starts:
            return
        self._end(
            "llm", "",
            run_id=run_id, parent_run_id=parent_run_id,
            output_data=_truncate(_extract_llm_output(response), _MAX_LLM_PAYLOAD),
        )

    def on_llm_error(self, error, *, run_id, parent_run_id=None, **kwargs):
        if str(run_id) not in self._starts:
            return
        self._end("llm", "", run_id=run_id, parent_run_id=parent_run_id, error=str(error))

    # ── tool calls ──────────────────────────────────────────────────────────
    def on_tool_start(self, serialized, input_str, *, run_id, parent_run_id=None,
                      tags=None, metadata=None, inputs=None, **kwargs):
        name = (serialized or {}).get("name") or "tool"
        payload = inputs if inputs is not None else input_str
        kind = "skill" if _is_skill_interaction(name, payload) else "tool"
        self._tool_kind[str(run_id)] = kind
        self._start(
            kind, name,
            run_id=run_id, parent_run_id=parent_run_id,
            input_data=payload,
        )

    def on_tool_end(self, output, *, run_id, parent_run_id=None, **kwargs):
        kind = self._tool_kind.pop(str(run_id), "tool")
        self._end(kind, "", run_id=run_id, parent_run_id=parent_run_id, output_data=output)

    def on_tool_error(self, error, *, run_id, parent_run_id=None, **kwargs):
        kind = self._tool_kind.pop(str(run_id), "tool")
        self._end(kind, "", run_id=run_id, parent_run_id=parent_run_id, error=str(error))

    # ── legacy AgentExecutor (no langgraph_node metadata) ───────────────────
    def on_agent_action(self, action, *, run_id, parent_run_id=None, **kwargs):
        _emit({
            "type": "trace",
            "kind": "agent_action",
            "phase": "event",
            "name": getattr(action, "tool", "agent_action"),
            "run_id": str(run_id),
            "parent_run_id": str(parent_run_id) if parent_run_id else None,
            "ts": time.time(),
            "input": _truncate(getattr(action, "tool_input", None)),
            "log": _truncate(getattr(action, "log", None)),
        })

    def on_agent_finish(self, finish, *, run_id, parent_run_id=None, **kwargs):
        _emit({
            "type": "trace",
            "kind": "agent_finish",
            "phase": "event",
            "name": "agent_finish",
            "run_id": str(run_id),
            "parent_run_id": str(parent_run_id) if parent_run_id else None,
            "ts": time.time(),
            "output": _truncate(getattr(finish, "return_values", None)),
            "log": _truncate(getattr(finish, "log", None)),
        })


# ── installation ────────────────────────────────────────────────────────────

_var: ContextVar[AgentflowTracer | None] = ContextVar("agentflow_tracer", default=None)
_installed = False


def install() -> AgentflowTracer | None:
    """Install the tracer globally. Idempotent. Safe to call when LangChain isn't available."""
    global _installed
    if _installed:
        return _var.get()
    try:
        from langchain_core.tracers.context import register_configure_hook  # type: ignore
    except ImportError:
        return None
    tracer = AgentflowTracer()
    # `inheritable=True` propagates to child threads / async tasks
    register_configure_hook(_var, inheritable=True)
    _var.set(tracer)
    _installed = True

    _patch_pregel(tracer)
    return tracer


# ── monkey-patch LangGraph Pregel to capture compiled-graph topology ────────

_seen_graphs: set[int] = set()


def _patch_pregel(tracer: AgentflowTracer) -> None:
    """Wrap Pregel.invoke/ainvoke/stream/astream so the first call per compiled
    graph emits a `graph` event carrying its mermaid topology."""
    try:
        from langgraph.pregel import Pregel  # type: ignore
    except ImportError:
        return

    def _emit_topology(graph_obj: Any) -> None:
        gid = id(graph_obj)
        if gid in _seen_graphs:
            return
        _seen_graphs.add(gid)
        try:
            drawn = graph_obj.get_graph()
            mermaid = drawn.draw_mermaid()
            nodes = list(getattr(drawn, "nodes", {}).keys() if hasattr(drawn, "nodes") else [])
            _emit({
                "type": "graph",
                "graph_id": str(gid),
                "mermaid": mermaid,
                "nodes": nodes,
            })
        except Exception as exc:  # never let topology capture break a run
            print(f"[agentflow] topology capture failed: {exc}", file=sys.stderr)

    def _make_sync(orig):
        def wrapper(self, *args, **kwargs):
            _emit_topology(self)
            return orig(self, *args, **kwargs)
        wrapper._agentflow_patched = True  # type: ignore[attr-defined]
        return wrapper

    def _make_async(orig):
        async def wrapper(self, *args, **kwargs):
            _emit_topology(self)
            return await orig(self, *args, **kwargs)
        wrapper._agentflow_patched = True  # type: ignore[attr-defined]
        return wrapper

    def _make_async_iter(orig):
        async def wrapper(self, *args, **kwargs):
            _emit_topology(self)
            async for item in orig(self, *args, **kwargs):
                yield item
        wrapper._agentflow_patched = True  # type: ignore[attr-defined]
        return wrapper

    plan = [
        ("invoke", _make_sync),
        ("ainvoke", _make_async),
        ("stream", _make_sync),   # returns a generator; wrapping is fine
        ("astream", _make_async_iter),
    ]
    for method_name, factory in plan:
        orig = getattr(Pregel, method_name, None)
        if orig is None or getattr(orig, "_agentflow_patched", False):
            continue
        try:
            setattr(Pregel, method_name, factory(orig))
        except Exception as exc:
            print(f"[agentflow] could not patch Pregel.{method_name}: {exc}", file=sys.stderr)
