"""Warm worker pool — serverless-style per-script persistent interpreters.

WHY: every normal run spawns a fresh `python _runner.py` that re-imports the
whole langchain/langgraph/deepagents stack (the profiler's dominant `cold_import`
cost — there is otherwise no warm pool). A per-script worker stays alive between
runs, so run #2+ skips that import; `keep_warm` preheats the heavy stack so even
run #1 is warm.

DESIGN (see CLAUDE.md "warm worker" notes):
  - One long-lived subprocess per script, keyed by script_id. It boots once
    (imports agentflow + the user's main.py), then loops reading one job per line
    from stdin and streaming the same `__AGENTFLOW__` events back on stdout.
  - Serial per worker (an asyncio.Lock): one job at a time. Different scripts →
    different workers, still bounded by the engine's global concurrency
    semaphore.
  - Per-job config crosses via the job payload (env dict), NOT baked into any
    on-disk file — so nothing (secrets, LLM keys) is written to disk, and MOST
    config changes (MCP/skills/secrets) need NO restart. Only a **code** edit or
    a **venv** change retires a worker (invalidate_worker / a changed python
    path). Idle workers are reaped after a TTL.
  - Isolation is serverless-grade, not fresh-process: module globals persist
    across a worker's jobs (documented tradeoff). A script needing strict
    isolation sets `warm=False` and keeps the classic one-shot path.

GATING: the whole pool is a no-op unless AGENTFLOW_WARM_WORKERS is enabled AND
the script has warm=True. Default OFF → the platform behaves exactly as before.

The subprocess plumbing deliberately mirrors execution_engine (sync Popen +
reader threads + asyncio.Queue + call_soon_threadsafe + CREATE_NEW_PROCESS_GROUP
+ _clean_env) for the same Windows/debugpy reasons — do not swap in
asyncio.create_subprocess_exec.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Awaitable, Callable

from loguru import logger

from app.config import BACKEND_ROOT
from services import metrics
from services.venv_manager import (
    get_script_dir, get_venv_python, venv_exists, _clean_env,
    make_run_preexec, maybe_wrap_sandbox,
)

_PREFIX = "__AGENTFLOW__"


def _flag(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() not in ("0", "false", "no", "")


WARM_WORKERS_ENABLED: bool = _flag("AGENTFLOW_WARM_WORKERS", "0")
WORKER_IDLE_TTL: float = float(os.getenv("AGENTFLOW_WORKER_IDLE_TTL", "600"))       # evict after N idle seconds
WORKER_MAX_JOBS: int = int(os.getenv("AGENTFLOW_WORKER_MAX_JOBS", "0"))             # recycle after N jobs (0 = unlimited)
WORKER_BOOT_TIMEOUT: float = float(os.getenv("AGENTFLOW_WORKER_BOOT_TIMEOUT", "180"))
_REAP_INTERVAL: float = 60.0


class WorkerDied(Exception):
    """The worker process exited unexpectedly (crash / OOM / killed mid-job)."""


# ── the generated worker runner ─────────────────────────────────────────────

def _worker_runner_source(backend_root: str, script_dir: str, entry_fn: str) -> str:
    return f'''import sys, os, json, traceback, asyncio, inspect, importlib.util
from pathlib import Path

sys.path.insert(0, r"{backend_root}")
sys.path.insert(0, r"{script_dir}")

# agentflow.token()/log() decide whether to ALSO write raw text to stdout/stderr
# based on a module-level `_IN_PLATFORM = bool(os.environ.get("AGENTFLOW_EXECUTION_ID"))`
# evaluated ONCE at import time. The worker imports agentflow at boot — before any
# job's env (which carries the real execution id) has arrived — so we must mark
# "in platform" now. Otherwise token() double-emits: the `__AGENTFLOW__` protocol
# line AND a bare, newline-less `sys.stdout.write(content)` that glues onto the
# next protocol line and corrupts the stream. Each job overrides this with its
# real id via the job env (so _exec_id()/artifacts still work per run).
os.environ.setdefault("AGENTFLOW_EXECUTION_ID", "worker")

_P = "{_PREFIX}"
def _emit(d):
    print(_P + json.dumps(d, ensure_ascii=False), flush=True)

_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)
try:
    import nest_asyncio
    nest_asyncio.apply(_LOOP)
except Exception:
    pass

import logging as _logging
for _n in ("mcp", "httpx", "httpcore", "openai", "anthropic"):
    _logging.getLogger(_n).setLevel(_logging.WARNING)

import agentflow as _af
try:
    from agentflow._tracer import install as _install_tracer, reset_usage as _reset_usage, get_usage_totals as _gut
    _install_tracer()
except Exception as _e:
    def _reset_usage():
        pass
    def _gut():
        return {{}}
    print(f"[agentflow] tracer install failed: {{_e}}", file=sys.stderr)

# Import the user's module ONCE (a code edit invalidates the whole worker).
_spec = importlib.util.spec_from_file_location("user_script", r"{script_dir}/main.py")
_mod = importlib.util.module_from_spec(_spec)
sys.modules["user_script"] = _mod
_spec.loader.exec_module(_mod)

# Optional preheat: force the heavy stack into the module cache so run #1 is warm.
if os.environ.get("AGENTFLOW_PREHEAT") == "1":
    for _m in ("langchain_core", "langgraph", "langgraph.prebuilt", "langchain_openai"):
        try:
            __import__(_m)
        except Exception:
            pass

_emit({{"type": "worker_ready"}})

async def _run_one(job):
    env = job.get("env") or {{}}
    _keys = list(env.keys())
    for _k, _v in env.items():
        os.environ[_k] = _v
    run_dir = job["run_dir"]
    entry = job.get("entry_fn") or "{entry_fn}"
    try:
        os.chdir(run_dir)
    except Exception:
        pass
    # reset per-job global state so runs don't bleed into each other
    _af._injected_tools = None
    _reset_usage()
    ok = True
    try:
        _mcp = json.loads(os.environ.get("AGENTFLOW_MCP_CONFIGS", "{{}}"))
        if _mcp:
            try:
                from langchain_mcp_adapters.client import MultiServerMCPClient
                _client = MultiServerMCPClient(_mcp)
                _af._injected_tools = await _client.get_tools()
            except ImportError:
                print("[agentflow] langchain-mcp-adapters not installed; MCP tools unavailable", file=sys.stderr)
        fn = getattr(_mod, entry)
        inp = json.loads(Path(run_dir, "_input.json").read_text(encoding="utf-8"))
        inp = _af._hydrate_file_refs(inp)
        result = await fn(inp) if inspect.iscoroutinefunction(fn) else fn(inp)
        _emit({{"type": "result", "data": result
            if isinstance(result, (dict, list, str, int, float, bool, type(None)))
            else str(result)}})
    except Exception as exc:
        ok = False
        _emit({{"type": "error", "message": str(exc), "traceback": traceback.format_exc()}})
    finally:
        try:
            _u = _gut()
            if _u.get("llm_calls"):
                _emit({{"type": "usage", **_u}})
        except Exception:
            pass
        for _k in _keys:
            os.environ.pop(_k, None)
    return ok

for _line in sys.stdin:
    _line = _line.strip()
    if not _line:
        continue
    try:
        _job = json.loads(_line)
    except Exception:
        continue
    _jid = _job.get("job_id")
    try:
        _ok = _LOOP.run_until_complete(_run_one(_job))
    except Exception as _exc:
        _ok = False
        _emit({{"type": "error", "message": str(_exc), "traceback": traceback.format_exc()}})
    _emit({{"type": "job_done", "job_id": _jid, "ok": _ok}})
'''


# ── one worker ──────────────────────────────────────────────────────────────

class _Worker:
    def __init__(self, script_id: str, python: Path, script_dir: Path, entry_fn: str, preheat: bool):
        self.script_id = script_id
        self.python = python
        self.script_dir = script_dir
        self.entry_fn = entry_fn
        self.preheat = preheat
        self.proc: subprocess.Popen | None = None
        self.queue: asyncio.Queue = asyncio.Queue()
        self.lock = asyncio.Lock()
        self.ready = False
        self.jobs_run = 0
        self.last_used = time.monotonic()

    def alive(self) -> bool:
        return self.ready and self.proc is not None and self.proc.poll() is None

    async def start(self, base_env: dict) -> None:
        runner_path = self.script_dir / "_worker_runner.py"
        runner_path.write_text(
            _worker_runner_source(
                str(BACKEND_ROOT).replace("\\", "/"),
                str(self.script_dir).replace("\\", "/"),
                self.entry_fn,
            ),
            encoding="utf-8",
        )
        env = _clean_env()
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env.setdefault("LANGCHAIN_TRACING_V2", "false")
        env.setdefault("LANGSMITH_TRACING", "false")
        env.update(base_env)
        if self.preheat:
            env["AGENTFLOW_PREHEAT"] = "1"

        popen_kwargs = {}
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            # POSIX: same defensive rlimits as the one-shot path. The worker is
            # long-lived, so make_run_preexec() sets NO RLIMIT_CPU (it would
            # accumulate across jobs and eventually self-kill the worker).
            _preexec = make_run_preexec()
            if _preexec is not None:
                popen_kwargs["preexec_fn"] = _preexec

        base_cmd = [str(self.python), str(runner_path)]
        # Filesystem-jail the worker to its own script dir (per-job run_dirs live
        # under it, so chdir into them still works); can't read data/.secret_key,
        # the DB, or other scripts. Never the assistant — worker_enabled() excludes it.
        cmd = maybe_wrap_sandbox(
            base_cmd, script_dir=self.script_dir, run_dir=self.script_dir,
            backend_root=BACKEND_ROOT,
        )

        def _spawn(argv):
            return subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(self.script_dir),
                env=env,
                bufsize=1,
                text=True,
                encoding="utf-8",
                errors="replace",
                **popen_kwargs,
            )

        try:
            self.proc = _spawn(cmd)
        except OSError:
            if cmd is not base_cmd:
                logger.warning("sandbox launch failed for worker; running unsandboxed")
                self.proc = _spawn(base_cmd)
            else:
                raise
        loop = asyncio.get_running_loop()

        def _pump(stream, is_stderr: bool):
            def _push(item):
                # The worker outlives individual requests; if the loop is torn
                # down (shutdown / tests) a late line must not crash the thread.
                try:
                    loop.call_soon_threadsafe(self.queue.put_nowait, item)
                except RuntimeError:
                    pass
            try:
                for line in iter(stream.readline, ""):
                    line = line.rstrip("\r\n")
                    if not line:
                        continue
                    _push((is_stderr, line))
            finally:
                _push((is_stderr, None))

        threading.Thread(target=_pump, args=(self.proc.stdout, False), daemon=True).start()
        threading.Thread(target=_pump, args=(self.proc.stderr, True), daemon=True).start()

        # Wait for the boot handshake (`worker_ready`). Non-prefixed boot lines
        # (import warnings) are streamed to the backend log, not the run.
        t0 = time.monotonic()
        while True:
            try:
                is_stderr, line = await asyncio.wait_for(self.queue.get(), timeout=WORKER_BOOT_TIMEOUT)
            except asyncio.TimeoutError:
                self.kill()
                raise WorkerDied(f"worker boot timed out after {WORKER_BOOT_TIMEOUT:.0f}s")
            if line is None:
                self.kill()
                raise WorkerDied("worker exited during boot")
            if line.startswith(_PREFIX):
                payload = _try_json(line)
                if payload and payload.get("type") == "worker_ready":
                    self.ready = True
                    boot_s = time.monotonic() - t0
                    metrics.record_worker_boot(self.preheat, boot_s)
                    logger.info("[worker {}] ready (boot {:.2f}s, preheat={})",
                                self.script_id[:8], boot_s, self.preheat)
                    return
            elif is_stderr:
                logger.debug("[worker {}] boot: {}", self.script_id[:8], line)

    async def run_job(self, job: dict, handler: Callable[[bool, str], Awaitable[None]]) -> bool:
        """Send one job and pump its output through `handler` until job_done.
        Returns the job's ok flag. Raises WorkerDied if the process dies mid-job.
        Serialized per worker via the lock (one job at a time)."""
        async with self.lock:
            if not self.alive():
                raise WorkerDied("worker not alive")
            assert self.proc is not None and self.proc.stdin is not None
            try:
                self.proc.stdin.write(json.dumps(job) + "\n")
                self.proc.stdin.flush()
            except (BrokenPipeError, OSError) as e:
                self.ready = False
                raise WorkerDied(f"failed to send job: {e}")

            while True:
                is_stderr, line = await self.queue.get()
                if line is None:
                    self.ready = False
                    raise WorkerDied("worker exited mid-job")
                if line.startswith(_PREFIX):
                    payload = _try_json(line)
                    if payload:
                        typ = payload.get("type")
                        if typ == "job_done":
                            self.jobs_run += 1
                            self.last_used = time.monotonic()
                            ok = bool(payload.get("ok", True))
                            metrics.record_worker_job(ok)
                            return ok
                        if typ == "worker_ready":
                            continue  # stray, ignore
                await handler(is_stderr, line)

    def kill(self) -> None:
        self.ready = False
        p = self.proc
        if p is None:
            return
        try:
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    p.kill()
        except Exception:
            pass


def _try_json(line: str) -> dict | None:
    try:
        obj = json.loads(line[len(_PREFIX):])
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


# ── the pool ────────────────────────────────────────────────────────────────

class WorkerManager:
    def __init__(self) -> None:
        self._workers: dict[str, _Worker] = {}
        self._reaper: asyncio.Task | None = None

    async def acquire(self, script_id: str, entry_fn: str, preheat: bool, base_env: dict | None = None) -> _Worker:
        """Return a live worker for the script, spawning one if needed. Reuses an
        existing worker only if it's alive, on the current venv python, and under
        the max-jobs cap; otherwise it's retired and replaced."""
        python = get_venv_python(script_id) if venv_exists(script_id) else Path(sys.executable)
        script_dir = get_script_dir(script_id)

        w = self._workers.get(script_id)
        stale = (
            w is not None and (
                not w.alive()
                or str(w.python) != str(python)
                or (WORKER_MAX_JOBS > 0 and w.jobs_run >= WORKER_MAX_JOBS)
            )
        )
        if stale and w is not None:
            w.kill()
            self._workers.pop(script_id, None)
            metrics.record_worker_retirement("stale")
            w = None
        if w is not None:
            metrics.record_worker_acquire("reused")
            return w

        w = _Worker(script_id, python, script_dir, entry_fn, preheat)
        self._workers[script_id] = w
        try:
            await w.start(base_env or {})
        except Exception:
            self._workers.pop(script_id, None)
            metrics.record_worker_acquire("failed")
            raise
        metrics.record_worker_acquire("spawned")
        self._ensure_reaper()
        return w

    def get(self, script_id: str) -> _Worker | None:
        return self._workers.get(script_id)

    def invalidate(self, script_id: str) -> bool:
        """Retire a script's worker (a code / config change made it stale)."""
        w = self._workers.pop(script_id, None)
        if w is None:
            return False
        w.kill()
        metrics.record_worker_retirement("invalidated")
        logger.info("[worker {}] invalidated", script_id[:8])
        return True

    def shutdown_all(self) -> None:
        workers = list(self._workers.values())
        for w in workers:
            w.kill()
        metrics.record_worker_retirement("shutdown", len(workers))
        self._workers.clear()
        if self._reaper is not None and not self._reaper.done():
            self._reaper.cancel()
        self._reaper = None

    def _ensure_reaper(self) -> None:
        if self._reaper is not None and not self._reaper.done():
            return
        try:
            self._reaper = asyncio.get_running_loop().create_task(self._reap_loop())
        except RuntimeError:
            self._reaper = None

    async def _reap_loop(self) -> None:
        while True:
            await asyncio.sleep(_REAP_INTERVAL)
            now = time.monotonic()
            for sid, w in list(self._workers.items()):
                idle = now - w.last_used
                # only reap an idle worker that isn't mid-job (lock free)
                if idle > WORKER_IDLE_TTL and not w.lock.locked():
                    self._workers.pop(sid, None)
                    w.kill()
                    metrics.record_worker_retirement("reaped")
                    logger.info("[worker {}] reaped (idle {:.0f}s)", sid[:8], idle)
            if not self._workers:
                return  # nothing left to watch; a future acquire restarts the reaper


# module-level singleton
manager = WorkerManager()


def invalidate_worker(script_id: str) -> bool:
    """Public hook (called from routers on code/config change). Safe no-op if the
    pool never ran."""
    return manager.invalidate(script_id)


def worker_enabled(script) -> bool:
    """Whether this run should route through the warm pool: the global flag is on,
    the script opted in (warm=True), and it's not the built-in assistant."""
    if not WARM_WORKERS_ENABLED:
        return False
    if not getattr(script, "warm", True):
        return False
    try:
        from services.assistant_seed import ASSISTANT_SCRIPT_NAME
        if script.name == ASSISTANT_SCRIPT_NAME:
            return False
    except Exception:
        pass
    return True
