"""Script input-schema extraction + validation.

The *source of truth* for a script's input contract is the script itself: a
module-level ``INPUT_SCHEMA`` (a JSON-Schema ``dict``), which the user may write
as a literal or compute (e.g. ``INPUT_SCHEMA = MyModel.model_json_schema()``).
``Script.input_schema`` is a CACHE of that, refreshed here on save / manual sync
/ MCP introspect. Everything downstream (pre-run validation, /docs examples,
auto-rendered forms) reads the cached column.

Extraction is two-level, cheapest first:

1. **Static AST parse** (``_static_extract``) — resolves a literal
   ``INPUT_SCHEMA = {...}`` with ``ast.literal_eval``. Zero cost, no venv, no
   code execution. Covers the common case.
2. **Introspection subprocess** (``_introspect``) — only when the name is
   assigned but not a literal (computed / Pydantic). Writes the script's files
   to a throwaway dir, imports the main module in the script's venv (or the
   backend python if it has none), and dumps ``INPUT_SCHEMA`` as JSON. Bounded by
   a timeout; any failure yields ``None`` (schema stays whatever it was).

Importing the main module is cheap in practice because ``import agentflow`` does
NOT pull langchain (it's lazy behind ``get_llm``/``get_agent``) — so a module
that just defines ``INPUT_SCHEMA`` + ``run`` imports in well under a second.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from loguru import logger

from app.config import BACKEND_ROOT
from services.script_files import script_file_path
from services.venv_manager import get_venv_python, venv_exists, _clean_env

SCHEMA_VAR = "INPUT_SCHEMA"
_MARKER = "__AGENTFLOW_SCHEMA__"
_INTROSPECT_TIMEOUT = 20.0


# ── static (AST) extraction ─────────────────────────────────────────────────

def _static_extract(source: str) -> tuple[str, dict | None]:
    """Try to resolve a module-level ``INPUT_SCHEMA`` from source without running
    it. Returns one of:
      - ("ok", schema_dict)   — resolved to a literal dict
      - ("dynamic", None)     — the name is assigned but not a literal dict
                                (computed / Pydantic) → caller should introspect
      - ("absent", None)      — no top-level INPUT_SCHEMA assignment at all
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return "absent", None

    value_node: ast.AST | None = None
    for node in tree.body:  # top level only
        targets: list[ast.AST] = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
        else:
            continue
        if any(isinstance(t, ast.Name) and t.id == SCHEMA_VAR for t in targets):
            value_node = node.value

    if value_node is None:
        return "absent", None
    try:
        val = ast.literal_eval(value_node)
    except (ValueError, TypeError, SyntaxError):
        return "dynamic", None
    if isinstance(val, dict):
        return "ok", val
    # Assigned to a non-dict literal (e.g. None) — treat as no schema.
    return "absent", None


# ── runtime introspection (subprocess) ──────────────────────────────────────

_BOOTSTRAP = r'''
import sys, json, importlib.util
_MARKER = {marker!r}
try:
    spec = importlib.util.spec_from_file_location("user_script", {main!r})
    mod = importlib.util.module_from_spec(spec)
    sys.modules["user_script"] = mod
    spec.loader.exec_module(mod)
    schema = getattr(mod, {var!r}, None)
    if schema is None:
        print(_MARKER + json.dumps({{"ok": False, "reason": "absent"}}))
    elif isinstance(schema, dict):
        print(_MARKER + json.dumps({{"ok": True, "schema": schema}}))
    else:
        print(_MARKER + json.dumps({{"ok": False, "reason": "not-a-dict"}}))
except Exception as exc:
    print(_MARKER + json.dumps({{"ok": False, "reason": str(exc)}}))
'''


def _introspect(script_id: str, files: list[tuple[str, str]], main_filename: str) -> dict | None:
    """Import the script's main module in its venv and dump INPUT_SCHEMA.

    `files` is a list of (filename, content). Runs in a throwaway temp dir so it
    never clobbers the live script_dir / a concurrent run. Best-effort: returns
    None on any failure or timeout.
    """
    py = get_venv_python(script_id) if venv_exists(script_id) else Path(sys.executable)
    with tempfile.TemporaryDirectory(prefix="af_introspect_") as tmp:
        tmp_dir = Path(tmp)
        main_path: Path | None = None
        for filename, content in files:
            try:
                dest = script_file_path(tmp_dir, filename)
            except ValueError:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content or "", encoding="utf-8")
            if filename == main_filename:
                main_path = dest
        if main_path is None:
            return None

        code = _BOOTSTRAP.format(
            marker=_MARKER,
            main=str(main_path).replace("\\", "/"),
            var=SCHEMA_VAR,
        )
        env = _clean_env()
        env["PYTHONIOENCODING"] = "utf-8"
        # so `from agentflow import ...` resolves without installing it
        env["PYTHONPATH"] = str(BACKEND_ROOT)
        try:
            proc = subprocess.run(
                [str(py), "-c", code],
                cwd=str(tmp_dir),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=_INTROSPECT_TIMEOUT,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            logger.warning("[script {}] schema introspection failed: {}", script_id, exc)
            return None

        for line in (proc.stdout or "").splitlines():
            if line.startswith(_MARKER):
                try:
                    payload = json.loads(line[len(_MARKER):])
                except json.JSONDecodeError:
                    return None
                if payload.get("ok"):
                    return payload.get("schema")
                return None
    return None


# ── orchestration ───────────────────────────────────────────────────────────

def _main_file(script) -> tuple[str, str] | None:
    """Return (filename, content) of the script's entry file (is_main, else main.py)."""
    main = next((f for f in script.files if f.is_main), None)
    if main is None:
        main = next((f for f in script.files if f.filename == "main.py"), None)
    if main is None:
        return None
    return main.filename, main.content or ""


def compute_schema(script) -> dict | None:
    """Resolve the script's INPUT_SCHEMA: static first, subprocess fallback.

    Pure (no DB write). Returns the schema dict or None if the script declares
    none / it couldn't be resolved.
    """
    entry = _main_file(script)
    if entry is None:
        return None
    main_filename, main_content = entry

    status, schema = _static_extract(main_content)
    if status == "ok":
        return schema
    if status == "absent":
        return None
    # status == "dynamic": the name is there but computed → introspect at runtime
    files = [(f.filename, f.content or "") for f in script.files]
    return _introspect(script.id, files, main_filename)


def refresh_script_schema(db, script) -> dict | None:
    """Recompute the script's input schema and persist it onto the row if it
    changed. Best-effort — never raises. Returns the resolved schema (or None)."""
    try:
        schema = compute_schema(script)
    except Exception:
        logger.exception("[script {}] schema refresh crashed", getattr(script, "id", "?"))
        return None
    if script.input_schema != schema:
        script.input_schema = schema
        try:
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("[script {}] failed to persist input_schema", script.id)
    return schema


# ── validation ──────────────────────────────────────────────────────────────

def validate_input(schema: dict | None, data: Any) -> None:
    """Validate `data` against `schema`. Raises ValueError with a concise message
    on mismatch. A missing / empty / structurally-invalid schema is a no-op (we
    never block a run because the *schema* is broken — only because the input is).
    """
    if not schema or not isinstance(schema, dict):
        return
    try:
        import jsonschema
        from jsonschema import Draft202012Validator
    except ImportError:
        return  # validator unavailable → skip rather than block
    try:
        Draft202012Validator.check_schema(schema)
    except Exception:
        logger.warning("input_schema is not a valid JSON Schema; skipping validation")
        return
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    if not errors:
        return
    e = errors[0]
    loc = "/".join(str(p) for p in e.path) or "(root)"
    raise ValueError(f"Input does not match schema at {loc}: {e.message}")
