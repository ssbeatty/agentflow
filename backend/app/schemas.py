from pydantic import BaseModel
from typing import Any, Optional
from datetime import datetime


# ── ScriptFile ──────────────────────────────────────────────────────────────

class ScriptFileUpsert(BaseModel):
    filename: str
    content: str = ""
    is_main: bool = False


class ScriptFileOut(BaseModel):
    id: str
    script_id: str
    filename: str
    content: str
    is_main: bool
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Script ───────────────────────────────────────────────────────────────────

class ScriptCreate(BaseModel):
    name: str
    description: str = ""
    entry_function: str = "run"
    requirements: str = ""
    mcp_server_ids: list[str] = []


class ScriptUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    entry_function: Optional[str] = None
    requirements: Optional[str] = None
    mcp_server_ids: Optional[list[str]] = None


class ScriptSummary(BaseModel):
    id: str
    name: str
    description: str
    entry_function: str
    mcp_server_ids: list[str] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ScriptDetail(ScriptSummary):
    requirements: str
    files: list[ScriptFileOut] = []


# ── Execution ─────────────────────────────────────────────────────────────────

class ExecutionCreate(BaseModel):
    script_id: str
    input_data: dict = {}


class ExecutionLogOut(BaseModel):
    id: str
    timestamp: datetime
    level: str
    message: str
    data: Optional[Any] = None
    step: Optional[str] = None

    model_config = {"from_attributes": True}


class ExecutionSummary(BaseModel):
    id: str
    script_id: str
    status: str
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ExecutionDetail(ExecutionSummary):
    input_data: dict
    output_data: Optional[Any] = None
    error: Optional[str] = None
    logs: list[ExecutionLogOut] = []


# ── LLMConfig ─────────────────────────────────────────────────────────────────

class LLMConfigCreate(BaseModel):
    name: str
    provider: str
    model: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    is_default: bool = False
    extra_config: dict = {}


class LLMConfigUpdate(BaseModel):
    name: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    is_default: Optional[bool] = None
    extra_config: Optional[dict] = None


class LLMConfigOut(BaseModel):
    id: str
    name: str
    provider: str
    model: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    is_default: bool
    extra_config: dict
    created_at: datetime

    model_config = {"from_attributes": True}


# ── MCPServerConfig ───────────────────────────────────────────────────────────

class MCPServerCreate(BaseModel):
    name: str
    transport: str = "http"
    url: Optional[str] = None
    command: Optional[str] = None
    args: Optional[list[str]] = None
    env_vars: Optional[dict] = None
    headers: Optional[dict] = None
    enabled: bool = True


class MCPServerUpdate(BaseModel):
    name: Optional[str] = None
    transport: Optional[str] = None
    url: Optional[str] = None
    command: Optional[str] = None
    args: Optional[list[str]] = None
    env_vars: Optional[dict] = None
    headers: Optional[dict] = None
    enabled: Optional[bool] = None


class MCPServerOut(BaseModel):
    id: str
    name: str
    transport: str
    url: Optional[str] = None
    command: Optional[str] = None
    args: Optional[list[str]] = None
    env_vars: Optional[dict] = None
    headers: Optional[dict] = None
    enabled: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── CronJob ───────────────────────────────────────────────────────────────────

class CronJobCreate(BaseModel):
    script_id: str
    label: str = ""
    cron_expression: str
    input_data: dict = {}
    enabled: bool = True


class CronJobUpdate(BaseModel):
    label: Optional[str] = None
    cron_expression: Optional[str] = None
    input_data: Optional[dict] = None
    enabled: Optional[bool] = None


class CronJobOut(BaseModel):
    id: str
    script_id: str
    label: str
    cron_expression: str
    input_data: dict
    enabled: bool
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}
