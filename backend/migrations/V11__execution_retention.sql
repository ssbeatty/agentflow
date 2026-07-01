-- V11: per-script execution-record retention.
-- Adds scripts.max_executions — how many execution rows to keep for a script;
-- the engine auto-prunes older terminal runs beyond this after each run.
-- 0 = keep unlimited. Existing rows default to 50 (backfill NULLs too, since
-- ALTER ... ADD COLUMN leaves pre-existing rows NULL on some engines and the
-- API schema types the field as a non-optional int).
ALTER TABLE scripts ADD COLUMN max_executions INTEGER DEFAULT 50;
UPDATE scripts SET max_executions = 50 WHERE max_executions IS NULL;
