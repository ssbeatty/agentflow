"""Safe code execution + calculation for agentflow scripts and agents.

Two capabilities, exposed to agents as the built-in tools ``calculate`` and
``python_exec`` (see :func:`agentflow.get_tools`) and importable directly:

- :func:`safe_calc` — a whitelist AST evaluator for arithmetic / math. It never
  spawns a process, imports nothing, and touches no attributes, so it is always
  safe. Use it whenever an agent needs to *compute* a number instead of guessing
  one (LLMs are bad at mental arithmetic, great at writing the expression).

- :func:`run_python` — execute arbitrary Python in a subprocess **sandbox**:
  the child runs with a scrubbed environment (no AgentFlow secrets / LLM keys),
  POSIX resource limits (CPU time, address space, file size), a wall-clock
  timeout, and an isolated temp working directory that is deleted afterwards.
  This is *process*-level isolation (rlimit + timeout + env-scrub + own process
  group), not a Python-level jail — the child can still ``import os``; the point
  is that it cannot exhaust the host, hang forever, or read platform credentials.

The exec sandbox reuses whatever Python is running the current script (the
per-script venv when there is one), so packages the user installed via
``requirements.txt`` (numpy, pandas, …) are importable inside the sandbox too.
"""
from __future__ import annotations

import ast
import math
import operator
import os
import shutil
import subprocess
import sys
import tempfile

# ── Safe arithmetic evaluator ──────────────────────────────────────────────────
#
# A tiny whitelist interpreter over the `ast` module. Only the node types,
# operators, names and functions listed below are permitted; anything else
# (attribute access, imports, comprehensions, lambdas, assignments, arbitrary
# names) raises. There is no way to reach the filesystem, network, or Python
# internals through it, so it is safe to run on untrusted input in-process.

_MAX_EXPR_LEN = 2000
_MAX_POW = 1000        # cap `a ** b` / pow(a, b) exponent → no 10**10**9 blow-up
_MAX_FACTORIAL = 1000  # cap factorial(n) argument


class CalcError(ValueError):
    """Raised when an expression uses something the safe evaluator forbids."""


_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARYOPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
    ast.Not: operator.not_,
}
_CMPOPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}


def _factorial(n):
    if not isinstance(n, int) or n < 0:
        raise CalcError("factorial requires a non-negative integer")
    if n > _MAX_FACTORIAL:
        raise CalcError(f"factorial argument too large (max {_MAX_FACTORIAL})")
    return math.factorial(n)


def _guard_pow(base, exp):
    """Reject pathologically large powers before they burn CPU / RAM."""
    try:
        if isinstance(exp, (int, float)) and abs(exp) > _MAX_POW and abs(base) > 1:
            raise CalcError(f"exponent too large (max {_MAX_POW})")
    except TypeError:
        pass


def _pow(base, exp, mod=None):
    _guard_pow(base, exp)
    return pow(base, exp) if mod is None else pow(base, exp, mod)


_NAMES = {
    "pi": math.pi,
    "e": math.e,
    "tau": math.tau,
    "inf": math.inf,
    "nan": math.nan,
    "True": True,
    "False": False,
    "None": None,
}

_FUNCS = {
    # builtins
    "abs": abs, "round": round, "min": min, "max": max, "sum": sum,
    "len": len, "pow": _pow, "int": int, "float": float, "bool": bool,
    "divmod": divmod, "sorted": sorted, "range": lambda *a: list(range(*a)),
    # math
    "sqrt": math.sqrt, "exp": math.exp, "log": math.log, "log2": math.log2,
    "log10": math.log10, "log1p": math.log1p,
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "asin": math.asin, "acos": math.acos, "atan": math.atan, "atan2": math.atan2,
    "sinh": math.sinh, "cosh": math.cosh, "tanh": math.tanh,
    "floor": math.floor, "ceil": math.ceil, "trunc": math.trunc,
    "fabs": math.fabs, "factorial": _factorial, "gcd": math.gcd,
    "degrees": math.degrees, "radians": math.radians, "hypot": math.hypot,
    "copysign": math.copysign, "fmod": math.fmod, "isclose": math.isclose,
    "comb": math.comb, "perm": math.perm, "dist": math.dist, "prod": math.prod,
}


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float, complex, bool, str)) or node.value is None:
            return node.value
        raise CalcError(f"literal not allowed: {node.value!r}")
    if isinstance(node, ast.Name):
        if node.id in _NAMES:
            return _NAMES[node.id]
        raise CalcError(f"name not allowed: {node.id!r}")
    if isinstance(node, ast.BinOp):
        op = _BINOPS.get(type(node.op))
        if op is None:
            raise CalcError(f"operator not allowed: {type(node.op).__name__}")
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow):
            _guard_pow(left, right)
        return op(left, right)
    if isinstance(node, ast.UnaryOp):
        op = _UNARYOPS.get(type(node.op))
        if op is None:
            raise CalcError(f"operator not allowed: {type(node.op).__name__}")
        return op(_eval(node.operand))
    if isinstance(node, ast.BoolOp):
        vals = [_eval(v) for v in node.values]
        if isinstance(node.op, ast.And):
            return all(vals) and vals[-1]
        return next((v for v in vals if v), vals[-1])
    if isinstance(node, ast.Compare):
        left = _eval(node.left)
        for op_node, comp in zip(node.ops, node.comparators):
            op = _CMPOPS.get(type(op_node))
            if op is None:
                raise CalcError(f"comparison not allowed: {type(op_node).__name__}")
            right = _eval(comp)
            if not op(left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise CalcError("only direct calls to whitelisted functions are allowed")
        fn = _FUNCS.get(node.func.id)
        if fn is None:
            raise CalcError(f"function not allowed: {node.func.id!r}")
        args = [_eval(a) for a in node.args]
        if any(isinstance(a, ast.Starred) for a in node.args):
            raise CalcError("argument unpacking is not allowed")
        kwargs = {}
        for kw in node.keywords:
            if kw.arg is None:
                raise CalcError("keyword unpacking is not allowed")
            kwargs[kw.arg] = _eval(kw.value)
        return fn(*args, **kwargs)
    if isinstance(node, (ast.List, ast.Tuple)):
        vals = [_eval(e) for e in node.elts]
        return vals if isinstance(node, ast.List) else tuple(vals)
    if isinstance(node, ast.IfExp):
        return _eval(node.body) if _eval(node.test) else _eval(node.orelse)
    raise CalcError(f"expression element not allowed: {type(node).__name__}")


def safe_calc(expression: str):
    """Safely evaluate an arithmetic / math expression and return the result.

    Supports ``+ - * / // % **``, comparisons, boolean ops, ternaries, lists /
    tuples, math constants (``pi``, ``e``, ``tau``, ``inf``), and a curated set
    of functions: ``abs round min max sum len pow sqrt exp log log2 log10 sin
    cos tan asin acos atan atan2 sinh cosh tanh floor ceil trunc factorial gcd
    comb perm hypot dist prod degrees radians …``.

    It imports nothing and accesses no attributes, so it is safe on untrusted
    input. Raises :class:`CalcError` for anything outside the whitelist.

    Examples::

        safe_calc("2 ** 10 + sqrt(144)")        # -> 1036.0
        safe_calc("factorial(20) / comb(52, 5)")
        safe_calc("sum([x for x in range(10)])")  # CalcError: comprehensions off
    """
    if not isinstance(expression, str) or not expression.strip():
        raise CalcError("expression must be a non-empty string")
    if len(expression) > _MAX_EXPR_LEN:
        raise CalcError(f"expression too long (max {_MAX_EXPR_LEN} chars)")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as e:
        raise CalcError(f"syntax error: {e.msg}") from None
    return _eval(tree)


# ── Subprocess exec sandbox ────────────────────────────────────────────────────

DEFAULT_TIMEOUT = 15          # wall-clock seconds
DEFAULT_MEM_MB = 1024         # address-space cap (RLIMIT_AS); None disables
DEFAULT_FSIZE_MB = 64         # max bytes any single file the code writes
DEFAULT_MAX_CODE = 100_000    # chars of source accepted
OUTPUT_LIMIT = 20_000         # chars of stdout/stderr returned

# Env vars the sandbox may keep; everything else (notably every AGENTFLOW_* key,
# which carries secrets / LLM credentials / OAuth tokens) is dropped so
# agent-authored code can't read platform credentials or phone home with them.
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


# Harness that runs the user's code REPL-style: statements execute, and if the
# final line is a bare expression its repr is printed (like a notebook cell), so
# `2 + 2` or `df.head()` produces output without an explicit print().
_HARNESS = r'''import ast, pathlib, sys
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


def _kill(proc) -> None:
    try:
        if os.name == "posix":
            import signal
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        else:
            proc.kill()
    except (ProcessLookupError, OSError):
        pass


def run_python(
    code: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    mem_mb: int | None = DEFAULT_MEM_MB,
    fsize_mb: int = DEFAULT_FSIZE_MB,
    allow_network: bool = True,
) -> dict:
    """Execute ``code`` in a resource-limited, env-scrubbed subprocess sandbox.

    Returns ``{"stdout", "stderr", "returncode", "timed_out"}``. The final bare
    expression (if any) is printed REPL-style. The child runs in a throwaway temp
    directory (its cwd, deleted afterwards) with CPU / memory / file-size limits,
    a wall-clock ``timeout``, and an environment stripped of all AgentFlow
    secrets and LLM credentials.

    ``allow_network=False`` best-effort blocks network access via ``unshare -n``
    where available (unprivileged user namespaces); it silently falls back to
    allowing network if the kernel/permissions don't support it, so never rely on
    it as a hard guarantee — the real protection is that credentials aren't in
    the child's environment.
    """
    if not isinstance(code, str) or not code.strip():
        return {"stdout": "", "stderr": "empty code", "returncode": 1, "timed_out": False}
    if len(code) > DEFAULT_MAX_CODE:
        return {"stdout": "", "stderr": f"code too long (max {DEFAULT_MAX_CODE} chars)",
                "returncode": 1, "timed_out": False}

    workdir = tempfile.mkdtemp(prefix="af_exec_")
    try:
        code_path = os.path.join(workdir, "_user_code.py")
        harness_path = os.path.join(workdir, "_harness.py")
        with open(code_path, "w", encoding="utf-8") as fh:
            fh.write(code)
        with open(harness_path, "w", encoding="utf-8") as fh:
            fh.write(_HARNESS)

        # `-I` = isolated mode: ignore PYTHON* env vars and user site-packages,
        # while still importing the venv's own installed packages.
        argv = [sys.executable, "-I", harness_path]
        if not allow_network and os.name == "posix" and shutil.which("unshare"):
            argv = ["unshare", "-rn", *argv]

        # CPU limit slightly above the wall timeout as a backstop for busy loops.
        cpu_s = max(1, int(timeout) + 1)
        preexec = _make_preexec(mem_mb, cpu_s, fsize_mb) if os.name == "posix" else None

        popen_kwargs = {}
        if os.name == "nt":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

        try:
            proc = subprocess.Popen(
                argv,
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
        except OSError as e:
            # e.g. `unshare` present but not permitted → retry without it once.
            if argv[0] == "unshare":
                argv = argv[3:]
                proc = subprocess.Popen(
                    argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    cwd=workdir, env=_sandbox_env(), text=True, encoding="utf-8",
                    errors="replace", preexec_fn=preexec, **popen_kwargs,
                )
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

        def _clip(s: str) -> str:
            s = s or ""
            if len(s) > OUTPUT_LIMIT:
                return s[:OUTPUT_LIMIT] + f"\n… [truncated, {len(s) - OUTPUT_LIMIT} more chars]"
            return s

        return {
            "stdout": _clip(stdout),
            "stderr": _clip(stderr),
            "returncode": proc.returncode if proc.returncode is not None else -1,
            "timed_out": timed_out,
        }
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def format_exec_result(res: dict, *, timeout: float = DEFAULT_TIMEOUT) -> str:
    """Render a run_python() result as a compact string for an LLM tool reply."""
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
