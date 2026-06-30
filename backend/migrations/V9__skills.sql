CREATE TABLE IF NOT EXISTS skills (
    id          TEXT PRIMARY KEY,
    name        VARCHAR(255) NOT NULL UNIQUE,
    description TEXT DEFAULT '',
    enabled     INTEGER NOT NULL DEFAULT 1,
    source      VARCHAR(50) DEFAULT 'manual',
    created_at  DATETIME,
    updated_at  DATETIME
);
CREATE TABLE IF NOT EXISTS skill_files (
    id         TEXT PRIMARY KEY,
    skill_id   TEXT NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    filename   VARCHAR(255) NOT NULL,
    content    TEXT DEFAULT '',
    is_main    INTEGER NOT NULL DEFAULT 0,
    created_at DATETIME,
    updated_at DATETIME
);
CREATE INDEX IF NOT EXISTS idx_skill_files_skill ON skill_files(skill_id);
ALTER TABLE scripts ADD COLUMN skill_ids TEXT;
