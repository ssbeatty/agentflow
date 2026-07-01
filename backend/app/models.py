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
