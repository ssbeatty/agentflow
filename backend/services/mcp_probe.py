"""Probe an MCP server: connect, run the handshake, list its tools.

Used by the ``POST /api/mcp-servers/{id}/probe`` endpoint so the UI can show
whether a server actually works and what tools it exposes — *before* a script
ever runs.

Why a dedicated thread + fresh event loop:
  - The probe must work for every transport, including ``stdio``, which spawns a
    subprocess. On Windows, ``asyncio`` subprocess support requires a
    ``ProactorEventLoop``; some debuggers install a ``SelectorEventLoop`` that
    raises ``NotImplementedError`` on subprocess creation (see CLAUDE.md). Running
    the probe in its own thread with an explicit Proactor loop isolates it from
    whatever loop uvicorn/debugpy happens to be using.
  - It also keeps the (blocking) probe off the request event loop entirely; the
    FastAPI endpoint is declared ``def`` so it runs in the threadpool.

The MCP client lib lives in the backend venv (see ``requirements.txt``); if it's
missing we return a friendly, actionable error instead of crashing.
"""
from __future__ import annotations

import asyncio
import sys
import threading
from typing import Any


def _tool_to_dict(t: Any) -> dict:
    # mcp's Tool model field is ``inputSchema`` (camelCase); tolerate snake_case
    # in case of an older/newer SDK.
    schema = getattr(t, "inputSchema", None)
    if schema is None:
        schema = getattr(t, "input_schema", None)
    return {
        "name": getattr(t, "name", "") or "",
        "title": getattr(t, "title", None),
        "description": getattr(t, "description", "") or "",
        "input_schema": schema or {},
    }


def _flatten(e: BaseException) -> list[BaseException]:
    """Walk an exception tree (ExceptionGroup sub-exceptions + cause/context).

    The mcp/anyio stack wraps transport failures in a TaskGroup ``ExceptionGroup``;
    a bare ``str(group)`` hides the real error (and any ``401``), so we unwrap it.
    """
    seen: set[int] = set()
    out: list[BaseException] = []

    def walk(x: BaseException) -> None:
        if x is None or id(x) in seen:
            return
        seen.add(id(x))
        out.append(x)
        for sub in (getattr(x, "exceptions", None) or ()):  # ExceptionGroup
            walk(sub)
        for nxt in (x.__cause__, x.__context__):
            if nxt is not None:
                walk(nxt)

    walk(e)
    return out


def _classify_error(e: BaseException) -> dict:
    if isinstance(e, ModuleNotFoundError) and (getattr(e, "name", "") == "mcp" or "mcp" in str(e)):
        return {
            "ok": False,
            "tools": [],
            "error": "MCP SDK not installed in the backend venv. Run: pip install -r requirements.txt",
            "needs_auth": False,
        }

    nodes = _flatten(e)
    # Prefer leaf exceptions (no sub-group) for a concrete message.
    leaves = [n for n in nodes if not getattr(n, "exceptions", None)] or nodes

    status = None
    for n in nodes:
        resp = getattr(n, "response", None)
        code = getattr(resp, "status_code", None)
        if isinstance(code, int):
            status = code
            break

    combined = " ".join(f"{type(n).__name__}: {n}" for n in nodes).lower()
    needs_auth = (status in (401, 403)) or any(
        s in combined for s in ("401", "unauthorized", "403", "forbidden", "invalid_token")
    )

    def _useful(n: BaseException) -> bool:
        # Cancellation is bookkeeping noise from the torn-down TaskGroup, not the cause.
        return (
            str(n).strip() != ""
            and type(n).__name__ != "CancelledError"
            and "cancel scope" not in str(n).lower()
        )

    parts = [f"{type(n).__name__}: {n}" for n in leaves if _useful(n)]
    msg = "; ".join(dict.fromkeys(parts)) or f"{type(e).__name__}: {e}"
    if status:
        msg = f"HTTP {status}: {msg}"
    return {"ok": False, "tools": [], "error": msg[:600], "needs_auth": needs_auth}


async def _aprobe(cfg: dict, timeout: float) -> dict:
    from mcp import ClientSession

    transport = (cfg.get("transport") or "http").lower()

    async def _list(read, write) -> list[dict]:
        async with ClientSession(read, write) as session:
            await asyncio.wait_for(session.initialize(), timeout)
            resp = await asyncio.wait_for(session.list_tools(), timeout)
            return [_tool_to_dict(t) for t in resp.tools]

    if transport in ("http", "streamable_http", "streamable-http"):
        try:
            from mcp.client.streamable_http import streamablehttp_client as _client
        except ImportError:  # pragma: no cover - older SDK naming
            from mcp.client.streamable_http import streamable_http_client as _client
        async with _client(cfg["url"], headers=cfg.get("headers")) as streams:
            tools = await _list(streams[0], streams[1])

    elif transport == "sse":
        from mcp.client.sse import sse_client
        async with sse_client(cfg["url"], headers=cfg.get("headers")) as streams:
            tools = await _list(streams[0], streams[1])

    elif transport == "stdio":
        from mcp import StdioServerParameters
        from mcp.client.stdio import stdio_client
        params = StdioServerParameters(
            command=cfg["command"],
            args=cfg.get("args") or [],
            env=cfg.get("env") or None,
        )
        async with stdio_client(params) as streams:
            tools = await _list(streams[0], streams[1])

    elif transport == "websocket":
        from mcp.client.websocket import websocket_client
        async with websocket_client(cfg["url"]) as streams:
            tools = await _list(streams[0], streams[1])

    else:
        raise ValueError(f"unsupported transport: {transport!r}")

    return {"ok": True, "tools": tools, "error": None, "needs_auth": False}


def probe_server(cfg: dict, timeout: float = 20.0) -> dict:
    """Connect to one MCP server and list its tools.

    Returns ``{ok, tools: [{name, title, description, input_schema}], error, needs_auth}``.
    Never raises — failures are reported in the result dict.
    """
    result: dict = {}

    def _run() -> None:
        if sys.platform == "win32":
            loop = asyncio.ProactorEventLoop()
        else:
            loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result.update(loop.run_until_complete(_aprobe(cfg, timeout)))
        except BaseException as e:  # noqa: BLE001 - report everything to the caller
            result.update(_classify_error(e))
        finally:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:
                pass
            loop.close()

    t = threading.Thread(target=_run, name="mcp-probe", daemon=True)
    t.start()
    t.join(timeout + 15)
    if t.is_alive():
        return {
            "ok": False,
            "tools": [],
            "error": f"probe timed out after {timeout:.0f}s",
            "needs_auth": False,
        }
    return result or {"ok": False, "tools": [], "error": "probe produced no result", "needs_auth": False}
