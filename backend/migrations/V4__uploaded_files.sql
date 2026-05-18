CREATE TABLE uploaded_files (
    id            TEXT PRIMARY KEY,
    original_name TEXT NOT NULL,
    mime          TEXT,
    size          INTEGER NOT NULL DEFAULT 0,
    script_id     TEXT REFERENCES scripts(id) ON DELETE SET NULL,
    storage_path  TEXT NOT NULL,
    created_at    DATETIME
);

CREATE INDEX idx_uploaded_files_script_id ON uploaded_files(script_id);
CREATE INDEX idx_uploaded_files_created_at ON uploaded_files(created_at);
