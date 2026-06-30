CREATE TABLE IF NOT EXISTS secrets (
    id          TEXT PRIMARY KEY,
    key         VARCHAR(255) NOT NULL UNIQUE,
    value       TEXT NOT NULL DEFAULT '',
    description TEXT DEFAULT '',
    created_at  DATETIME,
    updated_at  DATETIME
)
