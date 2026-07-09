export interface ScriptFile {
  id: string;
  script_id: string;
  filename: string;
  content: string;
  is_main: boolean;
  updated_at: string;
}

// A JSON Schema object describing a script's run() input (source: the script's
// own INPUT_SCHEMA). Loosely typed — we only read a small subset in the UI.
export interface JsonSchema {
  type?: string;
  title?: string;
  description?: string;
  properties?: Record<string, JsonSchema>;
  required?: string[];
  items?: JsonSchema;
  enum?: unknown[];
  default?: unknown;
  format?: string;
  minimum?: number;
  maximum?: number;
  [key: string]: unknown;
}

// "script" = a runnable entry point; "module" = an importable library other
// scripts bind via module_ids (no run()/venv, hidden from the run dashboard).
export type ScriptKind = "script" | "module";

export interface Script {
  id: string;
  name: string;
  description: string;
  entry_function: string;
  requirements: string;
  mcp_server_ids: string[];
  skill_ids: string[];
  module_ids: string[];
  kind: ScriptKind;
  module_package?: string | null;   // importable package name (modules only)
  max_executions: number;
  input_schema?: JsonSchema | null;
  warm: boolean;
  keep_warm: boolean;
  created_at: string;
  updated_at: string;
  files: ScriptFile[];
}

export interface ScriptSummary {
  id: string;
  name: string;
  description: string;
  entry_function: string;
  mcp_server_ids: string[];
  skill_ids: string[];
  module_ids: string[];
  kind: ScriptKind;
  module_package?: string | null;
  max_executions: number;
  input_schema?: JsonSchema | null;
  warm: boolean;
  keep_warm: boolean;
  created_at: string;
  updated_at: string;
}

export interface ExecutionLog {
  id: string;
  timestamp: string;
  // "_trace" / "_graph" / "_artifact" are internal levels used to persist
  // panel-specific events alongside logs so historical runs can replay them.
  // LogPanel filters them out.
  level: "info" | "warning" | "error" | "node" | "debug" | "raw" | "_trace" | "_graph" | "_artifact";
  message: string;
  data?: unknown;
  step?: string;
}

export interface Execution {
  id: string;
  script_id: string;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  input_data: Record<string, unknown>;
  output_data?: unknown;
  error?: string;
  started_at?: string;
  finished_at?: string;
  created_at: string;
  logs: ExecutionLog[];
}

export interface ExecutionSummary {
  id: string;
  script_id: string;
  status: Execution["status"];
  started_at?: string;
  finished_at?: string;
  created_at: string;
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  llm_calls?: number;
}

// Aggregated LLM token usage over a window (GET /executions/usage-stats).
export interface UsageStats {
  days: number;
  total_tokens: number;
  prompt_tokens: number;
  completion_tokens: number;
  llm_calls: number;
  runs: number;
  status_counts: Record<string, number>;
  daily: { date: string; total_tokens: number; runs: number }[];
  by_script: { script_id: string; name: string; total_tokens: number; runs: number }[];
}

// ── Eval (test cases + regression runs) ─────────────────────────────────────

export type AssertionType = "contains" | "not_contains" | "regex" | "equals" | "judge";

export interface Assertion {
  type: AssertionType;
  value: string;
  threshold?: number | null;
}

export interface EvalCase {
  id: string;
  script_id: string;
  name: string;
  input_json: string;
  assertions: Assertion[];
  created_at: string;
  updated_at: string;
}

export interface GradedAssertion extends Assertion {
  passed: boolean;
  detail?: string;
  score?: number;
}

export interface EvalCaseResult {
  case_id: string;
  name: string;
  passed: boolean;
  output?: unknown;
  error?: string | null;
  execution_id?: string | null;
  assertions: GradedAssertion[];
}

export interface EvalRun {
  id: string;
  script_id: string;
  status: "running" | "completed" | "failed";
  revision_number?: number | null;
  judge_model?: string | null;
  total: number;
  passed: number;
  error?: string | null;
  created_at: string;
  finished_at?: string | null;
  results_json?: EvalCaseResult[];
}

export interface LLMConfig {
  id: string;
  name: string;
  provider: string;
  model: string;
  has_api_key: boolean;
  base_url?: string;
  is_default: boolean;
  extra_config: Record<string, unknown>;
  created_at: string;
}

export interface CronJob {
  id: string;
  script_id: string;
  label: string;
  cron_expression: string;
  input_data: Record<string, unknown>;
  enabled: boolean;
  last_run_at?: string;
  next_run_at?: string;
  created_at: string;
}

export interface MCPServerConfig {
  id: string;
  name: string;
  transport: "http" | "sse" | "stdio" | "websocket";
  url?: string;
  command?: string;
  args?: string[];
  env_vars?: Record<string, string>;
  headers?: Record<string, string>;
  enabled: boolean;
  auth_type?: "none" | "oauth2";
  /** read-only: whether a live OAuth token is stored (server-side) */
  oauth_connected?: boolean;
  /** read-only: configured OAuth scope, if any */
  oauth_scope?: string | null;
  created_at: string;
  updated_at: string;
}

export interface Channel {
  id: string;
  name: string;
  provider: string;
  base_url?: string;
  models: string[];
  priority: number;
  enabled: boolean;
  is_default: boolean;
  default_model?: string | null;
  has_api_key: boolean;
  created_at: string;
}

export interface Secret {
  id: string;
  key: string;
  description: string;
  /** read-only: whether a value is stored (the value itself is never returned) */
  has_value: boolean;
  /** read-only: masked hint, e.g. "••••ab" */
  preview: string;
  created_at: string;
  updated_at: string;
}

/** Config for the built-in web_search / web_fetch tools. */
export interface SearchConfig {
  provider: "tavily" | "duckduckgo";
  /** read-only: whether a Tavily key is stored (the key itself is never returned) */
  tavily_connected: boolean;
  /** read-only: masked hint, e.g. "••••ab" */
  tavily_key_preview: string;
  updated_at: string | null;
}

// ── Notification channels (run-failure alerts) ────────────────────────────────

export type NotificationChannelType = "pushplus" | "bark" | "email";

export interface NotificationChannel {
  id: string;
  name: string;
  type: NotificationChannelType;
  enabled: boolean;
  created_at: string;
  /** config with secret sub-keys stripped (safe to display/edit) */
  config_safe: Record<string, unknown>;
  /** read-only: whether a provider secret (token / device_key / password) is set */
  has_secret: boolean;
}

// ── Skill (Agent Skills: SKILL.md + supporting files) ─────────────────────────

export interface SkillFile {
  id: string;
  skill_id: string;
  filename: string;
  content: string;
  is_main: boolean;
  updated_at: string;
}

export interface SkillSummary {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  source: string;
  created_at: string;
  updated_at: string;
}

export interface Skill extends SkillSummary {
  files: SkillFile[];
  /** all sub-directories (incl. empty ones), so the file tree can show them */
  dirs?: string[];
}

// ── Skill marketplace ─────────────────────────────────────────────────────────

/** A skill offered by the official GitHub repo (browse → install). */
export interface MarketplaceSkill {
  name: string;
  description: string;
  path: string;      // subpath within the repo to install
  files: number;
  owner?: string;
  repo?: string;
  upstream?: string;
  installed?: boolean;
}

/** A skill returned by the SkillsMP community registry search. */
export interface RegistrySkill {
  id: string | number;
  name: string;
  author: string;
  description: string;
  githubUrl: string;
  skillUrl: string;
  stars: number;
  updatedAt: string;
}

export interface MCPToolInfo {
  name: string;
  title?: string | null;
  description: string;
  input_schema: Record<string, unknown>;
}

export interface MCPProbeResult {
  ok: boolean;
  tools: MCPToolInfo[];
  error: string | null;
  needs_auth?: boolean;
}

// ── UploadedFile ──────────────────────────────────────────────────────────────

export interface UploadedFile {
  id: string;
  original_name: string;
  mime: string | null;
  size: number;
  script_id: string | null;
  created_at: string | null;
}

// ── ScriptInputPreset ────────────────────────────────────────────────────────

export interface ScriptInputPreset {
  id: string;
  script_id: string;
  name: string;
  input_json: string;
  created_at: string;
  updated_at: string;
}

// ── ScriptRevision ────────────────────────────────────────────────────────────

export interface RevisionFile {
  filename: string;
  content: string;
  is_main: boolean;
}

export interface ScriptRevision {
  id: string;
  script_id: string;
  revision_number: number;
  label: string;
  name: string;
  entry_function: string;
  created_at: string;
}

export interface ScriptRevisionDetail extends ScriptRevision {
  requirements: string;
  files: RevisionFile[];
}

// ── Execution trace (LangGraph nodes / tool calls / agent actions) ──────────

export interface TraceEvent {
  type: "trace";
  kind: "node" | "tool" | "skill" | "agent_action" | "agent_finish" | "llm";
  phase: "start" | "end" | "error" | "event";
  name: string;
  run_id: string;
  parent_run_id: string | null;
  step?: number;
  langgraph_step?: number;
  duration_ms?: number | null;
  ts: number;
  timestamp?: string;
  input?: unknown;
  output?: unknown;
  error?: string;
  log?: unknown;
  model?: string;
  temperature?: number;
}

export interface GraphTopology {
  type: "graph";
  graph_id: string;
  mermaid: string;
  nodes: string[];
}

// ── Artifacts (rich rendering in the Artifacts tab) ─────────────────────────
export type ArtifactEvent =
  | { type: "artifact"; kind: "markdown"; content: string; title?: string | null; timestamp?: string }
  | { type: "artifact"; kind: "image"; url: string; alt?: string; mime?: string | null; title?: string | null; timestamp?: string }
  | { type: "artifact"; kind: "table"; columns: string[]; rows: unknown[][]; title?: string | null; timestamp?: string }
  | { type: "artifact"; kind: "html"; html: string; title?: string | null; timestamp?: string }
  | { type: "artifact"; kind: "mermaid"; code: string; title?: string | null; timestamp?: string };

// WebSocket events
export type WsEvent =
  | { type: "log"; level: string; message: string; data?: unknown; step?: string; timestamp: string }
  | { type: "status"; status: Execution["status"]; output?: unknown; error?: string }
  | { type: "token"; content: string }
  | TraceEvent
  | GraphTopology
  | ArtifactEvent
  | { type: "ping" };

// ── Conversation ──────────────────────────────────────────────────────────────

export interface ConversationMessage {
  id: string;
  conversation_id: string;
  role: "user" | "assistant";
  content: string;
  reasoning?: string;   // <think> chain-of-thought; never sent as model history
  error?: string;
  execution_id?: string;
  created_at: string;
}

export interface ConversationSummary {
  id: string;
  script_id: string;
  title: string;
  context_turns: number;
  reasoning_effort: string;   // off | low | medium | high
  created_at: string;
  updated_at: string;
}

export interface Conversation extends ConversationSummary {
  messages: ConversationMessage[];
}

// ── Auth ──────────────────────────────────────────────────────────────────────

export interface AuthStatus {
  /** has an admin account been created yet? */
  initialized: boolean;
  /** is the current caller logged in? */
  authenticated: boolean;
  username: string | null;
}

export interface AuthResult {
  username: string;
  token: string;
}

export interface ApiKey {
  id: string;
  name: string;
  prefix: string;
  last_used_at?: string | null;
  revoked: boolean;
  created_at: string;
}

/** Returned only at creation time — the full key is shown exactly once. */
export interface ApiKeyCreated extends ApiKey {
  key: string;
}
