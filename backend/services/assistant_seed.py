"""Seed + maintain the in-browser **AI 助手** — a built-in agent that writes,
runs and debugs AgentFlow scripts *and* edits Skills, from inside the editor UI
(the "Claude Code effect").

Architecture ("回环 MCP 内建脚本"): the assistant is itself a normal AgentFlow
chat script that runs through the ordinary execution subprocess + tracer + WS
pipeline (so its tool calls, streaming answer and reasoning render for free via
the existing timeline). Its coding tools come from AgentFlow's OWN outward
`/mcp` gateway, bound to the script as a loopback MCP server. The subprocess
can't touch the DB directly, so it reaches the gateway tools over HTTP to
`self_base_url/mcp`, authenticated with a dedicated internal API key.

This module is the single owner of all three seeded pieces (idempotent, run on
startup + defensively on `/api/assistant/info`):
  1. an internal `af_…` API key (plaintext in `data/.assistant_key`, hash in an
     ApiKey row) — the ONLY credential the loopback connection needs;
  2. a loopback `MCPServerConfig` (`auth_type="internal"`, url `…/mcp`) whose
     bearer is injected at run time by `mcp_config.build_connection` (never
     stored in the DB `headers`, so it can't leak via `MCPServerOut`);
  3. the assistant Script + its `main.py`, bound to that server.

The internal MCP server is filtered out of `GET /api/mcp-servers`, and the
assistant script out of `GET /api/scripts`, so neither clutters the UI nor can
be misused.
"""
from __future__ import annotations

from app.config import BACKEND_ROOT, settings
from app.models import ApiKey, MCPServerConfig, Script, ScriptFile
from app import security

# Stable identities (name is the idempotency key for the MCP server + script).
ASSISTANT_MCP_NAME = "AgentFlow 内建工具"
ASSISTANT_SCRIPT_NAME = "AI 脚本助手"
INTERNAL_AUTH_TYPE = "internal"        # marker: build_connection injects the key
_KEY_FILE = BACKEND_ROOT / "data" / ".assistant_key"


# ── Internal API key ───────────────────────────────────────────────────────────

def _read_key_file() -> str | None:
    try:
        val = _KEY_FILE.read_text(encoding="utf-8").strip()
        return val or None
    except OSError:
        return None


def get_internal_key(db) -> str:
    """Return the plaintext internal API key, creating it (file + ApiKey row) if
    missing. Idempotent + self-healing: if the DB was reset but the key file
    survived (or vice-versa) the missing half is rebuilt so the loopback keeps
    authenticating."""
    full = _read_key_file()
    if not full:
        full, prefix, key_hash = security.generate_api_key()
        _KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        _KEY_FILE.write_text(full, encoding="utf-8")
    else:
        prefix, key_hash = full[:11], security.hash_api_key(full)

    row = db.query(ApiKey).filter_by(key_hash=key_hash).first()
    if not row:
        db.add(ApiKey(name="__internal_assistant__", prefix=prefix, key_hash=key_hash, revoked=False))
        db.commit()
    elif row.revoked:
        row.revoked = False
        db.commit()
    return full


# ── Loopback MCP + assistant script ────────────────────────────────────────────

def _self_mcp_url() -> str:
    base = (settings.self_base_url or "http://127.0.0.1:8000").rstrip("/")
    return f"{base}/mcp"


def is_internal_server(srv) -> bool:
    return getattr(srv, "auth_type", "none") == INTERNAL_AUTH_TYPE


def seed_assistant(db) -> str:
    """Ensure the internal key, loopback MCP server and assistant script all
    exist and are in sync. Returns the assistant script id. Idempotent."""
    get_internal_key(db)

    url = _self_mcp_url()
    srv = db.query(MCPServerConfig).filter_by(name=ASSISTANT_MCP_NAME).first()
    if not srv:
        srv = MCPServerConfig(
            name=ASSISTANT_MCP_NAME, transport="http", url=url,
            auth_type=INTERNAL_AUTH_TYPE, enabled=True, headers=None,
        )
        db.add(srv)
        db.commit()
        db.refresh(srv)
    elif srv.url != url or srv.auth_type != INTERNAL_AUTH_TYPE or not srv.enabled:
        srv.url = url
        srv.auth_type = INTERNAL_AUTH_TYPE
        srv.enabled = True
        db.commit()

    script = db.query(Script).filter_by(name=ASSISTANT_SCRIPT_NAME).first()
    if not script:
        script = Script(
            name=ASSISTANT_SCRIPT_NAME,
            description="内建 AI 脚本 / Skill 开发助手(系统脚本,请勿删除)",
            entry_function="run",
            requirements="",
            mcp_server_ids=[srv.id],
            skill_ids=[],
            max_executions=20,
        )
        db.add(script)
        db.commit()
        db.refresh(script)
        db.add(ScriptFile(script_id=script.id, filename="main.py", content=ASSISTANT_MAIN_PY, is_main=True))
        db.commit()
    else:
        changed = False
        bound = list(script.mcp_server_ids or [])
        if srv.id not in bound:
            script.mcp_server_ids = bound + [srv.id]
            changed = True
        mainf = db.query(ScriptFile).filter_by(script_id=script.id, filename="main.py").first()
        if mainf is None:
            db.add(ScriptFile(script_id=script.id, filename="main.py", content=ASSISTANT_MAIN_PY, is_main=True))
            changed = True
        elif mainf.content != ASSISTANT_MAIN_PY:
            # System script — keep main.py authoritative so SDK/prompt changes
            # ship on upgrade. Users edit their OWN scripts, not this one.
            mainf.content = ASSISTANT_MAIN_PY
            mainf.is_main = True
            changed = True
        if changed:
            db.commit()

    # The assistant runs on the backend python (platform deps in
    # requirements.txt), so it needs NO per-script venv. Remove a stale one a
    # previous build may have created — frees the heavy langchain venv from disk
    # and guarantees execution never accidentally selects it over backend python.
    try:
        from services.venv_manager import delete_venv
        delete_venv(script.id)
    except Exception:
        pass

    return script.id


def get_assistant_script_id(db) -> str:
    """Return the assistant script id, seeding it on demand if absent."""
    script = db.query(Script).filter_by(name=ASSISTANT_SCRIPT_NAME).first()
    return script.id if script else seed_assistant(db)


# ── The assistant script (runs in the user-script venv; SDK-only) ──────────────
# Kept authoritative here and re-synced to the DB on every seed. Uses only the
# baseline venv packages (langchain / langgraph / langchain-mcp-adapters), so a
# plain `setup_script_env` suffices — no extra requirements.
#
# Input contract: {message, history:[{role,content}], model, reasoning, context}
#   context = {kind:"script"|"skill"|"none", script_id|skill_id?, entry_function?,
#              active_file?, active_content?, selection?}
#   kind=="none" → global mode: the assistant was opened from a non-editor page,
#     so no target is bound and creating a NEW script/skill is allowed. When a
#     script_id/skill_id IS bound, the prompt forbids create_* (edit in place).
# Output: {reply}. The answer streams via token(); tool calls + reasoning render
# from the tracer/WS. Lines are joined with chr(10).
ASSISTANT_MAIN_PY = '''"""AI 助手 —— AgentFlow 内建的脚本 / Skill 开发 · 调试代理(系统脚本,请勿手改)。

通过 loopback MCP 获得平台的 write→run→debug 工具(脚本:create_script /
write_script_file / run_script / get_execution_logs …;Skill:get_skill /
write_skill_file / create_skill …),在你当前正在编辑的脚本或 Skill 上帮你写、跑、
调。最终答案 token 流式输出;工具调用由平台 tracer 渲染成时间线卡片。
"""
from agentflow import get_agent, token, log


def _text_of(chunk) -> str:
    c = getattr(chunk, "content", "")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "".join(
            part.get("text", "")
            for part in c
            if isinstance(part, dict) and part.get("type") in (None, "text")
        )
    return ""


def _system_prompt(ctx: dict) -> str:
    kind = ctx.get("kind") or "script"
    active = ctx.get("active_file") or ""
    content = ctx.get("active_content") or ""
    selection = ctx.get("selection") or ""
    common = [
        "You are AgentFlow's built-in AI assistant. You help the user write, run and debug AgentFlow scripts and Skills right in the browser.",
        "Reply in the user's own language (default 简体中文). Explain concisely what you did, why, and the result; do not dump large blocks of code back to the user.",
        "Format final replies as clean Markdown: use bullets or nested bullets for grouped facts; do not put a single word, tool/model name, or inline code on its own line unless it is a real bullet or fenced code block; avoid manual hard line breaks inside one sentence.",
    ]
    if kind == "none":
        # Global mode: opened from a non-editor page, nothing is bound. Creating
        # a NEW script/skill is allowed here (this is the only mode where it is).
        lines = common + [
            "",
            "No script or Skill is currently open — you are in GLOBAL mode.",
            "You may create a new script/Skill (create_script / create_skill), OR edit an existing one the user names (use list_scripts / list_skills to find it, then update it in place). If it is unclear whether they want a brand-new one or a change to an existing one, ask first.",
            "Script tools (MCP): get_platform_context, get_scripting_guide, list_scripts, get_script, create_script, update_script, read_script_file, write_script_file, delete_script_file, setup_script_env, run_script, list_executions, get_execution_logs.",
            "Skill tools (MCP): list_skills, get_skill, read_skill_file, write_skill_file, create_skill, delete_skill_file.",
            "Before writing a script call get_scripting_guide(); after editing a script, run_script once to verify and keep fixing until it passes.",
        ]
    elif kind == "skill":
        sid = ctx.get("skill_id") or ""
        lines = common + [
            "",
            "Current task: edit THE CURRENTLY-OPEN Skill (an Agent Skill = one SKILL.md instruction file + optional supporting files).",
            "Available tools (MCP): list_skills, get_skill, read_skill_file, write_skill_file, create_skill, delete_skill_file.",
            "Rules:",
            "1) Operate on the CURRENT skill (skill_id below). It may be brand-new / EMPTY — requests like 'create a skill', 'build a skill that does X', 'make this skill …' all mean: fill in THIS skill by writing its SKILL.md and supporting files with write_skill_file. SKILL.md is the main file (YAML frontmatter name/description + a markdown body that makes clear WHEN to use it and HOW); supporting files can live in subfolders like references/.",
            "2) Do NOT call create_skill — that creates a SEPARATE new skill and is almost never what the user wants here. Only call create_skill if the user EXPLICITLY asks for an additional / separate new skill.",
            "3) Skills are not executed, so just summarize your changes.",
        ]
        if sid:
            lines += ["", "[Context] You are editing skill_id = " + str(sid) + " (the currently-open skill)."]
    else:
        sid = ctx.get("script_id") or ""
        entry = ctx.get("entry_function") or "run"
        lines = common + [
            "",
            "Current task: write / run / debug THE CURRENTLY-OPEN AgentFlow script.",
            "Available tools (MCP): get_platform_context, get_scripting_guide, list_scripts, get_script, create_script, update_script, read_script_file, write_script_file, delete_script_file, setup_script_env, run_script, list_executions, get_execution_logs.",
            "Rules:",
            "1) Before writing a script the first time, call get_scripting_guide() to learn the conventions (entry def run(input: dict) -> Any; get_llm / get_agent / get_secret; streaming / reasoning). Use get_platform_context() to see available models / secrets / MCP / Skills when needed.",
            "2) Operate on the CURRENT script (script_id below), even if it is empty/new — edit it in place with write_script_file / update_script. Do NOT call create_script; that creates a SEPARATE new script. Only create_script if the user EXPLICITLY asks for a new / separate script. Change dependencies via update_script(requirements=...) then setup_script_env — do NOT write dependencies as a requirements.txt file.",
            "3) After editing, always run_script once to verify, read the error / traceback, and keep fixing until it passes.",
        ]
        if sid:
            lines += ["", "[Context] You are editing script_id = " + str(sid) + " (entry function " + str(entry) + ")."]
    if active:
        lines += ["The currently open file is " + str(active) + "; its latest content:", "```", (content or "")[:8000], "```"]
    if selection:
        lines += ["The user has selected this snippet in the editor (if they say 'edit this / here', they mean it):", "```", str(selection)[:2000], "```"]
    return chr(10).join(lines)


async def run(input: dict) -> dict:
    message = input.get("message", "")
    history = input.get("history", []) or []
    ctx = input.get("context", {}) or {}
    model = input.get("model") or "default"

    try:
        agent = get_agent(
            system_prompt=_system_prompt(ctx),
            llm_name=model,
            reasoning=input.get("reasoning"),
            stream_reasoning=True,
        )
    except Exception as exc:
        return {"reply": "⚠️ Failed to create the assistant (model " + str(model) + "): " + str(exc)}
    if agent is None:
        return {"reply": "⚠️ No default LLM channel configured. Add a channel in Settings and mark it as default, then retry."}

    messages = [
        ("human" if m.get("role") == "user" else "ai", m.get("content", ""))
        for m in history
    ]
    messages.append(("human", message))

    full = ""
    try:
        async for chunk, _meta in agent.astream({"messages": messages}, stream_mode="messages"):
            # Stream only the agent's spoken text (skip tool results); the
            # <think> reasoning block is surfaced by the platform automatically.
            if chunk.__class__.__name__ != "AIMessageChunk":
                continue
            text = _text_of(chunk)
            if text:
                token(text)
                full += text
    except Exception as exc:  # fall back to a single non-streaming turn
        log("assistant astream failed, falling back to invoke: " + str(exc))
        result = agent.invoke({"messages": messages})
        full = _text_of(result["messages"][-1])

    return {"reply": full}
'''
