from pydantic import BaseModel, Field, computed_field, field_validator
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


# ── ScriptRevision ────────────────────────────────────────────────────────────

class RevisionCreate(BaseModel):
    label: str = ""


class RevisionLabelUpdate(BaseModel):
    label: str


class RevisionFileOut(BaseModel):
    filename: str
    content: str
    is_main: bool


class RevisionSummaryOut(BaseModel):
    id: str
    script_id: str
    revision_number: int
    label: str
    name: str
    entry_function: str
    created_at: datetime

    model_config = {"from_attributes": True}


class RevisionDetailOut(RevisionSummaryOut):
    requirements: str
    files: list[RevisionFileOut]


class ForkRevisionRequest(BaseModel):
    name: str


# ── ScriptInputPreset ─────────────────────────────────────────────────────────

class InputPresetCreate(BaseModel):
    name: str
    input_json: str = "{}"


class InputPresetUpdate(BaseModel):
    name: Optional[str] = None
    input_json: Optional[str] = None


class InputPresetOut(BaseModel):
    id: str
    script_id: str
    name: str
    input_json: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Execution ─────────────────────────────────────────────────────────────────

class ExecutionCreate(BaseModel):
    script_id: str
    input_data: dict = {}
    max_retries: int = 0


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
    queued_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_at: datetime
    retry_count: int = 0
    max_retries: int = 0

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


class ModelListRequest(BaseModel):
    provider: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None


class ModelListResponse(BaseModel):
    models: list[str] = []
    error: Optional[str] = None


# ── Channel (NewAPI-style provider endpoint serving multiple models) ───────────

class ChannelCreate(BaseModel):
    name: str
    provider: str = "openai"
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    models: list[str] = []
    priority: int = 0
    enabled: bool = True
    extra_config: dict = {}


class ChannelUpdate(BaseModel):
    name: Optional[str] = None
    provider: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    models: Optional[list[str]] = None
    priority: Optional[int] = None
    enabled: Optional[bool] = None
    extra_config: Optional[dict] = None


class ChannelSetDefault(BaseModel):
    model: Optional[str] = None   # which of the channel's models is the default


class ChannelOut(BaseModel):
    id: str
    name: str
    provider: str
    base_url: Optional[str] = None
    models: list[str] = []
    priority: int
    enabled: bool
    is_default: bool
    default_model: Optional[str] = None
    created_at: datetime

    # read for derivation only — api_key value never serialized
    api_key: Optional[str] = Field(default=None, exclude=True, repr=False)

    model_config = {"from_attributes": True}

    @field_validator("models", mode="before")
    @classmethod
    def _models_to_list(cls, v):
        return v or []

    @computed_field
    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key)


class LLMConfigOut(BaseModel):
    id: str
    name: str
    provider: str
    model: str
    api_key: Optional[str] = Field(default=None, exclude=True, repr=False)
    base_url: Optional[str] = None
    is_default: bool
    extra_config: dict
    created_at: datetime

    model_config = {"from_attributes": True}

    @computed_field
    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key)


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
    auth_type: str = "none"          # none | oauth2
    oauth_config: Optional[dict] = None


class MCPServerUpdate(BaseModel):
    name: Optional[str] = None
    transport: Optional[str] = None
    url: Optional[str] = None
    command: Optional[str] = None
    args: Optional[list[str]] = None
    env_vars: Optional[dict] = None
    headers: Optional[dict] = None
    enabled: Optional[bool] = None
    auth_type: Optional[str] = None
    oauth_config: Optional[dict] = None   # shallow-merged into existing on PATCH


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
    auth_type: str = "none"
    created_at: datetime
    updated_at: datetime

    # Read from the ORM for derivation only — never serialized (secrets stay server-side).
    oauth_token: Optional[dict] = Field(default=None, exclude=True)
    oauth_config: Optional[dict] = Field(default=None, exclude=True)

    @computed_field
    @property
    def oauth_connected(self) -> bool:
        return bool((self.oauth_token or {}).get("access_token"))

    @computed_field
    @property
    def oauth_scope(self) -> Optional[str]:
        return (self.oauth_config or {}).get("scope")

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


# ── Conversation ──────────────────────────────────────────────────────────────

class ConversationMessageOut(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str
    error: Optional[str] = None
    execution_id: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ConversationCreate(BaseModel):
    script_id: str
    title: str = "New conversation"
    context_turns: int = 10


class ConversationUpdate(BaseModel):
    title: Optional[str] = None
    context_turns: Optional[int] = None


class ConversationSummary(BaseModel):
    id: str
    script_id: str
    title: str
    context_turns: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConversationDetail(ConversationSummary):
    messages: list[ConversationMessageOut] = []


class ConverseChatStartRequest(BaseModel):
    message: str


class ConverseConfirmRequest(BaseModel):
    execution_id: str


# ── Auth ──────────────────────────────────────────────────────────────────────

class AdminSetup(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=6, max_length=128)


class AdminLogin(BaseModel):
    username: str
    password: str


class ChangePassword(BaseModel):
    old_password: str
    new_password: str = Field(min_length=6, max_length=128)


class AuthStatus(BaseModel):
    initialized: bool          # has an admin account been created yet?
    authenticated: bool        # is the caller logged in?
    username: Optional[str] = None


class AuthResult(BaseModel):
    username: str
    token: str                 # also set as an httpOnly cookie


# ── API keys ──────────────────────────────────────────────────────────────────

class ApiKeyCreate(BaseModel):
    name: str = Field(default="API Key", max_length=128)


class ApiKeyOut(BaseModel):
    id: str
    name: str
    prefix: str
    last_used_at: Optional[datetime] = None
    revoked: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ApiKeyCreated(ApiKeyOut):
    key: str                   # full plaintext key — returned exactly once
