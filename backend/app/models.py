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
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    files = relationship("ScriptFile", back_populates="script", cascade="all, delete-orphan")
    executions = relationship("Execution", back_populates="script", cascade="all, delete-orphan")
    cron_jobs = relationship("CronJob", back_populates="script", cascade="all, delete-orphan")


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


class Execution(Base):
    __tablename__ = "executions"

    id = Column(String, primary_key=True, default=_id)
    script_id = Column(String, ForeignKey("scripts.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(50), default="pending")  # pending/running/completed/failed/cancelled
    input_data = Column(JSON, default=dict)
    output_data = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

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
    created_at = Column(DateTime, default=datetime.utcnow)
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
