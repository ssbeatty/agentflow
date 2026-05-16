"""
Execution engine:
  - writes user script files to disk
  - generates a _runner_<id>.py wrapper
  - runs it in the script's venv (subprocess, non-blocking)
  - streams structured __AGENTFLOW__ events + raw stdout/stderr via WebSocket
  - persists logs & final status to DB
"""
import asyncio
import json
import os
import subprocess
import sys
import threading
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import BACKEND_ROOT
from app.database import SessionLocal
from app.models import Execution, ExecutionLog, Script
from services.script_files import script_file_path
from services.venv_manager import get_script_dir, get_venv_python, venv_exists, _clean_env

_PREFIX = "__AGENTFLOW__"

# ── WebSocket connection manager ───────────────────────────────────────────────

class _WsManager:
    def __init__(self, buffer_size: int = 2000):
        # execution_id -> set of websockets
        self._conns: dict[str, set] = {}
        # execution_id -> deque of past messages (so late-joiners can replay)
        self._buffers: dict[str, deque] = {}
        self._buffer_size = buffer_size

    async def connect(self, eid: str, ws) -> None:
        self._conns.setdefault(eid, set()).add(ws)
        # replay buffered messages on (re)connect
        for msg in list(self._buffers.get(eid, ())):
            try:
                await ws.send_json(msg)
            except Exception:
                return

    def disconnect(self, eid: str, ws) -> None:
        bucket = self._conns.get(eid, set())
        bucket.discard(ws)

    async def send(self, eid: str, msg: dict) -> None:
        buf = self._buffers.setdefault(eid, deque(maxlen=self._buffer_size))
        buf.append(msg)
        dead = set()
        for ws in list(self._conns.get(eid, set())):
            try:
                await ws.send_json(msg)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self._conns.get(eid, set()).discard(ws)

    def cleanup(self, eid: str) -> None:
        """Drop buffer once nobody needs replay (call after a delay)."""
        self._buffers.pop(eid, None)
        self._conns.pop(eid, None)


ws_manager = _WsManager()

# install job connections: job_key -> set of websockets
install_manager = _WsManager()

# active subprocess handles: execution_id -> Popen
_procs: dict[str, subprocess.Popen] = {}

# hold strong refs so background tasks aren't garbage-collected mid-run
_tasks: set[asyncio.Task] = set()


def spawn_execution(execution_id: str) -> asyncio.Task:
    """Schedule start_execution while keeping a strong reference."""
    task = asyncio.create_task(start_execution(execution_id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task

# ── Wrapper generation ─────────────────────────────────────────────────────────

def _write_runner(script_dir: Path, entry_fn: str, execution_id: str, llm_envs: dict) -> Path:
    backend_root = str(BACKEND_ROOT).replace("\\", "/")
    script_dir_s = str(script_dir).replace("\\", "/")
    input_file = script_dir / f"_input_{execution_id}.json"
    input_path = str(input_file).replace("\\", "/")

    runner = script_dir / f"_runner_{execution_id}.py"
    runner.write_text(
        f'''import sys, os, json, traceback, asyncio, inspect
import importlib.util
from pathlib import Path

sys.path.insert(0, r"{backend_root}")
sys.path.insert(0, r"{script_dir_s}")
os.environ["AGENTFLOW_EXECUTION_ID"] = "{execution_id}"
''' +
        "".join(f'os.environ[{k!r}] = {v!r}\n' for k, v in llm_envs.items()) +
        f'''
_P = "{_PREFIX}"

def _emit(d):
    print(_P + json.dumps(d, ensure_ascii=False), flush=True)

# Allow nested asyncio.run() so sync LangGraph .invoke() can call tools inside our async runner.
try:
    import nest_asyncio
    nest_asyncio.apply()
except ImportError:
    pass

async def _main():
    import agentflow as _af

    _mcp = json.loads(os.environ.get("AGENTFLOW_MCP_CONFIGS", "{{}}"))

    async def _run():
        spec = importlib.util.spec_from_file_location("user_script", r"{script_dir_s}/main.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules["user_script"] = mod
        spec.loader.exec_module(mod)

        fn = getattr(mod, "{entry_fn}")
        inp = json.loads(Path(r"{input_path}").read_text(encoding="utf-8"))
        result = await fn(inp) if inspect.iscoroutinefunction(fn) else fn(inp)
        _emit({{"type": "result", "data": result
            if isinstance(result, (dict, list, str, int, float, bool, type(None)))
            else str(result)}})

    if _mcp:
        try:
            from langchain_mcp_adapters.client import MultiServerMCPClient
            async with MultiServerMCPClient(_mcp) as _client:
                _af._injected_tools = await _client.get_tools()
                await _run()
        except ImportError:
            print("[agentflow] langchain-mcp-adapters not installed; MCP tools unavailable", file=sys.stderr)
            await _run()
    else:
        await _run()

try:
    asyncio.run(_main())
except SystemExit as e:
    sys.exit(e.code or 0)
except Exception as exc:
    _emit({{"type": "error", "message": str(exc), "traceback": traceback.format_exc()}})
    sys.exit(1)
''',
        encoding="utf-8",
    )
    return runner, input_file


# ── Main runner ────────────────────────────────────────────────────────────────

async def start_execution(execution_id: str) -> None:
    db = SessionLocal()
    try:
        exc_row: Execution = db.query(Execution).filter_by(id=execution_id).first()
        if not exc_row:
            return
        script: Script = db.query(Script).filter_by(id=exc_row.script_id).first()
        if not script:
            return

        # ── write script files to disk ────────────────────────────────────────
        script_dir = get_script_dir(exc_row.script_id)
        for f in script.files:
            target = script_file_path(script_dir, f.filename)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f.content, encoding="utf-8")

        # ── build LLM env vars ────────────────────────────────────────────────
        from app.models import LLMConfig, MCPServerConfig
        import re
        def _norm(name: str) -> str:
            # POSIX-safe env var key: uppercase, non-alphanumeric -> _
            return re.sub(r"[^A-Z0-9]+", "_", (name or "").upper()).strip("_") or "UNNAMED"

        llm_envs: dict[str, str] = {}
        llm_names: list[str] = []   # original names, for discovery
        llms = db.query(LLMConfig).all()
        for llm in llms:
            payload = json.dumps({
                "name": llm.name,
                "provider": llm.provider,
                "model": llm.model,
                "api_key": llm.api_key,
                "base_url": llm.base_url,
                "extra_config": llm.extra_config or {},
            })
            llm_envs[f"AGENTFLOW_LLM_{_norm(llm.name)}"] = payload
            llm_names.append(llm.name)
            if llm.is_default:
                llm_envs["AGENTFLOW_LLM_DEFAULT"] = payload
        llm_envs["AGENTFLOW_LLM_NAMES"] = json.dumps(llm_names)

        # ── build MCP server configs ──────────────────────────────────────────
        mcp_configs: dict[str, dict] = {}
        for srv in db.query(MCPServerConfig).filter_by(enabled=True).all():
            cfg: dict = {"transport": srv.transport}
            if srv.url:
                cfg["url"] = srv.url
            if srv.command:
                cfg["command"] = srv.command
            if srv.args:
                cfg["args"] = srv.args
            if srv.env_vars:
                cfg["env"] = srv.env_vars
            if srv.headers:
                cfg["headers"] = srv.headers
            mcp_configs[srv.name] = cfg
        llm_envs["AGENTFLOW_MCP_CONFIGS"] = json.dumps(mcp_configs)

        # ── write runner + input ──────────────────────────────────────────────
        runner, input_file = _write_runner(script_dir, script.entry_function, execution_id, llm_envs)
        input_file.write_text(json.dumps(exc_row.input_data or {}), encoding="utf-8")

        # ── pick python ───────────────────────────────────────────────────────
        py = get_venv_python(exc_row.script_id) if venv_exists(exc_row.script_id) else Path(sys.executable)

        # ── update DB status ──────────────────────────────────────────────────
        exc_row.status = "running"
        exc_row.started_at = datetime.utcnow()
        db.commit()

        await ws_manager.send(execution_id, {"type": "status", "status": "running"})

        # diagnostic log so users can see which LLM/MCP configs are wired up
        diag_msg = (
            f"LLM configs: {[llm.name for llm in llms]}; "
            f"default={'yes' if any(l.is_default for l in llms) else 'no'}; "
            f"MCP servers: {list(mcp_configs.keys()) or 'none'}"
        )
        _persist_log(db, execution_id, {"level": "debug", "message": diag_msg, "step": "_engine"})
        await ws_manager.send(execution_id, {
            "type": "log", "level": "debug", "message": diag_msg,
            "step": "_engine", "timestamp": datetime.utcnow().isoformat(),
        })

        sub_env = _clean_env()
        sub_env["PYTHONUNBUFFERED"] = "1"
        sub_env["PYTHONIOENCODING"] = "utf-8"
        # langsmith / langchain telemetry off by default (faster cold imports,
        # no surprise network calls). User can override in their own script.
        sub_env.setdefault("LANGCHAIN_TRACING_V2", "false")
        sub_env.setdefault("LANGSMITH_TRACING", "false")
        sub_env.update(llm_envs)

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        popen_kwargs = {}
        if sys.platform == "win32":
            # detach from parent console so CTRL_C (e.g. uvicorn --reload)
            # doesn't kill the user script.
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

        proc = subprocess.Popen(
            [str(py), str(runner)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(script_dir),
            env=sub_env,
            bufsize=1,
            text=True,
            encoding="utf-8",
            errors="replace",
            **popen_kwargs,
        )
        _procs[execution_id] = proc

        def _pump(stream, is_stderr: bool):
            try:
                for line in iter(stream.readline, ""):
                    line = line.rstrip("\r\n")
                    if not line:
                        continue
                    loop.call_soon_threadsafe(queue.put_nowait, (is_stderr, line))
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, (is_stderr, None))

        threading.Thread(target=_pump, args=(proc.stdout, False), daemon=True).start()
        threading.Thread(target=_pump, args=(proc.stderr, True), daemon=True).start()

        result_data: Any = None
        error_data: dict | None = None
        eof_count = 0

        while eof_count < 2:
            is_stderr, line = await queue.get()
            if line is None:
                eof_count += 1
                continue
            if line.startswith(_PREFIX):
                try:
                    payload = json.loads(line[len(_PREFIX):])
                except json.JSONDecodeError:
                    continue
                t = payload.get("type")
                if t == "log":
                    _persist_log(db, execution_id, payload)
                    await ws_manager.send(execution_id, {
                        "type": "log",
                        "level": payload.get("level", "info"),
                        "message": payload.get("message", ""),
                        "data": payload.get("data"),
                        "step": payload.get("step"),
                        "timestamp": datetime.utcnow().isoformat(),
                    })
                elif t == "result":
                    result_data = payload.get("data")
                elif t == "error":
                    error_data = payload
            else:
                level = "error" if is_stderr else "raw"
                _persist_log(db, execution_id, {"level": level, "message": line})
                await ws_manager.send(execution_id, {
                    "type": "log",
                    "level": level,
                    "message": line,
                    "timestamp": datetime.utcnow().isoformat(),
                })

        await asyncio.to_thread(proc.wait)

        exc_row = db.query(Execution).filter_by(id=execution_id).first()
        exc_row.finished_at = datetime.utcnow()
        if proc.returncode == 0:
            exc_row.status = "completed"
            exc_row.output_data = result_data
        else:
            exc_row.status = "failed"
            if error_data:
                exc_row.error = error_data.get("traceback") or error_data.get("message")
        db.commit()

        await ws_manager.send(execution_id, {
            "type": "status",
            "status": exc_row.status,
            "output": result_data,
            "error": exc_row.error,
        })

        # cleanup temp files
        try:
            runner.unlink(missing_ok=True)
            input_file.unlink(missing_ok=True)
        except Exception:
            pass

    except asyncio.CancelledError:
        _mark_cancelled(db, execution_id)
        await ws_manager.send(execution_id, {"type": "status", "status": "cancelled"})
    except Exception as e:
        _mark_failed(db, execution_id, str(e))
        await ws_manager.send(execution_id, {"type": "status", "status": "failed", "error": str(e)})
    finally:
        _procs.pop(execution_id, None)
        db.close()
        # keep replay buffer around briefly so a reconnect after status=completed
        # still sees the final logs, then drop it
        asyncio.get_event_loop().call_later(
            300, ws_manager.cleanup, execution_id
        )


async def stop_execution(execution_id: str) -> bool:
    proc = _procs.get(execution_id)
    if not proc:
        return False
    proc.terminate()
    try:
        await asyncio.wait_for(asyncio.to_thread(proc.wait), timeout=5.0)
    except asyncio.TimeoutError:
        proc.kill()
    return True


# ── Helpers ────────────────────────────────────────────────────────────────────

def _persist_log(db, execution_id: str, payload: dict) -> None:
    entry = ExecutionLog(
        execution_id=execution_id,
        level=payload.get("level", "info"),
        message=payload.get("message", ""),
        data=payload.get("data"),
        step=payload.get("step"),
    )
    db.add(entry)
    db.commit()


def _mark_cancelled(db, execution_id: str) -> None:
    row = db.query(Execution).filter_by(id=execution_id).first()
    if row:
        row.status = "cancelled"
        row.finished_at = datetime.utcnow()
        db.commit()


def _mark_failed(db, execution_id: str, error: str) -> None:
    row = db.query(Execution).filter_by(id=execution_id).first()
    if row:
        row.status = "failed"
        row.error = error
        row.finished_at = datetime.utcnow()
        db.commit()
