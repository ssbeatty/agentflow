-- V1: Execution queue, concurrency control, and retry support
--
-- Adds three columns to executions:
--   queued_at    — timestamp when the execution entered the queue (waiting for a slot)
--   retry_count  — how many automatic retries have been attempted (0 = first run)
--   max_retries  — maximum automatic retries allowed (0 = no retry)
--
-- Status flow extended: pending → queued → running → completed/failed/cancelled
--
-- Runtime behaviour controlled by env vars:
--   AGENTFLOW_MAX_CONCURRENT  (default 5)  — max parallel script subprocesses
--   AGENTFLOW_EXECUTION_TIMEOUT (default 600) — per-execution timeout in seconds

ALTER TABLE executions ADD COLUMN queued_at   DATETIME;
ALTER TABLE executions ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE executions ADD COLUMN max_retries INTEGER NOT NULL DEFAULT 0;
