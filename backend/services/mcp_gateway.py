"""
Outward-facing MCP server ("gateway") — lets external coding agents (Claude Code,
Cursor, any MCP client) develop AgentFlow scripts remotely: create/edit script
files, set up the venv, run scripts and read execution logs.

Transport: Streamable HTTP, stateless, JSON responses — mounted at `/mcp` in
`app/main.py`. Every request must carry an issued API key (`Authorization:
Bearer af_…` or `X-API-Key`) or an admin session Bearer token; the gate is the
ASGI wrapper `build_gateway_asgi()` below, reusing the same `api_keys` table as
`POST /api/executions/run`. Note this widens what an API key can do (script CRUD
+ run, not just run) — keys are admin-issued, single-admin trust model.

The scripting guide served by `get_scripting_guide` is the Agent Skill shipped at
`backend/assets/skills/agentflow-scripting/SKILL.md` (also downloadable via
`GET /mcp/skill` for installing into a client's skills folder) — one source of
truth for "how to write AgentFlow scripts".
"""
from __future__ import annotations

import ast
import asyncio
import json
from datetime import datetime
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from app.database import SessionLocal
from app.models import (
    Channel, EvalCase, EvalRun, Execution, ExecutionLog, MCPServerConfig,
    Script, ScriptFile, SearchConfig, Secret,
)
from services.script_files import normalize_script_filename
from services.venv_manager import stream_create_venv, stream_install, venv_exists

ASSETS_DIR = Path(__file__).resolve().parents[1] / "assets"
SKILL_MD = ASSETS_DIR / "skills" / "agentflow-scripting" / "SKILL.md"

RUN_TIMEOUT_DEFAULT = 300.0
RUN_TIMEOUT_MAX = 3600.0

_INSTRUCTIONS = """\
AgentFlow script development gateway. AgentFlow runs user-written Python scripts
(LangGraph/LangChain agents) in per-script virtualenvs.

Typical loop: get_platform_context → create_script → write_script_file (main.py)
→ setup_script_env (once per new script / after changing requirements) →
run_script → fix from the returned traceback → run_script again.

Call get_scripting_guide before writing your first script — it documents the
script contract (entry `def run(input: dict)`), the `agentflow` SDK
(get_llm/get_agent/get_tools/get_secret/log/token/...) and the chat conventions.
"""

gateway = FastMCP(
    "agentflow",
    instructions=_INSTRUCTIONS,
    stateless_http=True,
    streamable_http_path="/",
    json_response=True,
)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() + "Z" if dt else None


def _script_or_error(db, script_id: str) -> Script | None:
    return db.query(Script).filter_by(id=script_id).first()


def _lint_source(source: str, filename: str, entry_function: str | None) -> list[dict]:
    """Same checks as POST /api/scripts/{id}/lint: ast syntax + entry presence."""
    issues: list[dict] = []
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as e:
        return [{
            "line": e.lineno or 1, "col": e.offset or 1,
            "message": e.msg or "syntax error", "severity": "error",
        }]
    if entry_function:
        names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)}
        if entry_function not in names:
            issues.append({
                "line": 1, "col": 1,
                "message": f"entry function `{entry_function}` not defined in this file",
                "severity": "warning",
            })
    return issues


# ── Platform context ───────────────────────────────────────────────────────────

@gateway.tool()
def get_platform_context() -> dict:
    """Discover what this AgentFlow instance offers scripts: available LLM model
    ids (+ the default model), secret keys readable via get_secret(), MCP servers
    a script can bind (script.mcp_server_ids), platform skills a script can bind
    (script.skill_ids), and the web-search provider. Call this before writing
    code that references models, secrets, MCP servers or skills."""
    db = SessionLocal()
    try:
        channels = (
            db.query(Channel).filter_by(enabled=True)
            .order_by(Channel.priority.desc(), Channel.created_at.asc()).all()
        )
        models: list[str] = []
        default_model = None
        for ch in channels:
            for m in ch.models or []:
                if m not in models:
                    models.append(m)
            if ch.is_default and ch.default_model and not default_model:
                default_model = ch.default_model
        secret_keys = [s.key for s in db.query(Secret).order_by(Secret.key).all()]
        mcp_servers = [
            {"id": s.id, "name": s.name, "transport": s.transport, "enabled": s.enabled}
            for s in db.query(MCPServerConfig).order_by(MCPServerConfig.name).all()
        ]
        cfg = db.query(SearchConfig).filter_by(id="default").first()
        search_provider = (cfg.provider if cfg and cfg.tavily_api_key else "duckduckgo")
    finally:
        db.close()

    try:
        from services.skill_store import list_skills as _list_skills
        skills = [
            {"id": s.get("id"), "name": s.get("name"),
             "description": s.get("description"), "enabled": s.get("enabled")}
            for s in _list_skills()
        ]
    except Exception:
        skills = []

    return {
        "llm_models": models,
        "default_model": default_model,
        "secret_keys": secret_keys,
        "mcp_servers": mcp_servers,
        "skills": skills,
        "web_search_provider": search_provider,
    }


@gateway.tool()
def get_scripting_guide() -> str:
    """The full AgentFlow scripting guide: script contract, `agentflow` SDK
    reference (get_llm/get_agent/get_tools/secrets/logging/streaming), chat-page
    conventions and gotchas. Read it before writing your first script."""
    try:
        return SKILL_MD.read_text(encoding="utf-8")
    except OSError as e:
        return f"guide unavailable: {e}"


# ── Scripts ────────────────────────────────────────────────────────────────────

@gateway.tool()
def list_scripts() -> list[dict]:
    """List all scripts on this AgentFlow instance (id, name, description,
    entry_function, whether its venv exists)."""
    db = SessionLocal()
    try:
        return [
            {
                "id": s.id, "name": s.name, "description": s.description or "",
                "entry_function": s.entry_function, "venv_ready": venv_exists(s.id),
                "updated_at": _iso(s.updated_at),
            }
            for s in db.query(Script).order_by(Script.updated_at.desc()).all()
        ]
    finally:
        db.close()


@gateway.tool()
def get_script(script_id: str) -> dict:
    """Get one script's full config: metadata, requirements, bound MCP servers /
    skills, and its file list (names only — use read_script_file for content)."""
    db = SessionLocal()
    try:
        s = _script_or_error(db, script_id)
        if not s:
            return {"error": f"script {script_id} not found"}
        return {
            "id": s.id, "name": s.name, "description": s.description or "",
            "entry_function": s.entry_function,
            "requirements": s.requirements or "",
            "mcp_server_ids": s.mcp_server_ids or [],
            "skill_ids": s.skill_ids or [],
            "venv_ready": venv_exists(s.id),
            "files": [
                {"filename": f.filename, "is_main": f.is_main, "bytes": len(f.content or "")}
                for f in s.files
            ],
        }
    finally:
        db.close()


@gateway.tool()
def create_script(
    name: str,
    description: str = "",
    entry_function: str = "run",
    requirements: str = "",
) -> dict:
    """Create a new script with a stub main.py. Overwrite main.py with
    write_script_file, then call setup_script_env once so the script has a venv
    with the LangChain baseline installed."""
    db = SessionLocal()
    try:
        s = Script(
            name=name, description=description,
            entry_function=entry_function or "run", requirements=requirements,
        )
        db.add(s)
        db.flush()
        stub = (
            "from agentflow import log, get_llm\n\n\n"
            f"def {s.entry_function}(input: dict) -> dict:\n"
            "    log(\"Script started\", data=input)\n"
            "    return {\"result\": \"ok\"}\n"
        )
        db.add(ScriptFile(script_id=s.id, filename="main.py", content=stub, is_main=True))
        db.commit()
        return {"id": s.id, "name": s.name, "entry_function": s.entry_function,
                "files": ["main.py"], "main_py": stub}
    finally:
        db.close()


@gateway.tool()
def update_script(
    script_id: str,
    name: str | None = None,
    description: str | None = None,
    entry_function: str | None = None,
    requirements: str | None = None,
    mcp_server_ids: list[str] | None = None,
    skill_ids: list[str] | None = None,
) -> dict:
    """Update script config. `requirements` is the pip requirements.txt content
    (run setup_script_env afterwards to install). `mcp_server_ids` /
    `skill_ids` bind platform MCP servers / skills to the script — ids come
    from get_platform_context."""
    db = SessionLocal()
    try:
        s = _script_or_error(db, script_id)
        if not s:
            return {"error": f"script {script_id} not found"}
        for field, value in {
            "name": name, "description": description, "entry_function": entry_function,
            "requirements": requirements, "mcp_server_ids": mcp_server_ids,
            "skill_ids": skill_ids,
        }.items():
            if value is not None:
                setattr(s, field, value)
        db.commit()
        return {"ok": True, "id": s.id, "entry_function": s.entry_function,
                "requirements": s.requirements or "",
                "mcp_server_ids": s.mcp_server_ids or [], "skill_ids": s.skill_ids or []}
    finally:
        db.close()


# ── Files ──────────────────────────────────────────────────────────────────────

@gateway.tool()
def read_script_file(script_id: str, filename: str) -> dict:
    """Read one script file's content."""
    db = SessionLocal()
    try:
        try:
            filename = normalize_script_filename(filename)
        except ValueError as e:
            return {"error": str(e)}
        f = db.query(ScriptFile).filter_by(script_id=script_id, filename=filename).first()
        if not f:
            return {"error": f"file {filename!r} not found in script {script_id}"}
        return {"filename": f.filename, "is_main": f.is_main, "content": f.content or ""}
    finally:
        db.close()


@gateway.tool()
def write_script_file(script_id: str, filename: str, content: str) -> dict:
    """Create or overwrite a script file (nested paths like `lib/util.py` are
    allowed). For .py files the response includes syntax-lint issues — fix any
    `error`-severity issue before running."""
    db = SessionLocal()
    try:
        s = _script_or_error(db, script_id)
        if not s:
            return {"error": f"script {script_id} not found"}
        try:
            filename = normalize_script_filename(filename)
        except ValueError as e:
            return {"error": str(e)}
        f = db.query(ScriptFile).filter_by(script_id=script_id, filename=filename).first()
        if f:
            f.content = content
        else:
            f = ScriptFile(script_id=script_id, filename=filename, content=content,
                           is_main=(filename == "main.py" and not any(x.is_main for x in s.files)))
            db.add(f)
        db.commit()
        issues = []
        if filename.endswith(".py"):
            issues = _lint_source(
                content, filename, s.entry_function if f.is_main else None,
            )
        return {"ok": True, "filename": filename, "is_main": f.is_main, "lint_issues": issues}
    finally:
        db.close()


@gateway.tool()
def delete_script_file(script_id: str, filename: str) -> dict:
    """Delete a script file (the main file cannot be deleted)."""
    db = SessionLocal()
    try:
        try:
            filename = normalize_script_filename(filename)
        except ValueError as e:
            return {"error": str(e)}
        f = db.query(ScriptFile).filter_by(script_id=script_id, filename=filename).first()
        if not f:
            return {"error": f"file {filename!r} not found"}
        if f.is_main:
            return {"error": "cannot delete the main file"}
        db.delete(f)
        db.commit()
        return {"ok": True}
    finally:
        db.close()


# ── Skills (Agent Skills: SKILL.md + supporting files, edited on disk) ──────────

@gateway.tool()
def list_skills() -> list[dict]:
    """List all skills. Returns [{skill_id, name, description, enabled}]; skill_id
    is the folder name — use it with the other skill_* tools."""
    from services import skill_store
    return [
        {"skill_id": s["id"], "name": s["name"], "description": s.get("description", ""),
         "enabled": s.get("enabled", True)}
        for s in skill_store.list_skills()
    ]


@gateway.tool()
def get_skill(skill_id: str) -> dict:
    """Get a skill's metadata + file list. Returns {skill_id, name, description,
    enabled, files:[{filename,is_main,bytes}], dirs}."""
    from services import skill_store
    try:
        s = skill_store.get_skill(skill_id)
    except FileNotFoundError:
        return {"error": f"skill {skill_id!r} not found"}
    return {
        "skill_id": s["id"], "name": s["name"], "description": s.get("description", ""),
        "enabled": s.get("enabled", True),
        "files": [{"filename": f["filename"], "is_main": f["is_main"],
                   "bytes": len(f["content"] or "")} for f in s["files"]],
        "dirs": s.get("dirs", []),
    }


@gateway.tool()
def read_skill_file(skill_id: str, filename: str) -> dict:
    """Read one skill file's content (e.g. SKILL.md or a supporting file)."""
    from services import skill_store
    try:
        s = skill_store.get_skill(skill_id)
    except FileNotFoundError:
        return {"error": f"skill {skill_id!r} not found"}
    for f in s["files"]:
        if f["filename"] == filename:
            return {"filename": f["filename"], "is_main": f["is_main"], "content": f["content"] or ""}
    return {"error": f"file {filename!r} not found in skill {skill_id}"}


@gateway.tool()
def write_skill_file(skill_id: str, filename: str, content: str) -> dict:
    """Create or overwrite a file inside a skill. SKILL.md is the main instruction
    file (YAML frontmatter `name`/`description` + markdown); supporting files and
    nested paths like `references/x.md` are allowed."""
    from services import skill_store
    if not skill_store.exists(skill_id):
        return {"error": f"skill {skill_id!r} not found"}
    try:
        r = skill_store.upsert_file(skill_id, filename, content, is_main=(filename == "SKILL.md"))
    except ValueError as e:
        return {"error": str(e)}
    return {"ok": True, "filename": r.get("filename", filename), "is_main": r.get("is_main", False)}


@gateway.tool()
def create_skill(name: str, description: str = "") -> dict:
    """Create a new skill (folder + a starter SKILL.md). Returns {skill_id, name}."""
    from services import skill_store
    s = skill_store.create_skill(name, description)
    return {"skill_id": s["id"], "name": s["name"]}


@gateway.tool()
def delete_skill_file(skill_id: str, filename: str) -> dict:
    """Delete a file from a skill (SKILL.md cannot be deleted)."""
    from services import skill_store
    try:
        skill_store.delete_file(skill_id, filename)
    except Exception as e:
        return {"error": str(e)}
    return {"ok": True}


# ── Environment ────────────────────────────────────────────────────────────────

@gateway.tool()
async def setup_script_env(script_id: str, force: bool = False) -> dict:
    """Create the script's virtualenv (baseline: langchain/langgraph/deepagents
    stack) and install its requirements. Call once for a brand-new script and
    again after changing requirements. First-time setup downloads packages and
    can take several minutes — wait for it, don't retry. `force=True` recreates
    the venv from scratch."""
    db = SessionLocal()
    try:
        s = _script_or_error(db, script_id)
        if not s:
            return {"error": f"script {script_id} not found"}
        requirements = s.requirements or ""
    finally:
        db.close()

    lines: list[str] = []
    async for line in stream_create_venv(script_id, force=force):
        lines.append(line)
    failed = any(l.startswith("ERROR:") for l in lines)
    if not failed and requirements.strip():
        async for line in stream_install(script_id, requirements):
            lines.append(line)
        failed = any(l.startswith("ERROR:") for l in lines)
    return {
        "ok": not failed and venv_exists(script_id),
        "venv_ready": venv_exists(script_id),
        "output_tail": lines[-30:],
    }


# ── Run & debug ────────────────────────────────────────────────────────────────

@gateway.tool()
async def run_script(script_id: str, input_data: dict | None = None,
                     timeout: float = RUN_TIMEOUT_DEFAULT) -> dict:
    """Run a script and block until it finishes (like POST /api/executions/run).
    Returns status, output_data and error; on failure the error logs (traceback)
    are included so you can fix the script in one round-trip. Raise `timeout`
    (seconds, max 3600) for long jobs."""
    from services.execution_engine import spawn_execution, stop_execution

    timeout = max(1.0, min(float(timeout), RUN_TIMEOUT_MAX))
    db = SessionLocal()
    try:
        if not _script_or_error(db, script_id):
            return {"error": f"script {script_id} not found"}
        exc = Execution(script_id=script_id, input_data=input_data or {})
        db.add(exc)
        db.commit()
        db.refresh(exc)
        execution_id = exc.id
    finally:
        db.close()

    task = spawn_execution(execution_id)
    try:
        await asyncio.wait_for(task, timeout=timeout)
    except asyncio.TimeoutError:
        await stop_execution(execution_id)
        return {"execution_id": execution_id, "status": "cancelled",
                "error": f"execution exceeded {timeout}s timeout and was stopped"}

    db = SessionLocal()
    try:
        final = db.query(Execution).filter_by(id=execution_id).first()
        result = {
            "execution_id": final.id,
            "status": final.status,
            "output_data": final.output_data,
            "error": final.error,
            "started_at": _iso(final.started_at),
            "finished_at": _iso(final.finished_at),
        }
        if final.status != "completed":
            result["error_logs"] = [
                {"message": l.message, "step": l.step}
                for l in db.query(ExecutionLog)
                .filter_by(execution_id=execution_id, level="error")
                .order_by(ExecutionLog.timestamp).limit(10).all()
            ]
        return result
    finally:
        db.close()


@gateway.tool()
def list_executions(script_id: str, limit: int = 10) -> list[dict]:
    """List recent executions of a script, newest first."""
    db = SessionLocal()
    try:
        rows = (
            db.query(Execution).filter_by(script_id=script_id)
            .order_by(Execution.created_at.desc()).limit(max(1, min(limit, 100))).all()
        )
        return [
            {"execution_id": e.id, "status": e.status, "error": e.error,
             "created_at": _iso(e.created_at), "finished_at": _iso(e.finished_at)}
            for e in rows
        ]
    finally:
        db.close()


@gateway.tool()
def get_execution_logs(execution_id: str, level: str | None = None,
                       limit: int = 100) -> dict:
    """Full log stream of a past execution (structured `log()` lines, stdout
    `raw` lines, tracebacks). Optionally filter by level: info/warning/error/
    node/debug/raw."""
    db = SessionLocal()
    try:
        exc = db.query(Execution).filter_by(id=execution_id).first()
        if not exc:
            return {"error": f"execution {execution_id} not found"}
        q = db.query(ExecutionLog).filter_by(execution_id=execution_id)
        if level:
            q = q.filter_by(level=level)
        rows = q.order_by(ExecutionLog.timestamp).limit(max(1, min(limit, 1000))).all()
        return {
            "execution_id": execution_id,
            "status": exc.status,
            "output_data": exc.output_data,
            "error": exc.error,
            "logs": [
                {"ts": _iso(l.timestamp), "level": l.level, "step": l.step,
                 "message": l.message,
                 "data": l.data if isinstance(l.data, (dict, list)) else None}
                for l in rows
            ],
        }
    finally:
        db.close()


# ── eval / regression (test dataset + graded runs) ────────────────────────────

@gateway.tool()
def list_eval_cases(script_id: str) -> list[dict]:
    """List a script's eval test cases (id, name, input, assertions). An eval
    case is an input + assertions the script's output must satisfy; run_eval
    grades them all into a pass/fail score."""
    db = SessionLocal()
    try:
        return [
            {"id": c.id, "name": c.name, "input_json": c.input_json,
             "assertions": c.assertions or []}
            for c in db.query(EvalCase).filter_by(script_id=script_id)
            .order_by(EvalCase.created_at).all()
        ]
    finally:
        db.close()


@gateway.tool()
def add_eval_case(script_id: str, name: str, input_json: str,
                  assertions: list[dict]) -> dict:
    """Add one eval test case to a script's dataset.

    - input_json: a JSON object string, the input passed to the script, e.g.
      '{"message": "how do I get a refund?"}'
    - assertions: a list of checks the output must pass, each
      {"type": ..., "value": ..., "threshold"?: int}:
        contains / not_contains : substring is / isn't in the output
        regex                   : output matches the pattern
        equals                  : output equals value exactly
        judge                   : an LLM scores the output 0-10 against `value`
                                  (a criterion), passes if >= threshold (default 7)
      e.g. [{"type":"contains","value":"7 days"},
            {"type":"judge","value":"is the tone polite and helpful?","threshold":7}]
    """
    try:
        obj = json.loads(input_json or "{}")
        if not isinstance(obj, dict):
            return {"error": "input_json must be a JSON object"}
    except json.JSONDecodeError as e:
        return {"error": f"input_json is not valid JSON: {e}"}
    db = SessionLocal()
    try:
        if not _script_or_error(db, script_id):
            return {"error": f"script {script_id} not found"}
        case = EvalCase(
            script_id=script_id, name=name or "case",
            input_json=input_json or "{}",
            assertions=[a for a in (assertions or []) if isinstance(a, dict)],
        )
        db.add(case)
        db.commit()
        db.refresh(case)
        return {"id": case.id, "name": case.name}
    finally:
        db.close()


@gateway.tool()
def update_eval_case(case_id: str, name: str | None = None,
                     input_json: str | None = None,
                     assertions: list[dict] | None = None) -> dict:
    """Update an eval test case (get its id from list_eval_cases). Pass only the
    fields to change — name, input_json (a JSON object string), and/or assertions
    (same shape as add_eval_case). Omitted fields are left unchanged."""
    if input_json is not None:
        try:
            obj = json.loads(input_json or "{}")
            if not isinstance(obj, dict):
                return {"error": "input_json must be a JSON object"}
        except json.JSONDecodeError as e:
            return {"error": f"input_json is not valid JSON: {e}"}
    db = SessionLocal()
    try:
        case = db.query(EvalCase).filter_by(id=case_id).first()
        if not case:
            return {"error": f"eval case {case_id} not found"}
        if name is not None:
            case.name = name
        if input_json is not None:
            case.input_json = input_json
        if assertions is not None:
            case.assertions = [a for a in assertions if isinstance(a, dict)]
        db.commit()
        return {"id": case.id, "name": case.name}
    finally:
        db.close()


@gateway.tool()
def delete_eval_case(case_id: str) -> dict:
    """Delete an eval test case by id (from list_eval_cases)."""
    db = SessionLocal()
    try:
        case = db.query(EvalCase).filter_by(id=case_id).first()
        if not case:
            return {"error": f"eval case {case_id} not found"}
        db.delete(case)
        db.commit()
        return {"deleted": case_id}
    finally:
        db.close()


@gateway.tool()
async def run_eval(script_id: str, timeout: float = 600.0) -> dict:
    """Run a script's whole eval dataset and block until it finishes. Each case
    is executed through the real engine, then graded. Returns the pass/total
    score plus per-case results (which assertions failed and why) so you can fix
    the script and re-run. Add cases first with add_eval_case."""
    from services.eval_engine import start_eval_run

    timeout = max(1.0, min(float(timeout), RUN_TIMEOUT_MAX))
    db = SessionLocal()
    try:
        if not _script_or_error(db, script_id):
            return {"error": f"script {script_id} not found"}
        n = db.query(EvalCase).filter_by(script_id=script_id).count()
        if n == 0:
            return {"error": "no eval cases to run — add some with add_eval_case first"}
        run = EvalRun(script_id=script_id, status="running", total=n)
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id
    finally:
        db.close()

    start_eval_run(run_id)
    # Poll the run row until it leaves "running" (the engine runs cases in a
    # background task; this makes the tool a single blocking round-trip).
    waited = 0.0
    while waited < timeout:
        await asyncio.sleep(1.0)
        waited += 1.0
        db = SessionLocal()
        try:
            run = db.query(EvalRun).filter_by(id=run_id).first()
            if run and run.status != "running":
                return {
                    "run_id": run.id, "status": run.status,
                    "passed": run.passed, "total": run.total,
                    "error": run.error, "results": run.results_json or [],
                }
        finally:
            db.close()
    return {"run_id": run_id, "status": "running",
            "error": f"eval still running after {timeout:.0f}s (results not ready yet)"}


# ── ASGI middleware (routing + auth gate) ─────────────────────────────────────

class MCPGatewayMiddleware:
    """Pure-ASGI middleware wrapping the whole FastAPI app. Intercepts, before
    routing:

      * POST/GET/DELETE `/mcp` (trailing slash optional) → the FastMCP
        streamable-HTTP app, behind the API-key gate. A plain `Mount("/mcp")`
        can't do this: current Starlette mounts don't match the bare `/mcp`
        path (it fell through to the frontend catch-all → 405) and no longer
        rewrite `scope["path"]` for children.
      * GET `/mcp/skill` → the (non-sensitive) agentflow-scripting SKILL.md so
        clients can install it locally. Public, like /health.

    Auth reuses the same credentials as POST /api/executions/run — an issued
    API key (`X-API-Key` / `Authorization: Bearer af_…`) or an admin session
    Bearer token. No new auth scheme."""

    def __init__(self, app):
        self.app = app
        # Also instantiates gateway.session_manager, which app/main.py's
        # lifespan runs (`async with gateway.session_manager.run():`).
        self.mcp_app = gateway.streamable_http_app()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        root = scope.get("root_path") or ""
        path = scope.get("path") or ""
        rel = path[len(root):] if root and path.startswith(root) else path

        if rel in ("/mcp", "/mcp/"):
            if not self._authorized(scope):
                await self._unauthorized(scope, receive, send)
                return
            # The inner Starlette app resolves its "/" route against
            # path[len(root_path):] — normalize so both /mcp and /mcp/ hit it.
            child = dict(scope)
            child["root_path"] = root + "/mcp"
            child["path"] = root + "/mcp/"
            await self.mcp_app(child, receive, send)
            return

        if rel == "/mcp/skill" and scope.get("method") in ("GET", "HEAD"):
            await self._serve_skill(scope, receive, send)
            return

        await self.app(scope, receive, send)

    @staticmethod
    async def _unauthorized(scope, receive, send):
        body = json.dumps({
            "jsonrpc": "2.0", "id": None,
            "error": {"code": -32001,
                      "message": "Unauthorized: pass an AgentFlow API key as "
                                 "'Authorization: Bearer af_…' or 'X-API-Key'."},
        }).encode()
        await send({
            "type": "http.response.start", "status": 401,
            "headers": [(b"content-type", b"application/json"),
                        (b"www-authenticate", b"Bearer")],
        })
        await send({"type": "http.response.body", "body": body})

    @staticmethod
    async def _serve_skill(scope, receive, send):
        try:
            body = SKILL_MD.read_bytes()
            status = 200
        except OSError:
            body, status = b"skill file missing", 404
        await send({
            "type": "http.response.start", "status": status,
            "headers": [(b"content-type", b"text/markdown; charset=utf-8")],
        })
        await send({"type": "http.response.body", "body": body})

    @staticmethod
    def _authorized(scope) -> bool:
        from app.models import AdminUser, ApiKey
        from app.security import hash_api_key, looks_like_api_key, verify_session_token

        headers = {k.decode("latin-1").lower(): v.decode("latin-1")
                   for k, v in scope.get("headers", [])}
        candidate = (headers.get("x-api-key") or "").strip()
        bearer = ""
        auth = headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            bearer = auth[7:].strip()
        if not candidate and looks_like_api_key(bearer):
            candidate = bearer

        db = SessionLocal()
        try:
            if candidate:
                rec = (
                    db.query(ApiKey)
                    .filter_by(key_hash=hash_api_key(candidate), revoked=False)
                    .first()
                )
                if rec:
                    rec.last_used_at = datetime.utcnow()
                    db.commit()
                    return True
            if bearer and not looks_like_api_key(bearer):
                payload = verify_session_token(bearer)
                sub = payload.get("sub") if payload else None
                if sub and db.query(AdminUser).filter_by(username=sub).first():
                    return True
            return False
        finally:
            db.close()
