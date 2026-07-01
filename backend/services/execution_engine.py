"""
Execution engine:
  - writes user script files to disk
  - generates a _runner_<id>.py wrapper
  - runs it in the script's venv (subprocess, non-blocking)
  - streams structured __AGENTFLOW__ events + raw stdout/stderr via WebSocket
  - persists logs & final status to DB
  - concurrency-limited via asyncio.Semaphore (AGENTFLOW_MAX_CONCURRENT, default 5)
  - per-execution timeout via AGENTFLOW_EXECUTION_TIMEOUT (default 600s)
  - queued/retry status tracking
"""
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import BACKEND_ROOT
from app.database import SessionLocal
from app.models import Execution, ExecutionLog, Script, UploadedFile
from services.file_storage import UPLOADS_DIR, blob_path
from services.script_files import script_file_path
from services.venv_manager import get_script_dir, get_venv_python, venv_exists, _clean_env

_PREFIX = "__AGENTFLOW__"

MAX_CONCURRENT: int = int(os.getenv("AGENTFLOW_MAX_CONCURRENT", "5"))
EXECUTION_TIMEOUT: float = float(os.getenv("AGENTFLOW_EXECUTION_TIMEOUT", "600"))

# Lightweight timing diagnostics printed to the backend console (uvicorn / F5),
# so a slow run can be split into queue-wait / prep / python-cold-start-imports /
# script(LLM) without digging through the per-run logs in the DB. The heavy,
# usually-dominant cost is `cold_import` — every run spawns a fresh python that
# re-imports the whole langchain/langgraph stack (there is no warm worker pool).
# Toggle off with AGENTFLOW_PROFILE=0.
_PROFILE: bool = os.getenv("AGENTFLOW_PROFILE", "1").lower() not in ("0", "false", "no", "")


def _prof(execution_id: str, msg: str) -> None:
    if _PROFILE:
        print(f"[agentflow] [{execution_id[:8]}] {msg}", flush=True)

# lazy-init so it's created inside the running event loop
_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    return _semaphore


# ── WebSocket connection manager ───────────────────────────────────────────────

class _WsManager:
    def __init__(self, buffer_size: int = 2000):
        self._conns: dict[str, set] = {}
        self._buffers: dict[str, deque] = {}
        self._buffer_size = buffer_size

    async def connect(self, eid: str, ws) -> None:
        self._conns.setdefault(eid, set()).add(ws)
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
        self._buffers.pop(eid, None)
        self._conns.pop(eid, None)


ws_manager = _WsManager()
install_manager = _WsManager()

# active subprocess handles: execution_id -> Popen
_procs: dict[str, subprocess.Popen] = {}

# strong refs so background tasks aren't garbage-collected mid-run
_tasks: set[asyncio.Task] = set()


def spawn_execution(execution_id: str) -> asyncio.Task:
    """Schedule start_execution while keeping a strong reference."""
    task = asyncio.create_task(start_execution(execution_id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task


def queue_stats() -> dict:
    """Return current concurrency usage (best-effort, in-process view)."""
    sem = _semaphore
    running = MAX_CONCURRENT - (sem._value if sem else MAX_CONCURRENT)
    running = max(0, running)
    # DB query for accurate queued count is done in the router; return what we know locally
    return {"max_concurrent": MAX_CONCURRENT, "running_slots_used": running}


# ── File-reference resolution ──────────────────────────────────────────────────

_FILE_MARKER = "__agentflow_file__"


def _resolve_file_refs(value: Any, db) -> Any:
    """Walk input_data recursively; replace any {"$file": "<id>"} with a marker
    dict that the runner converts into an AgentFlowFile object.

    Returns the rewritten value. Unknown file ids raise ValueError so the caller
    can surface a clear error before launching the subprocess.
    """
    if isinstance(value, dict):
        # treat {"$file": "<id>"} as a leaf, not a regular dict
        if set(value.keys()) == {"$file"} and isinstance(value["$file"], str):
            file_id = value["$file"]
            row = db.query(UploadedFile).filter_by(id=file_id).first()
            if not row:
                raise ValueError(f"file ref {{$file: {file_id!r}}} not found")
            bp = blob_path(file_id)
            return {
                _FILE_MARKER: True,
                "id": row.id,
                "name": row.original_name,
                "mime": row.mime or "",
                "size": row.size,
                "path": str(bp).replace("\\", "/"),
            }
        return {k: _resolve_file_refs(v, db) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_file_refs(v, db) for v in value]
    return value


# ── Wrapper generation ─────────────────────────────────────────────────────────

def _safe_skill_dirname(name: str) -> str:
    """Turn a skill's display name into a filesystem-safe directory name."""
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", (name or "").strip()).strip("-.")
    return slug or "skill"


def _write_runner(
    script_dir: Path,
    run_dir: Path,
    entry_fn: str,
    execution_id: str,
    llm_envs: dict,
) -> tuple[Path, Path]:
    backend_root = str(BACKEND_ROOT).replace("\\", "/")
    script_dir_s = str(script_dir).replace("\\", "/")
    input_file = run_dir / "_input.json"
    input_path = str(input_file).replace("\\", "/")

    runner = run_dir / "_runner.py"
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

# Silence noisy third-party loggers that write INFO to stderr (captured as [ERR] by the platform).
import logging as _logging
for _noisy in ("mcp", "httpx", "httpcore", "openai", "anthropic"):
    _logging.getLogger(_noisy).setLevel(_logging.WARNING)

async def _main():

    import agentflow as _af
    # Signal that python cold-start + base imports are done, so the engine can
    # split process-boot cost from script(LLM) cost. Unknown event type -> the
    # engine's drain loop ignores it (never shown in the Logs panel).
    _emit({{"type": "boot"}})

    # Zero-intrusion execution tracing: emits __AGENTFLOW__ trace events
    # for every LangGraph node, tool call, and agent action. User scripts
    # don't have to do anything.
    try:
        from agentflow._tracer import install as _install_tracer
        _install_tracer()
    except Exception as _exc:
        print(f"[agentflow] tracer install failed: {{_exc}}", file=sys.stderr)

    _mcp = json.loads(os.environ.get("AGENTFLOW_MCP_CONFIGS", "{{}}"))

    async def _run():
        spec = importlib.util.spec_from_file_location("user_script", r"{script_dir_s}/main.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules["user_script"] = mod
        spec.loader.exec_module(mod)

        fn = getattr(mod, "{entry_fn}")
        inp = json.loads(Path(r"{input_path}").read_text(encoding="utf-8"))
        # Convert {{"__agentflow_file__": true, ...}} markers (planted by the engine
        # when resolving {{"$file": "<id>"}} refs) into AgentFlowFile objects.
        inp = _af._hydrate_file_refs(inp)
        result = await fn(inp) if inspect.iscoroutinefunction(fn) else fn(inp)
        _emit({{"type": "result", "data": result
            if isinstance(result, (dict, list, str, int, float, bool, type(None)))
            else str(result)}})

    if _mcp:
        try:
            from langchain_mcp_adapters.client import MultiServerMCPClient
            _client = MultiServerMCPClient(_mcp)
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
    slot_acquired = False
    _t_enter = time.perf_counter()
    _t_slot = _t_spawn = _t_enter
    try:
        exc_row: Execution = db.query(Execution).filter_by(id=execution_id).first()
        if not exc_row:
            return
        script: Script = db.query(Script).filter_by(id=exc_row.script_id).first()
        if not script:
            return

        # ── mark queued, then wait for a concurrency slot ─────────────────────
        exc_row.status = "queued"
        exc_row.queued_at = datetime.utcnow()
        db.commit()
        await ws_manager.send(execution_id, {"type": "status", "status": "queued"})

        await _get_semaphore().acquire()
        slot_acquired = True
        _t_slot = time.perf_counter()

        # re-read: may have been cancelled while waiting in queue
        db.refresh(exc_row)
        if exc_row.status == "cancelled":
            return

        # ── re-load script inside same session ────────────────────────────────
        script = db.query(Script).filter_by(id=exc_row.script_id).first()
        if not script:
            return

        # ── write script files to disk ────────────────────────────────────────
        script_dir = get_script_dir(exc_row.script_id)
        for f in script.files:
            target = script_file_path(script_dir, f.filename)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f.content, encoding="utf-8")

        # ── per-execution working directory (cwd) + persistent workspace ──────
        run_dir = script_dir / "runs" / execution_id
        run_dir.mkdir(parents=True, exist_ok=True)
        workspace_dir = script_dir / "workspace"
        workspace_dir.mkdir(parents=True, exist_ok=True)

        # Mirror the user's own files into the run dir (which is the cwd), so the
        # intuitive `open("data.txt")` works: the file tree the user sees in the
        # editor is materialized right next to their running code. run_dir is
        # per-execution, so every run gets a clean isolated copy and anything the
        # script writes stays out of the source tree (script_dir). The runtime
        # files written afterwards (_runner.py / _input.json / skills/) win on any
        # name clash. (Files are also written to script_dir above for imports /
        # venv / persistence; this is the read-from-cwd copy.)
        for f in script.files:
            try:
                dest = script_file_path(run_dir, f.filename)
            except ValueError:
                continue  # skip names that would escape the run dir
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(f.content, encoding="utf-8")

        # ── resolve {"$file": "<id>"} refs in input_data before persisting ────
        try:
            resolved_input = _resolve_file_refs(exc_row.input_data or {}, db)
        except ValueError as e:
            _mark_failed(db, execution_id, str(e))
            await ws_manager.send(execution_id, {
                "type": "status", "status": "failed", "error": str(e),
            })
            return

        # ── build LLM env vars from channels ──────────────────────────────────
        # Each model name is served by AGENTFLOW_LLM_<NORM(model)>. When several
        # enabled channels serve the same model, the highest-priority one wins
        # (ties → earliest created). The default model (get_llm() with no name)
        # is whichever channel was flagged is_default.
        from app.models import Channel, MCPServerConfig, Secret, SearchConfig
        import re
        def _norm(name: str) -> str:
            return re.sub(r"[^A-Z0-9]+", "_", (name or "").upper()).strip("_") or "UNNAMED"

        llm_envs: dict[str, str] = {}
        channels = db.query(Channel).filter(Channel.enabled == True).all()  # noqa: E712
        ranked = sorted(
            channels,
            key=lambda c: (-(c.priority or 0), c.created_at or datetime.min),
        )
        chosen: dict[str, "Channel"] = {}
        for ch in ranked:
            for model in (ch.models or []):
                chosen.setdefault(model, ch)   # first (highest-priority) wins

        def _blob(model: str, ch) -> str:
            return json.dumps({
                "name": model,
                "provider": ch.provider,
                "model": model,
                "api_key": ch.api_key,
                "base_url": ch.base_url,
                "extra_config": ch.extra_config or {},
            })

        for model, ch in chosen.items():
            llm_envs[f"AGENTFLOW_LLM_{_norm(model)}"] = _blob(model, ch)
        llm_envs["AGENTFLOW_LLM_NAMES"] = json.dumps(list(chosen.keys()))

        default_model = next(
            (c.default_model for c in channels if c.is_default and c.default_model), None
        )
        if default_model and default_model in chosen:
            llm_envs["AGENTFLOW_LLM_DEFAULT"] = _blob(default_model, chosen[default_model])

        # ── build MCP server configs ──────────────────────────────────────────
        # build_connection() also refreshes + injects OAuth bearer tokens so the
        # headless runner only ever sees a static Authorization header.
        from services.mcp_config import build_connection
        selected_ids: list[str] = script.mcp_server_ids or []
        mcp_configs: dict[str, dict] = {}
        if selected_ids:
            for srv in db.query(MCPServerConfig).filter(
                MCPServerConfig.id.in_(selected_ids),
                MCPServerConfig.enabled == True,  # noqa: E712
            ).all():
                mcp_configs[srv.name] = build_connection(srv, db)
        llm_envs["AGENTFLOW_MCP_CONFIGS"] = json.dumps(mcp_configs)

        # ── materialize bound skills + build the skill manifest ───────────────
        # Skills live on disk at backend/data/skills/<dir>/ (services/skill_store).
        # Each enabled skill the script opts into (script.skill_ids holds the skill
        # *directory names*) is copied into run_dir/skills/<safe-name>/ and advertised
        # to the agent via AGENTFLOW_SKILLS (name+description+dir). get_agent() folds
        # the manifest into the system prompt and reads a skill's SKILL.md on demand
        # via read_skill; get_deep_agent() browses the copied files directly. We copy
        # (rather than point at the canonical folder) so both agent modes see skills
        # under run_dir and the agent can't mutate the stored skill.
        from services import skill_store
        skill_ids: list[str] = script.skill_ids or []
        skills_root = run_dir / "skills"
        skill_manifest: list[dict] = []
        for dir_name in skill_ids:
            entry = skill_store.manifest_entry(dir_name)
            if not entry:
                continue  # unknown / disabled skill — skip silently
            safe = _safe_skill_dirname(dir_name)
            sk_dir = skills_root / safe
            shutil.copytree(
                entry["dir"], sk_dir,
                ignore=shutil.ignore_patterns(skill_store.SIDECAR, ".git", "__pycache__"),
                dirs_exist_ok=True,
            )
            skill_manifest.append({
                "name": entry["name"],
                "description": entry["description"],
                "dir": str(sk_dir),
                "main": entry["main"],
            })
        llm_envs["AGENTFLOW_SKILLS"] = json.dumps(skill_manifest)

        # ── build externally-managed secret env vars ──────────────────────────
        # Read by agentflow.get_secret("<key>") as AGENTFLOW_SECRET_<NORM(key)>.
        # These go ONLY into the subprocess env below — deliberately NOT passed to
        # _write_runner(), so secret values never get baked into the on-disk
        # _runner.py file. Global by design (single-admin model, no tenancy).
        secret_envs: dict[str, str] = {}
        secret_rows = db.query(Secret).all()
        for sec in secret_rows:
            secret_envs[f"AGENTFLOW_SECRET_{_norm(sec.key)}"] = sec.value or ""
        secret_envs["AGENTFLOW_SECRET_NAMES"] = json.dumps([s.key for s in secret_rows])

        # ── build web-search provider config ──────────────────────────────────
        # Read by agentflow._make_builtin_tools() (web_search / web_fetch). Goes
        # into secret_envs (subprocess-only) so the Tavily key is never baked
        # into the on-disk _runner.py. DuckDuckGo is the always-on fallback, so
        # an unconfigured deployment still works.
        search_cfg = db.query(SearchConfig).filter_by(id="default").first()
        search_provider = (search_cfg.provider if search_cfg else "tavily") or "tavily"
        search_blob = {"provider": search_provider}
        if search_cfg and search_cfg.tavily_api_key:
            search_blob["tavily_api_key"] = search_cfg.tavily_api_key
        secret_envs["AGENTFLOW_SEARCH_CONFIG"] = json.dumps(search_blob)

        # expose paths to user scripts via env (read by agentflow.paths)
        llm_envs["AGENTFLOW_RUN_DIR"] = str(run_dir)
        llm_envs["AGENTFLOW_WORKSPACE_DIR"] = str(workspace_dir)
        llm_envs["AGENTFLOW_SCRIPT_DIR"] = str(script_dir)
        llm_envs["AGENTFLOW_UPLOADS_DIR"] = str(UPLOADS_DIR)

        # ── write runner + input ──────────────────────────────────────────────
        runner, input_file = _write_runner(
            script_dir, run_dir, script.entry_function, execution_id, llm_envs,
        )
        input_file.write_text(json.dumps(resolved_input), encoding="utf-8")

        py = get_venv_python(exc_row.script_id) if venv_exists(exc_row.script_id) else Path(sys.executable)

        exc_row.status = "running"
        exc_row.started_at = datetime.utcnow()
        db.commit()

        await ws_manager.send(execution_id, {"type": "status", "status": "running"})

        diag_msg = (
            f"LLM models: {list(chosen.keys()) or 'none'}; "
            f"default={default_model or 'none'}; "
            f"MCP servers: {list(mcp_configs.keys()) or 'none'}; "
            f"skills: {[s['name'] for s in skill_manifest] or 'none'}; "
            f"secrets: {[s.key for s in secret_rows] or 'none'}; "
            f"search: {search_provider}"
            + (" (tavily key set)" if search_blob.get("tavily_api_key") else "")
        )
        _persist_log(db, execution_id, {"level": "debug", "message": diag_msg, "step": "_engine"})
        await ws_manager.send(execution_id, {
            "type": "log", "level": "debug", "message": diag_msg,
            "step": "_engine", "timestamp": datetime.utcnow().isoformat(),
        })

        sub_env = _clean_env()
        sub_env["PYTHONUNBUFFERED"] = "1"
        sub_env["PYTHONIOENCODING"] = "utf-8"
        sub_env.setdefault("LANGCHAIN_TRACING_V2", "false")
        sub_env.setdefault("LANGSMITH_TRACING", "false")
        sub_env.update(llm_envs)
        # Secrets last, subprocess-only: never written into the on-disk runner.
        sub_env.update(secret_envs)

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        popen_kwargs = {}
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

        proc = subprocess.Popen(
            [str(py), str(runner)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(run_dir),
            env=sub_env,
            bufsize=1,
            text=True,
            encoding="utf-8",
            errors="replace",
            **popen_kwargs,
        )
        _procs[execution_id] = proc
        _t_spawn = time.perf_counter()
        _prof(execution_id, (
            f"spawned pid={proc.pid} "
            f"(queue_wait={_t_slot - _t_enter:.2f}s, prep={_t_spawn - _t_slot:.2f}s, "
            f"venv={'yes' if venv_exists(exc_row.script_id) else 'no→backend-py'})"
        ))

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
        first_output_at: float | None = None
        result_at: float | None = None

        async def _drain():
            nonlocal result_data, error_data, eof_count, first_output_at, result_at
            while eof_count < 2:
                is_stderr, line = await queue.get()
                if line is None:
                    eof_count += 1
                    continue
                if first_output_at is None:
                    first_output_at = time.perf_counter()
                    _prof(execution_id, (
                        f"first output +{first_output_at - _t_spawn:.2f}s "
                        f"(python cold-start + imports)"
                    ))
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
                    elif t == "token":
                        await ws_manager.send(execution_id, {
                            "type": "token",
                            "content": payload.get("content", ""),
                        })
                    elif t == "trace":
                        # persist so historical runs can re-render the flow
                        _persist_log(db, execution_id, {
                            "level": "_trace",
                            "message": payload.get("name", ""),
                            "data": payload,
                            "step": payload.get("kind"),
                        })
                        await ws_manager.send(execution_id, {
                            **payload,
                            "timestamp": datetime.utcnow().isoformat(),
                        })
                    elif t == "artifact":
                        # persisted so historical runs can re-render in Artifacts tab
                        _persist_log(db, execution_id, {
                            "level": "_artifact",
                            "message": payload.get("kind", ""),
                            "data": payload,
                            "step": payload.get("kind"),
                        })
                        await ws_manager.send(execution_id, {
                            **payload,
                            "timestamp": datetime.utcnow().isoformat(),
                        })
                    elif t == "graph":
                        _persist_log(db, execution_id, {
                            "level": "_graph",
                            "message": "graph",
                            "data": payload,
                        })
                        await ws_manager.send(execution_id, payload)
                    elif t == "result":
                        result_data = payload.get("data")
                        result_at = time.perf_counter()
                    elif t == "error":
                        error_data = payload
                        # Persist the crash as a log too, so it shows in the Logs
                        # panel (live + on reload) — not only in execution.error /
                        # a transient toast. The full traceback goes in the message
                        # (whitespace-preserved), the short message in step.
                        err_msg = payload.get("traceback") or payload.get("message") or "Execution failed"
                        _persist_log(db, execution_id, {
                            "level": "error", "message": err_msg, "step": "error",
                        })
                        await ws_manager.send(execution_id, {
                            "type": "log", "level": "error", "message": err_msg,
                            "step": "error", "timestamp": datetime.utcnow().isoformat(),
                        })
                else:
                    level = "error" if is_stderr else "raw"
                    _persist_log(db, execution_id, {"level": level, "message": line})
                    await ws_manager.send(execution_id, {
                        "type": "log",
                        "level": level,
                        "message": line,
                        "timestamp": datetime.utcnow().isoformat(),
                    })

        try:
            await asyncio.wait_for(_drain(), timeout=EXECUTION_TIMEOUT)
        except asyncio.TimeoutError:
            proc.terminate()
            try:
                await asyncio.wait_for(asyncio.to_thread(proc.wait), timeout=5.0)
            except asyncio.TimeoutError:
                proc.kill()
            _procs.pop(execution_id, None)

            timeout_msg = f"Execution timed out after {EXECUTION_TIMEOUT:.0f}s"
            _prof(execution_id, (
                f"TIMEOUT after {EXECUTION_TIMEOUT:.0f}s | "
                f"cold_import={'n/a' if first_output_at is None else f'{first_output_at - _t_spawn:.2f}s'} "
                f"(no result before timeout)"
            ))
            exc_row = db.query(Execution).filter_by(id=execution_id).first()
            exc_row.status = "failed"
            exc_row.error = timeout_msg
            exc_row.finished_at = datetime.utcnow()
            db.commit()
            _persist_log(db, execution_id, {"level": "error", "message": timeout_msg, "step": "_engine"})
            await ws_manager.send(execution_id, {
                "type": "log", "level": "error", "message": timeout_msg,
                "step": "_engine", "timestamp": datetime.utcnow().isoformat(),
            })
            await ws_manager.send(execution_id, {
                "type": "status", "status": "failed", "error": timeout_msg,
            })
            _schedule_ws_cleanup(execution_id)
            return

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
            else:
                # Process died without emitting a structured error (e.g. sys.exit(),
                # SIGKILL/OOM, or a native crash). Without this the run would be
                # marked failed with a completely empty error — nothing in Logs,
                # Output or Flow. Synthesize a message from the exit code so the
                # failure is at least visible and traceable.
                synth = (
                    f"Process exited with code {proc.returncode} without reporting an "
                    f"error (possibly sys.exit(), a killed/out-of-memory process, or a "
                    f"native crash). Check the raw output above for details."
                )
                exc_row.error = synth
                _persist_log(db, execution_id, {
                    "level": "error", "message": synth, "step": "_engine",
                })
                await ws_manager.send(execution_id, {
                    "type": "log", "level": "error", "message": synth,
                    "step": "_engine", "timestamp": datetime.utcnow().isoformat(),
                })
        db.commit()

        _t_end = time.perf_counter()
        if first_output_at is not None:
            _cold = first_output_at - _t_spawn
            _script = (result_at or _t_end) - first_output_at
        else:
            _cold = _t_end - _t_spawn      # process produced no output at all
            _script = 0.0
        _prof(execution_id, (
            f"done status={exc_row.status} rc={proc.returncode} | "
            f"queue_wait={_t_slot - _t_enter:.2f}s prep={_t_spawn - _t_slot:.2f}s "
            f"cold_import={_cold:.2f}s script={_script:.2f}s total={_t_end - _t_slot:.2f}s"
        ))

        await ws_manager.send(execution_id, {
            "type": "status",
            "status": exc_row.status,
            "output": result_data,
            "error": exc_row.error,
        })

        # ── auto-retry on failure ─────────────────────────────────────────────
        if exc_row.status == "failed" and exc_row.retry_count < exc_row.max_retries:
            await _schedule_retry(exc_row)

        # leave run_dir intact for post-mortem inspection; prune old runs
        try:
            runner.unlink(missing_ok=True)
            input_file.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            _prune_old_runs(script_dir, keep=20)
        except Exception:
            pass
        # prune old execution *rows* (DB) per the script's retention setting
        try:
            prune_executions(db, script.id, script.max_executions)
        except Exception:
            pass

    except asyncio.CancelledError:
        _mark_cancelled(db, execution_id)
        await ws_manager.send(execution_id, {"type": "status", "status": "cancelled"})
    except Exception as e:
        _mark_failed(db, execution_id, str(e))
        await ws_manager.send(execution_id, {"type": "status", "status": "failed", "error": str(e)})
    finally:
        if slot_acquired:
            _get_semaphore().release()
        _procs.pop(execution_id, None)
        db.close()
        _schedule_ws_cleanup(execution_id)


async def _schedule_retry(failed_row: Execution) -> None:
    """Spawn a new Execution row as a retry of the given failed one."""
    db = SessionLocal()
    try:
        retry_exc = Execution(
            script_id=failed_row.script_id,
            input_data=failed_row.input_data,
            max_retries=failed_row.max_retries,
            retry_count=failed_row.retry_count + 1,
        )
        db.add(retry_exc)
        db.commit()
        db.refresh(retry_exc)
        retry_id = retry_exc.id
        retry_num = retry_exc.retry_count
    finally:
        db.close()

    msg = f"Auto-retry {retry_num}/{failed_row.max_retries} → new execution {retry_id}"
    db2 = SessionLocal()
    try:
        _persist_log(db2, failed_row.id, {"level": "info", "message": msg, "step": "_engine"})
    finally:
        db2.close()
    await ws_manager.send(failed_row.id, {
        "type": "log", "level": "info", "message": msg,
        "step": "_engine", "timestamp": datetime.utcnow().isoformat(),
    })
    spawn_execution(retry_id)


def _prune_old_runs(script_dir: Path, keep: int) -> None:
    """Keep only the `keep` most recently modified subdirs under script_dir/runs/."""
    runs_dir = script_dir / "runs"
    if not runs_dir.is_dir():
        return
    entries = [p for p in runs_dir.iterdir() if p.is_dir()]
    entries.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    import shutil as _shutil
    for stale in entries[keep:]:
        _shutil.rmtree(stale, ignore_errors=True)


def _schedule_ws_cleanup(execution_id: str) -> None:
    try:
        loop = asyncio.get_event_loop()
        loop.call_later(300, ws_manager.cleanup, execution_id)
    except RuntimeError:
        pass


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
    # Persist the engine-level failure as a log so it surfaces in the Logs panel
    # (on reload) instead of being buried only in execution.error.
    try:
        _persist_log(db, execution_id, {
            "level": "error", "message": error or "Execution failed", "step": "_engine",
        })
    except Exception:
        pass


# ── Execution-record retention ───────────────────────────────────────────────

def delete_run_dir(script_id: str, execution_id: str) -> None:
    """Remove the per-execution working dir (best-effort)."""
    try:
        run_dir = get_script_dir(script_id) / "runs" / execution_id
        shutil.rmtree(run_dir, ignore_errors=True)
    except Exception:
        pass


def prune_executions(db, script_id: str, keep: int | None) -> int:
    """Delete the oldest execution rows for a script beyond `keep`, keeping the
    `keep` most recent. In-flight runs (running/queued/pending) are never deleted
    and don't count against the limit. Returns how many rows were removed.

    keep <= 0 (or None) means unlimited — nothing is pruned.
    """
    if not keep or keep <= 0:
        return 0
    rows = (
        db.query(Execution)
        .filter(Execution.script_id == script_id)
        .order_by(Execution.created_at.desc())
        .all()
    )
    # Only terminal runs are candidates for deletion; keep the newest `keep` of them.
    terminal = [r for r in rows if r.status in ("completed", "failed", "cancelled")]
    stale = terminal[keep:]
    removed = 0
    for r in stale:
        delete_run_dir(script_id, r.id)
        db.delete(r)  # cascade removes ExecutionLog rows
        removed += 1
    if removed:
        db.commit()
    return removed
