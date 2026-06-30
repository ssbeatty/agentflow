CREATE TABLE IF NOT EXISTS channels (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    provider      TEXT NOT NULL DEFAULT 'openai',
    api_key       TEXT,
    base_url      TEXT,
    models        TEXT,
    priority      INTEGER NOT NULL DEFAULT 0,
    enabled       INTEGER NOT NULL DEFAULT 1,
    is_default    INTEGER NOT NULL DEFAULT 0,
    default_model TEXT,
    extra_config  TEXT,
    created_at    DATETIME,
    updated_at    DATETIME
);
CREATE INDEX IF NOT EXISTS idx_channels_priority ON channels(priority);
