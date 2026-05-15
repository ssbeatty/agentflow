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
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import BACKEND_ROOT
from app.database import SessionLocal
from app.models import Execution, ExecutionLog, Script
from services.venv_manager import get_script_dir, get_venv_python, venv_exists

_PREFIX = "__AGENTFLOW__"

# ── WebSocket connection manager ───────────────────────────────────────────────

class _WsManager:
    def __init__(self):
        # execution_id -> set of websockets
        self._conns: dict[str, set] = {}

    async def connect(self, eid: str, ws) -> None:
        self._conns.setdefault(eid, set()).add(ws)

    def disconnect(self, eid: str, ws) -> None:
        bucket = self._conns.get(eid, set())
        bucket.discard(ws)

    async def send(self, eid: str, msg: dict) -> None:
        dead = set()
        for ws in list(self._conns.get(eid, set())):
            try:
                await ws.send_json(msg)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self._conns.get(eid, set()).discard(ws)


ws_manager = _WsManager()

# install job connections: job_key -> set of websockets
install_manager = _WsManager()

# active subprocess handles: execution_id -> Process
_procs: dict[str, asyncio.subprocess.Process] = {}

# ── Wrapper generation ─────────────────────────────────────────────────────────

def _write_runner(script_dir: Path, entry_fn: str, execution_id: str, llm_envs: dict) -> Path:
    backend_root = str(BACKEND_ROOT).replace("\\", "/")
    script_dir_s = str(script_dir).replace("\\", "/")
    input_file = script_dir / f"_input_{execution_id}.json"

    runner = script_dir / f"_runner_{execution_id}.py"
    runner.write_text(
        f'''import sys, os, json, traceback
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

try:
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "user_script", r"{script_dir_s}/main.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["user_script"] = mod
    spec.loader.exec_module(mod)

    fn = getattr(mod, "{entry_fn}")
    inp = json.loads(Path(r"{str(input_file).replace(chr(92), '/')}").read_text(encoding="utf-8"))
    result = fn(inp)

    _emit({{"type": "result", "data": result
        if isinstance(result, (dict, list, str, int, float, bool, type(None)))
        else str(result)}})

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
            (script_dir / f.filename).write_text(f.content, encoding="utf-8")

        # ── build LLM env vars ────────────────────────────────────────────────
        from app.models import LLMConfig
        llm_envs: dict[str, str] = {}
        llms = db.query(LLMConfig).all()
        for llm in llms:
            key = f"AGENTFLOW_LLM_{llm.name.upper()}"
            llm_envs[key] = json.dumps({
                "provider": llm.provider,
                "model": llm.model,
                "api_key": llm.api_key,
                "base_url": llm.base_url,
                "extra_config": llm.extra_config or {},
            })
            if llm.is_default:
                llm_envs["AGENTFLOW_LLM_DEFAULT"] = llm_envs[key]

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

        proc = await asyncio.create_subprocess_exec(
            str(py), str(runner),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(script_dir),
        )
        _procs[execution_id] = proc

        result_data: Any = None
        error_data: dict | None = None

        async def _read(stream, is_stderr: bool):
            nonlocal result_data, error_data
            async for raw in stream:
                line = raw.decode("utf-8", errors="replace").rstrip()
                if not line:
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

        await asyncio.gather(_read(proc.stdout, False), _read(proc.stderr, True))
        await proc.wait()

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


async def stop_execution(execution_id: str) -> bool:
    proc = _procs.get(execution_id)
    if not proc:
        return False
    proc.terminate()
    try:
        await asyncio.wait_for(proc.wait(), timeout=5.0)
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
