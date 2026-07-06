import asyncio
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from loguru import logger

from app.config import DATA_DIR


_DEBUGGER_ENV_PREFIXES = ("PYDEVD_", "DEBUGPY_", "PYCHARM_")
_DEBUGGER_ENV_KEYS = {"PYTHONPATH", "PYTHONSTARTUP", "PYTHONHOME", "VIRTUAL_ENV"}


def _clean_env() -> dict:
    """Parent env minus anything that would drag the debugger / parent venv
    into the child python process."""
    env = {
        k: v for k, v in os.environ.items()
        if k not in _DEBUGGER_ENV_KEYS
        and not any(k.startswith(p) for p in _DEBUGGER_ENV_PREFIXES)
    }
    return env


def _subproc_env() -> dict:
    env = _clean_env()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    env["PIP_NO_INPUT"] = "1"
    env["PIP_PROGRESS_BAR"] = "off"
    return env


# ── Defensive resource limits for user-script subprocesses (POSIX) ─────────────
# Applied via preexec_fn at BOTH spawn sites (execution_engine's one-shot run and
# the warm worker) so a runaway or buggy user script can't take down the host.
# Best-effort by design: each limit is clamped to the inherited hard limit and any
# setrlimit failure is swallowed, so this only ever *tightens* — it can never make
# a legit launch fail. On Windows `resource` is unavailable and it degrades to a
# no-op, exactly like the opt-in _sandbox and the CREATE_NEW_PROCESS_GROUP path.
#
# Defaults are picked for near-zero false positives:
#   • RLIMIT_AS (address space) — the one limit ON by default: caps runaway
#     memory so one script can't OOM the box. Generous 4 GiB, env-tunable.
#   • RLIMIT_CORE = 0 — no core dumps (always safe, never breaks a workload).
#   • RLIMIT_FSIZE / RLIMIT_NPROC — OFF by default (0). A big-file writer
#     shouldn't silently hit SIGXFSZ, and RLIMIT_NPROC is per-UID (it counts the
#     whole backend's processes, not just this child), so it's opt-in only.
# Deliberately NO RLIMIT_CPU (user runs are network/LLM-bound — the engine's
# wall-clock EXECUTION_TIMEOUT already bounds runaways, and a warm worker would
# accumulate CPU across jobs and self-kill) and NO os.setsid() (leaves the
# existing process-group / cancellation semantics untouched).
RUN_MEM_MB = int(os.getenv("AGENTFLOW_RUN_MEM_MB", "4096"))    # 0 disables
RUN_FSIZE_MB = int(os.getenv("AGENTFLOW_RUN_FSIZE_MB", "0"))   # 0 disables
RUN_NPROC = int(os.getenv("AGENTFLOW_RUN_NPROC", "0"))         # 0 disables (per-UID)


def make_run_preexec(mem_mb: int | None = None, fsize_mb: int | None = None,
                     nproc: int | None = None):
    """Return a POSIX ``preexec_fn`` applying defensive rlimits to a user-script
    child, or ``None`` where they can't apply (Windows / no ``resource`` module,
    in which case Popen simply gets no preexec_fn). Values default to the module
    ``RUN_*`` settings; a value of 0 leaves that particular limit alone."""
    if os.name != "posix":
        return None
    try:
        import resource
    except ImportError:
        return None

    mem_mb = RUN_MEM_MB if mem_mb is None else mem_mb
    fsize_mb = RUN_FSIZE_MB if fsize_mb is None else fsize_mb
    nproc = RUN_NPROC if nproc is None else nproc

    def _apply():
        def _set(res, soft):
            try:
                hard = resource.getrlimit(res)[1]
                if hard != resource.RLIM_INFINITY:
                    soft = min(soft, hard)
                resource.setrlimit(res, (soft, soft))
            except (ValueError, OSError):
                pass

        _set(resource.RLIMIT_CORE, 0)
        if mem_mb:
            _set(resource.RLIMIT_AS, int(mem_mb) * 1024 * 1024)
        if fsize_mb:
            _set(resource.RLIMIT_FSIZE, int(fsize_mb) * 1024 * 1024)
        if nproc:
            _set(resource.RLIMIT_NPROC, int(nproc))

    return _apply


# ── Filesystem sandbox for user-script subprocesses (bubblewrap / bwrap) ───────
# rlimits (above) stop a script from exhausting host resources; this stops it
# from *reading* what it shouldn't. Without it a user script can open()
# data/.secret_key, the DB, or another script's folder — all of which live on
# disk next to its own dir. bwrap runs the child in a mount + pid namespace that
# only contains: the system dirs (read-only), the agentflow SDK (read-only), and
# THIS script's own directory (read-write). Everything else — crucially the data
# dir with the secret key / DB / other scripts — is simply not in the namespace,
# so it doesn't exist for the child. Network + env are NOT unshared, so LLM/MCP
# calls and the script's own secrets keep working.
#
# AGENTFLOW_SANDBOX: "auto" (default — wrap when a *functional* bwrap is present)
#   or "off" (never wrap; rlimits still apply). Any other value behaves as auto.
# Some hardened container runtimes block unprivileged user namespaces, so we
# probe once and DEGRADE to no-jail rather than breaking every run — a run is
# never failed just because bwrap couldn't start.
_SANDBOX_MODE = os.getenv("AGENTFLOW_SANDBOX", "auto").strip().lower()
_bwrap_ok: bool | None = None  # tri-state cache: None=unprobed


def _sandbox_extra(env_name: str) -> list:
    """Parse a comma-separated list of extra absolute paths from an env var
    (for operators who need a script to reach a shared dir outside its own)."""
    raw = os.getenv(env_name, "")
    return [p.strip() for p in raw.split(",") if p.strip()] if raw else []


def _bwrap_probe() -> bool:
    """One-time check that bwrap can create the namespaces we need here."""
    bw = shutil.which("bwrap")
    if not bw:
        return False
    try:
        r = subprocess.run(
            [bw, "--ro-bind", "/", "/", "--proc", "/proc", "--dev", "/dev",
             "--unshare-pid", "--die-with-parent", "true"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,
        )
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def sandbox_enabled() -> bool:
    """True when the bwrap filesystem jail should wrap user-script runs."""
    global _bwrap_ok
    if os.name != "posix" or _SANDBOX_MODE == "off":
        return False
    if _bwrap_ok is None:
        _bwrap_ok = _bwrap_probe()
    return _bwrap_ok


def build_bwrap_prefix(script_dir, run_dir, backend_root) -> list:
    """Build the bwrap argv prefix that jails a child to system dirs (ro) + the
    agentflow SDK (ro) + this script's own dir (rw), chdir'd into run_dir. Pure
    and side-effect free (safe to unit-test on any OS)."""
    sd = os.path.abspath(str(script_dir))
    rd = os.path.abspath(str(run_dir))
    sdk = os.path.join(os.path.abspath(str(backend_root)), "agentflow")

    prefix = [
        "bwrap",
        "--die-with-parent",
        "--unshare-pid",
        "--proc", "/proc",
        "--dev", "/dev",
        "--tmpfs", "/tmp",
    ]
    # System dirs, read-only — only those that exist (slim / merged-usr images).
    # /etc (ro) carries TLS certs + DNS/nsswitch config, so httpx→LLM and MCP DNS
    # keep working; the network namespace is deliberately NOT unshared.
    for p in ("/usr", "/bin", "/sbin", "/lib", "/lib32", "/lib64", "/etc"):
        if os.path.exists(p):
            prefix += ["--ro-bind", p, p]
    # ONLY the agentflow subdir of backend_root — never the whole tree, so app/
    # services/ and especially data/ (secret_key, DB, other scripts) stay out.
    if os.path.isdir(sdk):
        prefix += ["--ro-bind", sdk, sdk]
    # This script's own dir (its venv + main.py + runs/<id>/ + workspace/), rw.
    prefix += ["--bind", sd, sd]
    for spec in _sandbox_extra("AGENTFLOW_SANDBOX_RO_BINDS"):
        prefix += ["--ro-bind-try", spec, spec]
    for spec in _sandbox_extra("AGENTFLOW_SANDBOX_RW_BINDS"):
        prefix += ["--bind-try", spec, spec]
    prefix += ["--chdir", rd]
    return prefix


def maybe_wrap_sandbox(argv, *, script_dir, run_dir, backend_root):
    """Return ``argv`` wrapped in a bwrap filesystem jail when the sandbox is
    enabled+functional, else ``argv`` unchanged (identity, so callers can
    ``is``-compare to fall back if the wrapped launch fails)."""
    if not sandbox_enabled():
        return argv
    return build_bwrap_prefix(script_dir, run_dir, backend_root) + list(argv)


def get_script_dir(script_id: str) -> Path:
    d = DATA_DIR / script_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_venv_python(script_id: str) -> Path:
    venv = get_script_dir(script_id) / ".venv"
    if sys.platform == "win32":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def venv_exists(script_id: str) -> bool:
    return get_venv_python(script_id).exists()


def _uv() -> str | None:
    return shutil.which("uv")


# Always installed into every script venv on creation so `from agentflow import …`
# and `get_llm()` work out of the box without the user touching requirements.txt.
BASELINE_PACKAGES = [
    "langchain-core",
    "langchain-openai",
    "langchain-deepseek",
    "langgraph",
    # agentflow built-in tool support
    "httpx",
    "ddgs",
    # web_fetch clean-text extraction (falls back to raw HTML if missing)
    "beautifulsoup4",
    # MCP client (optional at runtime, gracefully skipped if unused)
    "langchain-mcp-adapters",
    # allows nested asyncio.run() when sync LangGraph calls tools inside our async runner
    "nest-asyncio",
    # deep agents (planning + subagents + filesystem-backed skills); powers get_deep_agent()
    "deepagents",
]


async def stream_create_venv(script_id: str, force: bool = False):
    """Yield output lines while creating the venv.

    If the venv already exists and force is False, short-circuit with a notice.
    """
    venv_dir = get_script_dir(script_id) / ".venv"
    logger.info("[script {}] venv create requested (force={})", script_id, force)

    if venv_exists(script_id) and not force:
        yield f"venv already exists at {venv_dir}; skipping (delete it to recreate)"
        yield "DONE"
        return

    if force and venv_dir.exists():
        yield f"removing existing venv at {venv_dir} ..."
        try:
            shutil.rmtree(venv_dir)
        except Exception as e:
            logger.warning("[script {}] failed to remove existing venv: {}", script_id, e)
            yield f"ERROR: failed to remove existing venv: {e}"
            return

    uv = _uv()
    if uv:
        cmd = [uv, "venv", str(venv_dir)]
    else:
        cmd = [sys.executable, "-m", "venv", str(venv_dir)]

    # 1) create the venv
    create_ok = True
    async for line in _run_and_stream(cmd):
        if line.startswith("ERROR:"):
            create_ok = False
            logger.warning("[script {}] venv creation failed: {}", script_id, line)
            yield line
            return
        if line == "DONE":
            yield "venv created"
            continue
        yield line

    if not create_ok:
        return

    # 2) install baseline packages so agentflow + LLM providers work out of the box
    python = get_venv_python(script_id)
    yield ""
    yield f"installing baseline packages: {', '.join(BASELINE_PACKAGES)}"
    if uv:
        base_cmd = [uv, "pip", "install", *BASELINE_PACKAGES, "--python", str(python)]
    else:
        base_cmd = [
            str(python), "-m", "pip", "install",
            "--disable-pip-version-check", "--no-input", "--progress-bar", "off",
            *BASELINE_PACKAGES,
        ]
    install_ok = True
    async for line in _run_and_stream(base_cmd):
        if line.startswith("ERROR:"):
            install_ok = False
        yield line
    logger.info("[script {}] venv create {}", script_id, "ready" if install_ok else "baseline install failed")


_LIST_PKGS_SCRIPT = r"""
import json, sys
from importlib import metadata as m
out = []
for dist in m.distributions():
    try:
        out.append({"name": dist.metadata["Name"], "version": dist.version})
    except Exception:
        continue
# de-dup by lowercase name
seen, dedup = set(), []
for p in sorted(out, key=lambda x: (x["name"] or "").lower()):
    k = (p["name"] or "").lower()
    if k in seen: continue
    seen.add(k); dedup.append(p)
print("__PKGS__" + json.dumps(dedup))
"""


def list_installed_packages(script_id: str) -> tuple[list[dict], str | None]:
    """Return (packages, error). Uses importlib.metadata inside the venv python."""
    import json as _json
    python = get_venv_python(script_id)
    if not python.exists():
        return [], "venv not created"

    try:
        proc = subprocess.run(
            [str(python), "-c", _LIST_PKGS_SCRIPT],
            env=_subproc_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )
    except Exception as e:
        return [], f"failed to run python: {e}"

    stdout = proc.stdout.decode("utf-8", errors="replace")
    stderr = proc.stderr.decode("utf-8", errors="replace")

    if proc.returncode != 0:
        return [], (stderr or stdout or f"python exited {proc.returncode}").strip()

    marker = "__PKGS__"
    idx = stdout.find(marker)
    if idx < 0:
        return [], f"no package marker found; stdout={stdout[:200]!r} stderr={stderr[:200]!r}"

    try:
        return _json.loads(stdout[idx + len(marker):].strip()), None
    except Exception as e:
        return [], f"failed to parse: {e}"


def delete_venv(script_id: str) -> bool:
    venv_dir = get_script_dir(script_id) / ".venv"
    if not venv_dir.exists():
        return False
    shutil.rmtree(venv_dir, ignore_errors=False)
    logger.info("[script {}] venv deleted", script_id)
    return True


_SENTINEL = object()


def _spawn_and_pump(cmd: list[str], queue: asyncio.Queue, loop: asyncio.AbstractEventLoop) -> None:
    """Blocking: run subprocess, push decoded chunks (split on \\n or \\r) into asyncio queue from a worker thread."""
    popen_kwargs = {}
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=_subproc_env(),
            bufsize=0,
            **popen_kwargs,
        )
    except Exception as e:
        loop.call_soon_threadsafe(queue.put_nowait, f"ERROR: failed to spawn: {e}")
        loop.call_soon_threadsafe(queue.put_nowait, _SENTINEL)
        return

    buf = b""
    try:
        while True:
            chunk = proc.stdout.read(1024)
            if not chunk:
                break
            buf += chunk
            while True:
                idx_n = buf.find(b"\n")
                idx_r = buf.find(b"\r")
                candidates = [i for i in (idx_n, idx_r) if i >= 0]
                if not candidates:
                    break
                idx = min(candidates)
                line, buf = buf[:idx], buf[idx + 1:]
                text = line.decode("utf-8", errors="replace").rstrip()
                if text:
                    loop.call_soon_threadsafe(queue.put_nowait, text)
        if buf:
            text = buf.decode("utf-8", errors="replace").rstrip()
            if text:
                loop.call_soon_threadsafe(queue.put_nowait, text)
        proc.wait()
        if proc.returncode != 0:
            loop.call_soon_threadsafe(
                queue.put_nowait, f"ERROR: process exited with code {proc.returncode}"
            )
        else:
            loop.call_soon_threadsafe(queue.put_nowait, "DONE")
    finally:
        loop.call_soon_threadsafe(queue.put_nowait, _SENTINEL)


async def _run_and_stream(cmd: list[str]):
    """Run a subprocess in a worker thread; yield lines as they arrive."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    threading.Thread(target=_spawn_and_pump, args=(cmd, queue, loop), daemon=True).start()
    while True:
        item = await queue.get()
        if item is _SENTINEL:
            return
        yield item


async def stream_install(script_id: str, requirements: str):
    """Write requirements.txt and yield pip install output lines."""
    script_dir = get_script_dir(script_id)
    req_file = script_dir / "requirements.txt"
    req_file.write_text(requirements or "", encoding="utf-8")

    if not (requirements or "").strip():
        yield "requirements.txt is empty; nothing to install"
        yield "DONE"
        return

    python = get_venv_python(script_id)
    if not python.exists():
        logger.warning("[script {}] requirements install requested but venv missing", script_id)
        yield "ERROR: venv not found; create it first"
        return

    uv = _uv()
    if uv:
        cmd = [uv, "pip", "install", "-r", str(req_file), "--python", str(python)]
    else:
        cmd = [
            str(python), "-m", "pip", "install",
            "--disable-pip-version-check",
            "--no-input",
            "--progress-bar", "off",
            "-r", str(req_file),
        ]

    install_ok = True
    async for line in _run_and_stream(cmd):
        if line.startswith("ERROR:"):
            install_ok = False
        yield line
    logger.info("[script {}] requirements install {}", script_id, "succeeded" if install_ok else "failed")
