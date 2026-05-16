import ast
import asyncio
import json
import keyword
from datetime import datetime
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from app.config import BACKEND_ROOT
from app.database import Base, SessionLocal, engine
from app.models import Execution, ExecutionLog, LLMConfig, Script, ScriptFile
from services.execution_engine import spawn_execution, stop_execution
from services.script_files import normalize_script_filename
from services.venv_manager import (
    delete_venv,
    list_installed_packages,
    stream_create_venv,
    stream_install,
    venv_exists,
)


AGENTFLOW_MCP_INSTRUCTIONS = """
AgentFlow MCP manages browser-authored LangGraph/LangChain Python scripts.

Recommended AI workflow:
1. Read agentflow://rules or call get_agentflow_rules before editing.
2. Use get_debug_context to inspect the script, latest run, logs, and platform rules.
3. Modify files with upsert_script_file; main.py must define the script entry function.
4. Run lint_script_file before run_script.
5. Use run_script for a blocking debug loop, then inspect returned logs/output/error.

Important contracts:
- The runner imports main.py and calls script.entry_function, default "run".
- Entry function signature is def run(input: dict) -> Any.
- Return values should be JSON-serializable.
- Use from agentflow import log, get_llm, list_llms inside user scripts.
- Structured logs written with log(...) are persisted and returned by execution tools.
- Each script may have an isolated venv; requirements are installed per script.
""".strip()


mcp = FastMCP(
    "AgentFlow",
    instructions=AGENTFLOW_MCP_INSTRUCTIONS,
    stateless_http=True,
    json_response=True,
    streamable_http_path="/",
)

_schema_ready = False


def _ensure_schema() -> None:
    global _schema_ready
    if not _schema_ready:
        Base.metadata.create_all(bind=engine)
        _schema_ready = True


def _db():
    _ensure_schema()
    return SessionLocal()


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=_json_default)


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _validate_entry_function(name: str) -> str:
    value = (name or "").strip()
    if not value:
        raise ToolError("entry_function is required")
    if not value.isidentifier() or keyword.iskeyword(value):
        raise ToolError("entry_function must be a valid Python identifier")
    return value


def _require_script(db, script_id: str) -> Script:
    script = db.query(Script).filter_by(id=script_id).first()
    if not script:
        raise ToolError(f"Script not found: {script_id}")
    return script


def _require_execution(db, execution_id: str) -> Execution:
    execution = db.query(Execution).filter_by(id=execution_id).first()
    if not execution:
        raise ToolError(f"Execution not found: {execution_id}")
    return execution


def _script_summary(script: Script) -> dict[str, Any]:
    return {
        "id": script.id,
        "name": script.name,
        "description": script.description or "",
        "entry_function": script.entry_function or "run",
        "requirements": script.requirements or "",
        "created_at": _dt(script.created_at),
        "updated_at": _dt(script.updated_at),
    }


def _file_payload(file: ScriptFile, include_content: bool = True) -> dict[str, Any]:
    payload = {
        "id": file.id,
        "script_id": file.script_id,
        "filename": file.filename,
        "is_main": bool(file.is_main),
        "updated_at": _dt(file.updated_at),
    }
    if include_content:
        payload["content"] = file.content or ""
    return payload


def _script_payload(script: Script, include_files: bool = True) -> dict[str, Any]:
    payload = _script_summary(script)
    if include_files:
        files = sorted(script.files, key=lambda f: (not f.is_main, f.filename))
        payload["files"] = [_file_payload(file) for file in files]
    return payload


def _log_payload(log: ExecutionLog) -> dict[str, Any]:
    return {
        "id": log.id,
        "timestamp": _dt(log.timestamp),
        "level": log.level,
        "message": log.message,
        "data": log.data,
        "step": log.step,
    }


def _execution_payload(
    db,
    execution: Execution,
    include_logs: bool = True,
    log_tail: int = 200,
) -> dict[str, Any]:
    payload = {
        "id": execution.id,
        "script_id": execution.script_id,
        "status": execution.status,
        "input_data": execution.input_data or {},
        "output_data": execution.output_data,
        "error": execution.error,
        "started_at": _dt(execution.started_at),
        "finished_at": _dt(execution.finished_at),
        "created_at": _dt(execution.created_at),
    }
    if include_logs:
        q = (
            db.query(ExecutionLog)
            .filter_by(execution_id=execution.id)
            .order_by(ExecutionLog.timestamp.asc())
        )
        logs = q.all()
        if log_tail > 0:
            logs = logs[-log_tail:]
        payload["logs"] = [_log_payload(log) for log in logs]
        payload["log_count"] = len(logs)
    return payload


def _read_execution(
    execution_id: str,
    include_logs: bool = True,
    log_tail: int = 200,
) -> dict[str, Any]:
    db = _db()
    try:
        execution = _require_execution(db, execution_id)
        return _execution_payload(db, execution, include_logs=include_logs, log_tail=log_tail)
    finally:
        db.close()


def _default_main(entry_fn: str) -> str:
    return f"""from agentflow import log, get_llm


def {entry_fn}(input: dict) -> dict:
    log("Script started", data=input, step="start")
    return {{"result": "ok"}}
"""


def _lint_source(source: str, filename: str, entry_function: str) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as e:
        issues.append({
            "line": e.lineno or 1,
            "col": e.offset or 1,
            "end_line": e.end_lineno or e.lineno or 1,
            "end_col": e.end_offset or (e.offset or 1) + 1,
            "message": e.msg or "syntax error",
            "severity": "error",
        })
        return issues

    if filename == "main.py":
        funcs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
        matches = [n for n in funcs if n.name == entry_function]
        if not matches:
            issues.append({
                "line": 1,
                "col": 1,
                "end_line": 1,
                "end_col": 1,
                "message": f"entry function `{entry_function}` not defined in main.py",
                "severity": "warning",
            })
        else:
            fn = matches[0]
            if len(fn.args.args) != 1:
                issues.append({
                    "line": fn.lineno,
                    "col": fn.col_offset + 1,
                    "end_line": getattr(fn, "end_lineno", fn.lineno),
                    "end_col": getattr(fn, "end_col_offset", fn.col_offset + 1),
                    "message": f"`{entry_function}` should accept exactly one dict input argument",
                    "severity": "warning",
                })
    return issues


def _read_claude_md() -> str:
    claude_path = BACKEND_ROOT.parent / "CLAUDE.md"
    try:
        return claude_path.read_text(encoding="utf-8")
    except Exception as e:
        return f"CLAUDE.md could not be read: {e}"


def _project_rules_text() -> str:
    return f"{AGENTFLOW_MCP_INSTRUCTIONS}\n\n# CLAUDE.md\n\n{_read_claude_md()}"


async def _collect_lines(stream, max_lines: int) -> list[str]:
    lines: list[str] = []
    async for line in stream:
        lines.append(str(line))
        if len(lines) > max_lines:
            lines = lines[-max_lines:]
    return lines


def _latest_execution(db, script_id: str) -> Execution | None:
    return (
        db.query(Execution)
        .filter_by(script_id=script_id)
        .order_by(Execution.created_at.desc())
        .first()
    )


@mcp.resource("agentflow://rules")
def rules_resource() -> str:
    """Project and script-authoring rules for AgentFlow."""
    return _project_rules_text()


@mcp.resource("agentflow://scripts")
def scripts_resource() -> str:
    """All AgentFlow script summaries as JSON."""
    return _json(list_scripts())


@mcp.resource("agentflow://scripts/{script_id}")
def script_resource(script_id: str) -> str:
    """One AgentFlow script, including files, as JSON."""
    return _json(get_script(script_id))


@mcp.resource("agentflow://executions/{execution_id}")
def execution_resource(execution_id: str) -> str:
    """One execution with persisted logs as JSON."""
    return _json(get_execution(execution_id))


@mcp.tool()
def get_agentflow_rules(include_claude: bool = True) -> dict[str, Any]:
    """Return the rules an AI should follow when authoring AgentFlow scripts."""
    return {
        "instructions": AGENTFLOW_MCP_INSTRUCTIONS,
        "claude_md": _read_claude_md() if include_claude else None,
    }


@mcp.tool()
def list_scripts(query: str | None = None, limit: int = 50) -> dict[str, Any]:
    """List script summaries. Use this before choosing a script to edit or run."""
    db = _db()
    try:
        q = db.query(Script).order_by(Script.updated_at.desc())
        if query:
            needle = f"%{query.strip()}%"
            q = q.filter(Script.name.ilike(needle))
        rows = q.limit(max(1, min(limit, 200))).all()
        return {"scripts": [_script_summary(script) for script in rows]}
    finally:
        db.close()


@mcp.tool()
def get_script(script_id: str) -> dict[str, Any]:
    """Read one script, including every stored file."""
    db = _db()
    try:
        script = _require_script(db, script_id)
        return _script_payload(script, include_files=True)
    finally:
        db.close()


@mcp.tool()
def create_script(
    name: str,
    description: str = "",
    entry_function: str = "run",
    requirements: str = "",
    main_py: str | None = None,
) -> dict[str, Any]:
    """Create a script with main.py. Returns the created script and lint issues."""
    entry_function = _validate_entry_function(entry_function)
    if not (name or "").strip():
        raise ToolError("name is required")

    content = main_py if main_py is not None else _default_main(entry_function)
    db = _db()
    try:
        script = Script(
            name=name.strip(),
            description=description or "",
            entry_function=entry_function,
            requirements=requirements or "",
        )
        db.add(script)
        db.flush()
        db.add(ScriptFile(
            script_id=script.id,
            filename="main.py",
            content=content,
            is_main=True,
        ))
        db.commit()
        db.refresh(script)
        return {
            "script": _script_payload(script, include_files=True),
            "lint": _lint_source(content, "main.py", entry_function),
        }
    finally:
        db.close()


@mcp.tool()
def update_script_metadata(
    script_id: str,
    name: str | None = None,
    description: str | None = None,
    entry_function: str | None = None,
    requirements: str | None = None,
) -> dict[str, Any]:
    """Update script metadata such as name, entry function, or requirements."""
    db = _db()
    try:
        script = _require_script(db, script_id)
        if name is not None:
            if not name.strip():
                raise ToolError("name must not be empty")
            script.name = name.strip()
        if description is not None:
            script.description = description
        if entry_function is not None:
            script.entry_function = _validate_entry_function(entry_function)
        if requirements is not None:
            script.requirements = requirements
        db.commit()
        db.refresh(script)
        return {"script": _script_payload(script, include_files=True)}
    finally:
        db.close()


@mcp.tool()
def upsert_script_file(
    script_id: str,
    filename: str,
    content: str,
    is_main: bool = False,
) -> dict[str, Any]:
    """Create or replace a script file. main.py is the file the runner imports."""
    try:
        filename = normalize_script_filename(filename)
    except ValueError as e:
        raise ToolError(str(e))
    if is_main and filename != "main.py":
        raise ToolError("AgentFlow executes main.py; only main.py can be marked as main")

    db = _db()
    try:
        script = _require_script(db, script_id)
        file = db.query(ScriptFile).filter_by(script_id=script_id, filename=filename).first()
        if file:
            file.content = content
            file.is_main = is_main or file.is_main
        else:
            file = ScriptFile(
                script_id=script_id,
                filename=filename,
                content=content,
                is_main=is_main,
            )
            db.add(file)
        if filename == "main.py":
            file.is_main = True
        if file.is_main:
            for other in script.files:
                if other.filename != filename:
                    other.is_main = False
        db.commit()
        db.refresh(file)
        payload = {"file": _file_payload(file)}
        if filename.endswith(".py"):
            payload["lint"] = _lint_source(content, filename, script.entry_function or "run")
        return payload
    finally:
        db.close()


@mcp.tool()
def delete_script_file(script_id: str, filename: str) -> dict[str, Any]:
    """Delete a non-main file from a script."""
    try:
        filename = normalize_script_filename(filename)
    except ValueError as e:
        raise ToolError(str(e))
    db = _db()
    try:
        _require_script(db, script_id)
        file = db.query(ScriptFile).filter_by(script_id=script_id, filename=filename).first()
        if not file:
            raise ToolError(f"File not found: {filename}")
        if file.is_main or filename == "main.py":
            raise ToolError("Cannot delete main.py")
        db.delete(file)
        db.commit()
        return {"deleted": True, "script_id": script_id, "filename": filename}
    finally:
        db.close()


@mcp.tool()
def delete_script(script_id: str, delete_script_venv: bool = False) -> dict[str, Any]:
    """Delete a script and optionally remove its per-script venv directory."""
    db = _db()
    try:
        script = _require_script(db, script_id)
        db.delete(script)
        db.commit()
    finally:
        db.close()

    removed_venv = delete_venv(script_id) if delete_script_venv else False
    return {"deleted": True, "script_id": script_id, "removed_venv": removed_venv}


@mcp.tool()
def lint_script_file(
    script_id: str,
    filename: str = "main.py",
    source: str | None = None,
) -> dict[str, Any]:
    """Run static Python syntax checks and entry-function checks for a script file."""
    try:
        filename = normalize_script_filename(filename)
    except ValueError as e:
        raise ToolError(str(e))
    db = _db()
    try:
        script = _require_script(db, script_id)
        if source is None:
            file = db.query(ScriptFile).filter_by(script_id=script_id, filename=filename).first()
            if not file:
                raise ToolError(f"File not found: {filename}")
            source = file.content or ""
        issues = _lint_source(source, filename, script.entry_function or "run")
        return {"ok": not any(i["severity"] == "error" for i in issues), "issues": issues}
    finally:
        db.close()


@mcp.tool()
async def prepare_script_venv(
    script_id: str,
    force: bool = False,
    install_requirements: bool = False,
    max_log_lines: int = 400,
) -> dict[str, Any]:
    """Create or recreate a script venv, optionally installing requirements after creation."""
    db = _db()
    try:
        script = _require_script(db, script_id)
        requirements = script.requirements or ""
    finally:
        db.close()

    max_log_lines = max(20, min(max_log_lines, 2000))
    lines = await _collect_lines(stream_create_venv(script_id, force=force), max_log_lines)
    if install_requirements:
        lines.extend(await _collect_lines(stream_install(script_id, requirements), max_log_lines))
        lines = lines[-max_log_lines:]
    return {
        "script_id": script_id,
        "venv_exists": venv_exists(script_id),
        "log": lines,
    }


@mcp.tool()
async def install_script_requirements(
    script_id: str,
    max_log_lines: int = 400,
) -> dict[str, Any]:
    """Install the script's requirements.txt into its venv and return pip/uv output."""
    db = _db()
    try:
        script = _require_script(db, script_id)
        requirements = script.requirements or ""
    finally:
        db.close()

    if not venv_exists(script_id):
        raise ToolError("venv does not exist; call prepare_script_venv first")
    max_log_lines = max(20, min(max_log_lines, 2000))
    lines = await _collect_lines(stream_install(script_id, requirements), max_log_lines)
    return {"script_id": script_id, "venv_exists": venv_exists(script_id), "log": lines}


@mcp.tool()
def list_script_packages(script_id: str) -> dict[str, Any]:
    """List packages installed in the script's isolated venv."""
    db = _db()
    try:
        _require_script(db, script_id)
    finally:
        db.close()
    packages, error = list_installed_packages(script_id)
    return {"script_id": script_id, "packages": packages, "error": error}


@mcp.tool()
def list_llm_configs() -> dict[str, Any]:
    """List configured LLMs without exposing API keys."""
    db = _db()
    try:
        rows = db.query(LLMConfig).order_by(LLMConfig.created_at.desc()).all()
        return {
            "llm_configs": [
                {
                    "id": row.id,
                    "name": row.name,
                    "provider": row.provider,
                    "model": row.model,
                    "base_url": row.base_url,
                    "is_default": bool(row.is_default),
                    "has_api_key": bool(row.api_key),
                    "extra_config": row.extra_config or {},
                    "created_at": _dt(row.created_at),
                }
                for row in rows
            ]
        }
    finally:
        db.close()


@mcp.tool()
async def start_script_execution(
    script_id: str,
    input_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Start a script run and return immediately with an execution id."""
    if input_data is not None and not isinstance(input_data, dict):
        raise ToolError("input_data must be an object")
    db = _db()
    try:
        _require_script(db, script_id)
        execution = Execution(script_id=script_id, input_data=input_data or {})
        db.add(execution)
        db.commit()
        db.refresh(execution)
        execution_id = execution.id
    finally:
        db.close()

    spawn_execution(execution_id)
    return {
        "execution_id": execution_id,
        "status": "pending",
        "next": "Call get_execution to poll logs/status, or stop_execution to cancel.",
    }


@mcp.tool()
async def run_script(
    script_id: str,
    input_data: dict[str, Any] | None = None,
    timeout_seconds: float = 300.0,
    create_venv_if_missing: bool = False,
    install_requirements: bool = False,
    log_tail: int = 200,
) -> dict[str, Any]:
    """Run a script synchronously for AI debugging and return status, output, error, and logs."""
    if input_data is not None and not isinstance(input_data, dict):
        raise ToolError("input_data must be an object")
    timeout_seconds = max(1.0, min(float(timeout_seconds), 3600.0))

    db = _db()
    try:
        script = _require_script(db, script_id)
        requirements = script.requirements or ""
    finally:
        db.close()

    preparation: list[str] = []
    if create_venv_if_missing and not venv_exists(script_id):
        preparation = await _collect_lines(stream_create_venv(script_id, force=False), 200)
    if install_requirements:
        if not venv_exists(script_id):
            raise ToolError("venv does not exist; set create_venv_if_missing=true or prepare it first")
        preparation.extend(await _collect_lines(stream_install(script_id, requirements), 200))

    db = _db()
    try:
        execution = Execution(script_id=script_id, input_data=input_data or {})
        db.add(execution)
        db.commit()
        db.refresh(execution)
        execution_id = execution.id
    finally:
        db.close()

    timed_out = False
    task = spawn_execution(execution_id)
    try:
        await asyncio.wait_for(task, timeout=timeout_seconds)
    except asyncio.TimeoutError:
        timed_out = True
        await stop_execution(execution_id)

    return {
        "timed_out": timed_out,
        "preparation_log": preparation[-200:],
        "execution": _read_execution(execution_id, include_logs=True, log_tail=log_tail),
    }


@mcp.tool()
def get_execution(
    execution_id: str,
    include_logs: bool = True,
    log_tail: int = 200,
) -> dict[str, Any]:
    """Read one execution, including persisted logs by default."""
    return _read_execution(
        execution_id,
        include_logs=include_logs,
        log_tail=max(0, min(log_tail, 2000)),
    )


@mcp.tool()
def list_executions(
    script_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """List recent executions, optionally filtered by script id and status."""
    db = _db()
    try:
        q = db.query(Execution).order_by(Execution.created_at.desc())
        if script_id:
            q = q.filter_by(script_id=script_id)
        if status:
            q = q.filter_by(status=status)
        rows = q.limit(max(1, min(limit, 200))).all()
        return {"executions": [_execution_payload(db, row, include_logs=False) for row in rows]}
    finally:
        db.close()


@mcp.tool()
async def stop_script_execution(execution_id: str) -> dict[str, Any]:
    """Stop a running execution subprocess and return the persisted execution state."""
    stopped = await stop_execution(execution_id)
    db = _db()
    try:
        execution = _require_execution(db, execution_id)
        if execution.status in ("running", "pending"):
            execution.status = "cancelled"
            execution.finished_at = datetime.utcnow()
            db.commit()
            db.refresh(execution)
        return {"stopped": stopped, "execution": _execution_payload(db, execution)}
    finally:
        db.close()


@mcp.tool()
def get_debug_context(
    script_id: str | None = None,
    execution_id: str | None = None,
    log_tail: int = 200,
) -> dict[str, Any]:
    """Return rules, script files, and execution logs in one payload for debugging."""
    db = _db()
    try:
        execution = None
        if execution_id:
            execution = _require_execution(db, execution_id)
            script = _require_script(db, execution.script_id)
        elif script_id:
            script = _require_script(db, script_id)
            execution = _latest_execution(db, script_id)
        else:
            raise ToolError("Provide script_id or execution_id")

        return {
            "rules": AGENTFLOW_MCP_INSTRUCTIONS,
            "script": _script_payload(script, include_files=True),
            "execution": (
                _execution_payload(db, execution, include_logs=True, log_tail=log_tail)
                if execution else None
            ),
            "llms": list_llm_configs()["llm_configs"],
        }
    finally:
        db.close()


@mcp.prompt(title="Write or debug an AgentFlow script")
def agentflow_script_prompt(task: str, script_id: str = "", execution_id: str = "") -> str:
    """Prompt template for AI clients that support MCP prompts."""
    target = []
    if script_id:
        target.append(f"script_id={script_id}")
    if execution_id:
        target.append(f"execution_id={execution_id}")
    target_text = ", ".join(target) or "no existing target"
    return f"""
You are helping with an AgentFlow script task: {task}

Target: {target_text}

Use this MCP workflow:
1. Read get_agentflow_rules.
2. Read get_debug_context for the target script or execution.
3. Edit files with upsert_script_file.
4. Run lint_script_file on main.py.
5. Run run_script with representative input and inspect logs, output, and error.

Keep main.py defining the configured entry function, and use agentflow.log for useful debug logs.
""".strip()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
