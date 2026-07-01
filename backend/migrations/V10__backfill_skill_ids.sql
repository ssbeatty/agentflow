-- V10: backfill JSON-array columns that "ALTER TABLE ... ADD COLUMN" left NULL
-- on pre-existing rows. V9 added scripts.skill_ids without a default, so rows
-- created before V9 hold NULL. The ORM maps these as JSON and the API schema
-- types them as `list[str]` (non-optional), so NULL breaks ScriptSummary /
-- ScriptDetail serialization with a 500. New rows are fine (model default=list).
UPDATE scripts SET skill_ids = '[]' WHERE skill_ids IS NULL;
UPDATE scripts SET mcp_server_ids = '[]' WHERE mcp_server_ids IS NULL;
