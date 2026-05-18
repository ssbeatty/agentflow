CREATE TABLE script_revisions (
    id              TEXT PRIMARY KEY,
    script_id       TEXT NOT NULL REFERENCES scripts(id) ON DELETE CASCADE,
    revision_number INTEGER NOT NULL,
    label           TEXT NOT NULL DEFAULT '',
    name            TEXT NOT NULL,
    entry_function  TEXT NOT NULL DEFAULT 'run',
    requirements    TEXT NOT NULL DEFAULT '',
    files_snapshot  TEXT NOT NULL DEFAULT '[]',
    created_at      DATETIME
);

CREATE INDEX idx_script_revisions_script_id ON script_revisions(script_id);

CREATE UNIQUE INDEX idx_script_revisions_number ON script_revisions(script_id, revision_number);
