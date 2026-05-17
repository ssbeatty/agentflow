-- V0: Baseline schema (all tables as initially created by create_all)
-- This reflects the schema before any manual migrations were introduced.
-- Do NOT apply this to an existing database — it is create-if-not-exists safe.

CREATE TABLE IF NOT EXISTS scripts (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    description  TEXT NOT NULL DEFAULT '',
    entry_function TEXT NOT NULL DEFAULT 'run',
    requirements TEXT NOT NULL DEFAULT '',
    mcp_server_ids TEXT,           -- JSON array of MCPServerConfig ids
    created_at   DATETIME,
    updated_at   DATETIME
);

CREATE TABLE IF NOT EXISTS script_files (
    id        TEXT PRIMARY KEY,
    script_id TEXT NOT NULL REFERENCES scripts(id) ON DELETE CASCADE,
    filename  TEXT NOT NULL,
    content   TEXT NOT NULL DEFAULT '',
    is_main   INTEGER NOT NULL DEFAULT 0,   -- BOOLEAN stored as 0/1
    created_at DATETIME,
    updated_at DATETIME
);

CREATE TABLE IF NOT EXISTS executions (
    id          TEXT PRIMARY KEY,
    script_id   TEXT NOT NULL REFERENCES scripts(id) ON DELETE CASCADE,
    status      TEXT NOT NULL DEFAULT 'pending',   -- pending/running/completed/failed/cancelled
    input_data  TEXT,           -- JSON
    output_data TEXT,           -- JSON, nullable
    error       TEXT,           -- nullable
    started_at  DATETIME,       -- nullable
    finished_at DATETIME,       -- nullable
    created_at  DATETIME
);

CREATE TABLE IF NOT EXISTS execution_logs (
    id           TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL REFERENCES executions(id) ON DELETE CASCADE,
    timestamp    DATETIME,
    level        TEXT NOT NULL DEFAULT 'info',    -- info/warning/error/node/debug/raw
    message      TEXT NOT NULL,
    data         TEXT,          -- JSON, nullable
    step         TEXT           -- nullable
);

CREATE TABLE IF NOT EXISTS llm_configs (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    provider     TEXT NOT NULL,  -- openai/anthropic/ollama/custom
    model        TEXT NOT NULL,
    api_key      TEXT,
    base_url     TEXT,
    is_default   INTEGER NOT NULL DEFAULT 0,
    extra_config TEXT,           -- JSON
    created_at   DATETIME
);

CREATE TABLE IF NOT EXISTS mcp_server_configs (
    id        TEXT PRIMARY KEY,
    name      TEXT NOT NULL UNIQUE,
    transport TEXT NOT NULL DEFAULT 'http',  -- http/sse/stdio/websocket
    url       TEXT,
    command   TEXT,
    args      TEXT,             -- JSON list[str]
    env_vars  TEXT,             -- JSON dict
    headers   TEXT,             -- JSON dict
    enabled   INTEGER NOT NULL DEFAULT 1,
    created_at DATETIME,
    updated_at DATETIME
);

CREATE TABLE IF NOT EXISTS conversations (
    id            TEXT PRIMARY KEY,
    script_id     TEXT NOT NULL REFERENCES scripts(id) ON DELETE CASCADE,
    title         TEXT NOT NULL DEFAULT 'New conversation',
    context_turns INTEGER NOT NULL DEFAULT 10,
    created_at    DATETIME,
    updated_at    DATETIME
);

CREATE TABLE IF NOT EXISTS conversation_messages (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL,          -- 'user' | 'assistant'
    content         TEXT NOT NULL DEFAULT '',
    error           TEXT,                   -- nullable
    execution_id    TEXT,                   -- plain ref to executions.id, nullable
    created_at      DATETIME
);

CREATE TABLE IF NOT EXISTS cron_jobs (
    id              TEXT PRIMARY KEY,
    script_id       TEXT NOT NULL REFERENCES scripts(id) ON DELETE CASCADE,
    label           TEXT NOT NULL DEFAULT '',
    cron_expression TEXT NOT NULL,
    input_data      TEXT,           -- JSON
    enabled         INTEGER NOT NULL DEFAULT 1,
    last_run_at     DATETIME,
    next_run_at     DATETIME,
    created_at      DATETIME
);
