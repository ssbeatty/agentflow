from sqlalchemy import Column, String, Text, DateTime, Boolean, ForeignKey, JSON, Integer
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid

from .database import Base


def _id() -> str:
    return str(uuid.uuid4())


class Script(Base):
    __tablename__ = "scripts"

    id = Column(String, primary_key=True, default=_id)
    name = Column(String(255), nullable=False)
    description = Column(Text, default="")
    entry_function = Column(String(255), default="run")
    requirements = Column(Text, default="")
    mcp_server_ids = Column(JSON, default=list)
    skill_ids = Column(JSON, default=list)
    # Reusable code modules this script imports (opt-in, like skill_ids). Holds
    # the row ids of kind="module" Scripts. At run time the engine materializes
    # each bound module's files into `script_dir/modules/<package>/` and puts
    # `script_dir/modules` on sys.path, so the script can `from <package> import …`.
    # A module has NO venv of its own; its `requirements` are merged into THIS
    # script's venv install. See Alembic 0012 + services/module_support.py.
    module_ids = Column(JSON, default=list)
    # Script kind: "script" (a runnable entry point — the default) or "module"
    # (an importable library other scripts bind via module_ids; no run()/venv,
    # hidden from the run dashboard). server_default so existing rows read
    # "script" and Alembic autogenerate sees no drift. See Alembic 0012.
    kind = Column(String(16), default="script", server_default="script", nullable=False)
    # For kind="module" only: the importable package name a referencing script
    # uses (`from <module_package> import …`). A valid Python identifier, unique
    # among modules. Null for kind="script". See services/module_support.py.
    module_package = Column(String(255), nullable=True)
    # Optional JSON Schema describing this script's run() input. The *source of
    # truth* is the script itself (a module-level `INPUT_SCHEMA` dict, or a
    # Pydantic model's `.model_json_schema()`); this column is a CACHE, refreshed
    # by services/script_schema.py on save / manual sync / MCP introspect. When
    # present it drives (a) pre-run input validation, (b) typed /docs examples,
    # (c) auto-rendered input forms in the run/chat pages. Null = untyped dict
    # (the legacy behaviour — anything goes). See Alembic 0008.
    input_schema = Column(JSON, nullable=True)
    # Warm-worker (serverless-style) execution. Only consulted when the global
    # AGENTFLOW_WARM_WORKERS flag is on (default off — the platform otherwise
    # spawns a fresh subprocess per run, the classic isolation). `warm` (default
    # True) lets a script reuse a long-lived per-script worker between runs
    # (skips the langchain cold-import on run #2+); set False for scripts that
    # need strict fresh-process isolation. `keep_warm` (default False) eagerly
    # preheats the worker (imports the heavy stack) so even run #1 is warm — the
    # "provisioned concurrency" opt-in. See Alembic 0009 + services/worker_pool.py.
    warm = Column(Boolean, default=True, server_default="1", nullable=False)
    keep_warm = Column(Boolean, default=False, server_default="0", nullable=False)
    # Max execution records to keep for this script; older ones are auto-pruned
    # (oldest terminal runs first) after each run. 0 = keep unlimited.
    # server_default mirrors the Python default so Alembic autogenerate sees no
    # drift and existing rows get 50 when the column is first added.
    max_executions = Column(Integer, default=50, server_default="50")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    files = relationship("ScriptFile", back_populates="script", cascade="all, delete-orphan")
    executions = relationship("Execution", back_populates="script", cascade="all, delete-orphan")
    cron_jobs = relationship("CronJob", back_populates="script", cascade="all, delete-orphan")
    revisions = relationship(
        "ScriptRevision", back_populates="script", cascade="all, delete-orphan",
        order_by="ScriptRevision.revision_number.desc()",
    )
    input_presets = relationship(
        "ScriptInputPreset", back_populates="script", cascade="all, delete-orphan",
        order_by="ScriptInputPreset.created_at",
    )
    eval_cases = relationship(
        "EvalCase", back_populates="script", cascade="all, delete-orphan",
        order_by="EvalCase.created_at",
    )
    eval_runs = relationship(
        "EvalRun", back_populates="script", cascade="all, delete-orphan",
        order_by="EvalRun.created_at.desc()",
    )


class ScriptFile(Base):
    __tablename__ = "script_files"

    id = Column(String, primary_key=True, default=_id)
    script_id = Column(String, ForeignKey("scripts.id", ondelete="CASCADE"), nullable=False)
    filename = Column(String(255), nullable=False)
    content = Column(Text, default="")
    is_main = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    script = relationship("Script", back_populates="files")


class ScriptRevision(Base):
    __tablename__ = "script_revisions"

    id = Column(String, primary_key=True, default=_id)
    script_id = Column(String, ForeignKey("scripts.id", ondelete="CASCADE"), nullable=False)
    revision_number = Column(Integer, nullable=False)
    label = Column(Text, default="")
    name = Column(String(255), nullable=False)
    entry_function = Column(String(255), default="run")
    requirements = Column(Text, default="")
    files_snapshot = Column(Text, default="[]")  # JSON: [{filename, content, is_main}]
    created_at = Column(DateTime, default=datetime.utcnow)

    script = relationship("Script", back_populates="revisions")


class ScriptInputPreset(Base):
    __tablename__ = "script_input_presets"

    id = Column(String, primary_key=True, default=_id)
    script_id = Column(String, ForeignKey("scripts.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    input_json = Column(Text, default="{}")  # raw JSON text (preserves formatting)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    script = relationship("Script", back_populates="input_presets")


class Execution(Base):
    __tablename__ = "executions"

    id = Column(String, primary_key=True, default=_id)
    script_id = Column(String, ForeignKey("scripts.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(50), default="pending")  # pending/queued/running/completed/failed/cancelled
    input_data = Column(JSON, default=dict)
    output_data = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    queued_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=0)
    # How this run was triggered — drives failure-notification filtering (eval
    # sub-runs are excluded so a graded test case can't spam the alert channels).
    trigger = Column(String(32), default="manual", server_default="manual")  # manual|api|cron|rerun|eval
    # Optional webhook: when set, the engine POSTs the run's final result here
    # once it reaches a terminal state (completed/failed/cancelled, after any
    # retries). Lets an external caller submit async (POST /run?wait=false) and
    # be pushed the result instead of polling. Best-effort (see services/
    # callbacks.py) — a dead webhook never affects the run. See Alembic 0011.
    callback_url = Column(Text, nullable=True)
    # Token usage aggregated across every LLM call in this run. Captured by the
    # tracer (agentflow/_tracer.py), emitted once as a `{"type":"usage"}` event
    # by the runner, and persisted at finalization. 0 = no usage recorded (a
    # plain non-LLM script, a provider that didn't report usage, or a crash
    # before any LLM call). `llm_calls` = number of model round-trips.
    # server_default mirrors the Python default so existing rows populate on ADD
    # and Alembic autogenerate sees no drift (see revision 0006).
    prompt_tokens = Column(Integer, default=0, server_default="0")
    completion_tokens = Column(Integer, default=0, server_default="0")
    total_tokens = Column(Integer, default=0, server_default="0")
    llm_calls = Column(Integer, default=0, server_default="0")

    script = relationship("Script", back_populates="executions")
    logs = relationship("ExecutionLog", back_populates="execution", cascade="all, delete-orphan",
                        order_by="ExecutionLog.timestamp")


class ExecutionLog(Base):
    __tablename__ = "execution_logs"

    id = Column(String, primary_key=True, default=_id)
    execution_id = Column(String, ForeignKey("executions.id", ondelete="CASCADE"), nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    level = Column(String(50), default="info")  # info/warning/error/node/debug/raw
    message = Column(Text, nullable=False)
    data = Column(JSON, nullable=True)
    step = Column(String(255), nullable=True)

    execution = relationship("Execution", back_populates="logs")


class LLMConfig(Base):
    __tablename__ = "llm_configs"

    id = Column(String, primary_key=True, default=_id)
    name = Column(String(255), nullable=False)
    provider = Column(String(100), nullable=False)  # openai/anthropic/ollama/custom
    model = Column(String(255), nullable=False)
    api_key = Column(String(500), nullable=True)
    base_url = Column(String(500), nullable=True)
    is_default = Column(Boolean, default=False)
    extra_config = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)


class Channel(Base):
    """An LLM provider endpoint (NewAPI-style "channel"): credentials configured
    once, serving a set of models. `get_llm("<model>")` resolves a model name to
    the highest-`priority` enabled channel that serves it (ties → earliest)."""
    __tablename__ = "channels"

    id = Column(String, primary_key=True, default=_id)
    name = Column(String(255), nullable=False)
    provider = Column(String(50), nullable=False, default="openai")
    api_key = Column(Text, nullable=True)
    base_url = Column(String(500), nullable=True)
    models = Column(JSON, nullable=True)          # list[str] of model ids served
    priority = Column(Integer, nullable=False, default=0)   # higher wins
    enabled = Column(Boolean, nullable=False, default=True)
    is_default = Column(Boolean, nullable=False, default=False)  # holds the default model
    default_model = Column(String(255), nullable=True)
    extra_config = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class MCPServerConfig(Base):
    __tablename__ = "mcp_server_configs"

    id = Column(String, primary_key=True, default=_id)
    name = Column(String(255), nullable=False, unique=True)
    transport = Column(String(50), nullable=False, default="http")  # http/sse/stdio/websocket
    url = Column(String(500), nullable=True)
    command = Column(String(500), nullable=True)
    args = Column(JSON, nullable=True)       # list[str] for stdio
    env_vars = Column(JSON, nullable=True)   # dict for stdio extra env
    headers = Column(JSON, nullable=True)    # dict for http/sse auth headers
    enabled = Column(Boolean, default=True)
    # OAuth 2.0 (http/sse): auth_type none|oauth2.
    # oauth_config holds discovered + manual endpoints and client creds
    #   {authorization_endpoint, token_endpoint, registration_endpoint,
    #    client_id, client_secret, scope, resource}
    # oauth_token holds the live grant (never exposed to the frontend)
    #   {access_token, refresh_token, token_type, scope, expires_at}
    auth_type = Column(String(20), nullable=False, default="none")
    oauth_config = Column(JSON, nullable=True)
    oauth_token = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Skill(Base):
    """A reusable Agent Skill — a folder with a SKILL.md (instructions) plus any
    supporting files. Global like MCP servers; a script opts in via
    `script.skill_ids`. At run time the engine materializes each bound skill to
    `run_dir/skills/<name>/`, injects each skill's name+description into the agent
    system prompt, and the agent loads a skill's full SKILL.md on demand via the
    built-in `read_skill` tool (Agent Skills "progressive disclosure")."""
    __tablename__ = "skills"

    id = Column(String, primary_key=True, default=_id)
    name = Column(String(255), nullable=False, unique=True)
    description = Column(Text, default="")
    enabled = Column(Boolean, default=True)
    source = Column(String(50), default="manual")   # manual | installed:<repo> (future)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    files = relationship("SkillFile", back_populates="skill", cascade="all, delete-orphan")


class SkillFile(Base):
    """A file inside a Skill. Mirrors ScriptFile — content lives in the DB and is
    written to disk at run time. `is_main` marks the skill's SKILL.md entry."""
    __tablename__ = "skill_files"

    id = Column(String, primary_key=True, default=_id)
    skill_id = Column(String, ForeignKey("skills.id", ondelete="CASCADE"), nullable=False)
    filename = Column(String(255), nullable=False)
    content = Column(Text, default="")
    is_main = Column(Boolean, default=False)   # True for SKILL.md
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    skill = relationship("Skill", back_populates="files")


class Secret(Base):
    """An externally-managed credential (API key / token / webhook url, etc).

    Stored once via the Secrets UI/API; scripts read the value at runtime with
    `agentflow.get_secret("<key>")`. The value is injected into the user-script
    subprocess as `AGENTFLOW_SECRET_<NORM(key)>` and is **never serialized to the
    frontend** (see `SecretOut`) — same contract as channel api_keys / OAuth
    tokens. Single-admin model → secrets are global (every script can read them)."""
    __tablename__ = "secrets"

    id = Column(String, primary_key=True, default=_id)
    key = Column(String(255), nullable=False, unique=True)   # e.g. BARK_KEY
    value = Column(Text, nullable=False, default="")          # plaintext at rest (like channels.api_key)
    description = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class NotificationChannel(Base):
    """A destination that gets pinged when a run fails (PushPlus / Bark / email).

    `type` selects the provider; `config` (JSON) holds provider-specific settings
    INCLUDING secrets (pushplus token / bark device_key / smtp password). Those
    secret sub-keys are **never serialized to the frontend** — `NotificationChannelOut`
    strips them and exposes only a `has_secret` flag + the non-secret fields, same
    contract as channels.api_key / secrets / OAuth tokens. Global (single-admin)."""
    __tablename__ = "notification_channels"

    id = Column(String, primary_key=True, default=_id)
    name = Column(String(255), nullable=False)
    type = Column(String(32), nullable=False)          # pushplus | bark | email
    enabled = Column(Boolean, default=True)
    config = Column(JSON, default=dict)                 # provider-specific (contains secrets)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SearchConfig(Base):
    """Singleton config for the built-in `web_search` / `web_fetch` tools.

    Picks the preferred web-search provider and holds its credentials. Only one
    row ever exists (id == "default"). DuckDuckGo (via `ddgs`, no key) is always
    the fallback, so an unconfigured deployment still searches.

    The `tavily_api_key` follows the same "never serialized to the frontend"
    contract as channel api_keys / secrets (see `SearchConfigOut`). At run time
    the engine folds this into `AGENTFLOW_SEARCH_CONFIG` (subprocess env only —
    never baked into the on-disk runner) which `agentflow._make_builtin_tools()`
    reads. Global by design (single-admin model)."""
    __tablename__ = "search_config"

    # Singleton: always the "default" row (String pk matches the id convention).
    id = Column(String, primary_key=True, default="default")
    # Preferred provider: "tavily" | "duckduckgo". DuckDuckGo is always fallback.
    provider = Column(String(32), nullable=False, default="tavily", server_default="tavily")
    tavily_api_key = Column(Text, nullable=True)  # plaintext at rest (like channels.api_key)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(String, primary_key=True, default=_id)
    script_id = Column(String, ForeignKey("scripts.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(500), default="New conversation")
    context_turns = Column(Integer, default=10)
    # Per-conversation reasoning/think level: off | low | medium | high. Threaded
    # into each run's input as input["reasoning"] and mapped to the model's
    # provider-specific thinking knob by agentflow.get_llm(reasoning=...).
    reasoning_effort = Column(String(16), default="off", server_default="off")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    messages = relationship(
        "ConversationMessage",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ConversationMessage.created_at",
    )


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id = Column(String, primary_key=True, default=_id)
    conversation_id = Column(String, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(20), nullable=False)        # "user" | "assistant"
    content = Column(Text, nullable=False, default="")
    # Chain-of-thought for the assistant turn, kept SEPARATE from `content` so it
    # survives reload (rendered as the <think> block) without ever entering the
    # model history (chat_start builds history from `content` only). Null = none.
    reasoning = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    execution_id = Column(String, nullable=True)     # plain string ref to executions.id
    created_at = Column(DateTime, default=datetime.utcnow)

    conversation = relationship("Conversation", back_populates="messages")


class UploadedFile(Base):
    __tablename__ = "uploaded_files"

    id = Column(String, primary_key=True, default=_id)
    original_name = Column(String(500), nullable=False)
    mime = Column(String(255), nullable=True)
    size = Column(Integer, nullable=False, default=0)
    script_id = Column(String, ForeignKey("scripts.id", ondelete="SET NULL"), nullable=True)
    storage_path = Column(Text, nullable=False)  # absolute path to blob on disk
    created_at = Column(DateTime, default=datetime.utcnow)


class AdminUser(Base):
    """The platform operator account. A single row in normal use; auth is a
    gate for the whole management UI/API, not multi-tenant user management."""
    __tablename__ = "admin_users"

    id = Column(String, primary_key=True, default=_id)
    username = Column(String(255), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)  # pbkdf2_sha256$...
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ApiKey(Base):
    """An issued API key for external callers of the run endpoint. Only the
    SHA-256 hash is stored — the plaintext key is shown exactly once at creation."""
    __tablename__ = "api_keys"

    id = Column(String, primary_key=True, default=_id)
    name = Column(String(255), nullable=False, default="API Key")
    prefix = Column(String(16), nullable=False)        # first chars, for display
    key_hash = Column(String(128), nullable=False, index=True)
    last_used_at = Column(DateTime, nullable=True)
    revoked = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class EvalCase(Base):
    """One test case in a script's eval dataset: an input + a set of assertions
    the script's output must satisfy. This is what turns "did my prompt change
    make things better or worse?" from vibes into a pass/fail number.

    `assertions` is a JSON list of `{type, value, threshold?}`:
      - contains / not_contains : substring (in / not in the stringified output)
      - regex                   : output matches the pattern
      - equals                  : stringified output equals value exactly
      - judge                   : an LLM grades the output against `value`
                                  (0–10), passes if score >= `threshold` (def 7)
    Reuses raw JSON text for `input_json` like ScriptInputPreset (preserves
    formatting; the engine parses it into the run input)."""
    __tablename__ = "eval_cases"

    id = Column(String, primary_key=True, default=_id)
    script_id = Column(String, ForeignKey("scripts.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False, default="case")
    input_json = Column(Text, default="{}")
    assertions = Column(JSON, default=list)   # list[{type, value, threshold?}]
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    script = relationship("Script", back_populates="eval_cases")


class EvalRun(Base):
    """One batch execution of a script's whole eval dataset at a point in time.

    Each case is run through the real execution engine (so it exercises the same
    venv / LLM / tracer path a normal run does — and its token usage is tracked),
    then its assertions are graded. `results_json` holds the per-case detail;
    `passed`/`total` the headline. `revision_number` records which script version
    it ran against, so a run can be compared to the previous one and pinned to a
    ScriptRevision (the "improve prompt → eval → don't regress → promote" loop)."""
    __tablename__ = "eval_runs"

    id = Column(String, primary_key=True, default=_id)
    script_id = Column(String, ForeignKey("scripts.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(20), default="running")   # running | completed | failed
    revision_number = Column(Integer, nullable=True)
    judge_model = Column(String(255), nullable=True)
    total = Column(Integer, default=0)
    passed = Column(Integer, default=0)
    results_json = Column(JSON, default=list)   # list[{case_id,name,passed,output,error,execution_id,assertions:[...]}]
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)

    script = relationship("Script", back_populates="eval_runs")


class CronJob(Base):
    __tablename__ = "cron_jobs"

    id = Column(String, primary_key=True, default=_id)
    script_id = Column(String, ForeignKey("scripts.id", ondelete="CASCADE"), nullable=False)
    label = Column(String(255), default="")
    cron_expression = Column(String(255), nullable=False)
    input_data = Column(JSON, default=dict)
    enabled = Column(Boolean, default=True)
    last_run_at = Column(DateTime, nullable=True)
    next_run_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    script = relationship("Script", back_populates="cron_jobs")
