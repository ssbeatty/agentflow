CREATE TABLE IF NOT EXISTS admin_users (
    id            TEXT PRIMARY KEY,
    username      VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    created_at    DATETIME,
    updated_at    DATETIME
);

CREATE TABLE IF NOT EXISTS api_keys (
    id           TEXT PRIMARY KEY,
    name         VARCHAR(255) NOT NULL DEFAULT 'API Key',
    prefix       VARCHAR(16) NOT NULL,
    key_hash     VARCHAR(128) NOT NULL,
    last_used_at DATETIME,
    revoked      INTEGER NOT NULL DEFAULT 0,
    created_at   DATETIME
);

CREATE INDEX IF NOT EXISTS ix_api_keys_key_hash ON api_keys (key_hash)
