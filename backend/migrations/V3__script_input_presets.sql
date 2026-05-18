CREATE TABLE script_input_presets (
    id          TEXT PRIMARY KEY,
    script_id   TEXT NOT NULL REFERENCES scripts(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    input_json  TEXT NOT NULL DEFAULT '{}',
    created_at  DATETIME,
    updated_at  DATETIME
);

CREATE INDEX idx_script_input_presets_script_id ON script_input_presets(script_id);

CREATE UNIQUE INDEX idx_script_input_presets_name ON script_input_presets(script_id, name);
