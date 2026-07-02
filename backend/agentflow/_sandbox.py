"""Sandboxed command / code execution for agentflow scripts and agents.

Two capabilities, both **opt-in** — they are NOT part of the default tool set.
A script enables them explicitly, the same way it calls `markdown()` / `image()`:

- :func:`run_bash` — run a shell command in a sandbox (the "exec sandbox").
- :func:`run_python` — run Python code in a sandbox (a full interpreter, handy
  for computation / data wrangling; the final bare expression is echoed).

Scripts call these directly (`from agentflow import run_bash, run_python`), or
hand the matching agent tools to an agent via
`get_agent(tools=get_tools() + exec_tools())` (see `bash_tool` / `python_tool`
/ `exec_tools` in agentflow/__init__.py).

Isolation is *process*-level, not a language jail — the child can still touch
the filesystem; the guarantees are:

1. **Env scrub** — the child keeps only a small allowlist, so every `AGENTFLOW_*`
   var (secrets, LLM keys, OAuth tokens) is dropped and the code can't read
   platform credentials.
2. **POSIX rlimits** — CPU time, address space (memory), file size, no core
   dumps, plus `os.setsid()` so a timeout kills the whole process group.
3. **Wall-clock timeout** — SIGKILL the group when it's exceeded.
4. **Isolated temp cwd** — a throwaway directory, deleted afterwards.

The Python sandbox reuses whatever Python is running the current script (the
per-script venv when there is one), so packages the user installed via
`requirements.txt` (numpy, pandas, …) are importable inside it too.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

DEFAULT_TIMEOUT = 30          # wall-clock seconds
DEFAULT_MEM_MB = 1024         # address-space cap (RLIMIT_AS); None disables
DEFAULT_FSIZE_MB = 64         # max bytes any single file the code writes
DEFAULT_MAX_INPUT = 100_000   # chars of code / command accepted
OUTPUT_LIMIT = 20_000         # chars of stdout/stderr returned

# Env vars the sandbox may keep; everything else (notably every AGENTFLOW_* key,
# which carries secrets / LLM credentials / OAuth tokens) is dropped so
# sandboxed code can't read platform credentials or phone home with them.
_ENV_KEEP = (
    "PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TZ",
    "TMPDIR", "TEMP", "TMP", "SYSTEMROOT", "WINDIR", "COMSPEC",
    "LD_LIBRARY_PATH",  # needed by some manylinux wheels (numpy/scipy)
)


def _sandbox_env() -> dict:
    env = {k: os.environ[k] for k in _ENV_KEEP if k in os.environ}
    env.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _make_preexec(mem_mb, cpu_s, fsize_mb):
    """Return a POSIX preexec_fn that puts the child in its own process group
    and applies resource limits. Returns None on platforms without `resource`."""
    try:
        import resource
    except ImportError:
        return None

    def _apply():
        # Own session/process group so a timeout can kill the whole tree.
        try:
            os.setsid()
        except OSError:
            pass

        def _set(res, soft):
            try:
                hard = resource.getrlimit(res)[1]
                if hard != resource.RLIM_INFINITY:
                    soft = min(soft, hard)
                resource.setrlimit(res, (soft, soft))
            except (ValueError, OSError):
                pass

        _set(resource.RLIMIT_CPU, int(cpu_s))
        _set(resource.RLIMIT_FSIZE, int(fsize_mb) * 1024 * 1024)
        _set(resource.RLIMIT_CORE, 0)
        if mem_mb:
            _set(resource.RLIMIT_AS, int(mem_mb) * 1024 * 1024)

    return _apply


def _kill(proc) -> None:
    try:
        if os.name == "posix":
            import signal
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        else:
            proc.kill()
    except (ProcessLookupError, OSError):
        pass


def _clip(s: str) -> str:
    s = s or ""
    if len(s) > OUTPUT_LIMIT:
        return s[:OUTPUT_LIMIT] + f"\n… [truncated, {len(s) - OUTPUT_LIMIT} more chars]"
    return s


def _run_sandboxed(
    build_argv,
    *,
    timeout: float,
    mem_mb: int | None,
    fsize_mb: int,
    allow_network: bool,
) -> dict:
    """Core sandbox runner. `build_argv(workdir)` writes any needed files into
    the throwaway `workdir` and returns the argv to run. Returns
    ``{"stdout", "stderr", "returncode", "timed_out"}``."""
    workdir = tempfile.mkdtemp(prefix="af_exec_")
    try:
        argv = build_argv(workdir)
        if not allow_network and os.name == "posix" and shutil.which("unshare"):
            argv = ["unshare", "-rn", *argv]

        cpu_s = max(1, int(timeout) + 1)  # backstop for busy loops
        preexec = _make_preexec(mem_mb, cpu_s, fsize_mb) if os.name == "posix" else None

        popen_kwargs = {}
        if os.name == "nt":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

        def _spawn(cmd):
            return subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=workdir,
                env=_sandbox_env(),
                text=True,
                encoding="utf-8",
                errors="replace",
                preexec_fn=preexec,
                **popen_kwargs,
            )

        try:
            proc = _spawn(argv)
        except OSError as e:
            # e.g. `unshare` present but not permitted → retry without it once.
            if argv and argv[0] == "unshare":
                try:
                    proc = _spawn(argv[3:])
                except OSError as e2:
                    return {"stdout": "", "stderr": f"failed to launch sandbox: {e2}",
                            "returncode": 1, "timed_out": False}
            else:
                return {"stdout": "", "stderr": f"failed to launch sandbox: {e}",
                        "returncode": 1, "timed_out": False}

        timed_out = False
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill(proc)
            try:
                stdout, stderr = proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                stdout, stderr = "", ""

        return {
            "stdout": _clip(stdout),
            "stderr": _clip(stderr),
            "returncode": proc.returncode if proc.returncode is not None else -1,
            "timed_out": timed_out,
        }
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# ── Python sandbox ─────────────────────────────────────────────────────────────

# Harness that runs the user's code REPL-style: statements execute, and if the
# final line is a bare expression its repr is printed (like a notebook cell), so
# `2 + 2` or `df.head()` produces output without an explicit print().
_PY_HARNESS = r'''import ast, pathlib
_src = pathlib.Path(__file__).with_name("_user_code.py").read_text(encoding="utf-8")
_g = {"__name__": "__main__", "__file__": "<sandbox>", "__builtins__": __builtins__}
_block = ast.parse(_src, filename="<sandbox>", mode="exec")
_last = None
if _block.body and isinstance(_block.body[-1], ast.Expr):
    _last = ast.Expression(_block.body.pop().value)
exec(compile(_block, "<sandbox>", "exec"), _g)
if _last is not None:
    _v = eval(compile(_last, "<sandbox>", "eval"), _g)
    if _v is not None:
        print(repr(_v))
'''


def run_python(
    code: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    mem_mb: int | None = DEFAULT_MEM_MB,
    fsize_mb: int = DEFAULT_FSIZE_MB,
    allow_network: bool = True,
) -> dict:
    """Execute Python ``code`` in the sandbox (see module docstring).

    Returns ``{"stdout", "stderr", "returncode", "timed_out"}``. The final bare
    expression (if any) is printed REPL-style. Runs under the per-script venv
    python via ``python -I`` (isolated mode), so installed packages are
    importable while PYTHON* env vars and user site-packages are ignored.
    """
    if not isinstance(code, str) or not code.strip():
        return {"stdout": "", "stderr": "empty code", "returncode": 1, "timed_out": False}
    if len(code) > DEFAULT_MAX_INPUT:
        return {"stdout": "", "stderr": f"code too long (max {DEFAULT_MAX_INPUT} chars)",
                "returncode": 1, "timed_out": False}

    def _build(workdir):
        code_path = os.path.join(workdir, "_user_code.py")
        harness_path = os.path.join(workdir, "_harness.py")
        with open(code_path, "w", encoding="utf-8") as fh:
            fh.write(code)
        with open(harness_path, "w", encoding="utf-8") as fh:
            fh.write(_PY_HARNESS)
        return [sys.executable, "-I", harness_path]

    return _run_sandboxed(
        _build, timeout=timeout, mem_mb=mem_mb, fsize_mb=fsize_mb,
        allow_network=allow_network,
    )


# ── Bash sandbox ───────────────────────────────────────────────────────────────

def _shell() -> str:
    return shutil.which("bash") or shutil.which("sh") or "bash"


def run_bash(
    command: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    mem_mb: int | None = DEFAULT_MEM_MB,
    fsize_mb: int = DEFAULT_FSIZE_MB,
    allow_network: bool = True,
) -> dict:
    """Execute a shell ``command`` in the sandbox (see module docstring).

    Returns ``{"stdout", "stderr", "returncode", "timed_out"}``. Runs via
    ``bash -c <command>`` (falls back to ``sh``) in a throwaway working
    directory with a scrubbed environment, resource limits and a timeout.
    """
    if not isinstance(command, str) or not command.strip():
        return {"stdout": "", "stderr": "empty command", "returncode": 1, "timed_out": False}
    if len(command) > DEFAULT_MAX_INPUT:
        return {"stdout": "", "stderr": f"command too long (max {DEFAULT_MAX_INPUT} chars)",
                "returncode": 1, "timed_out": False}

    def _build(workdir):
        return [_shell(), "-c", command]

    return _run_sandboxed(
        _build, timeout=timeout, mem_mb=mem_mb, fsize_mb=fsize_mb,
        allow_network=allow_network,
    )


# ── Shared formatting ──────────────────────────────────────────────────────────

def format_exec_result(res: dict, *, timeout: float = DEFAULT_TIMEOUT) -> str:
    """Render a run_python()/run_bash() result as a compact LLM tool reply."""
    parts = []
    out = (res.get("stdout") or "").strip()
    err = (res.get("stderr") or "").strip()
    if out:
        parts.append(out)
    if err:
        parts.append(f"[stderr]\n{err}")
    if res.get("timed_out"):
        parts.append(f"[timed out after {timeout}s — killed]")
    rc = res.get("returncode", 0)
    if rc not in (0, None) and not res.get("timed_out"):
        parts.append(f"[exit code {rc}]")
    return "\n".join(parts) if parts else "(no output)"
