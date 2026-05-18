import type {
  Script, ScriptSummary, ScriptFile,
  Execution, ExecutionSummary,
  LLMConfig,
  CronJob,
  MCPServerConfig,
  Conversation, ConversationSummary, ConversationMessage,
  ScriptRevision, ScriptRevisionDetail,
  ScriptInputPreset,
} from "./types";

const BASE = "/api";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText);
    throw new Error(detail || `HTTP ${res.status}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

// ── Scripts ────────────────────────────────────────────────────────────────────

export const scripts = {
  list: () => req<ScriptSummary[]>("/scripts"),

  get: (id: string) => req<Script>(`/scripts/${id}`),

  create: (data: { name: string; description?: string; entry_function?: string }) =>
    req<Script>("/scripts", { method: "POST", body: JSON.stringify(data) }),

  update: (id: string, data: Partial<Pick<Script, "name" | "description" | "entry_function" | "requirements" | "mcp_server_ids">>) =>
    req<Script>(`/scripts/${id}`, { method: "PATCH", body: JSON.stringify(data) }),

  delete: (id: string) => req<void>(`/scripts/${id}`, { method: "DELETE" }),

  upsertFile: (id: string, file: { filename: string; content: string; is_main?: boolean }) =>
    req<ScriptFile>(`/scripts/${id}/files`, { method: "PUT", body: JSON.stringify(file) }),

  deleteFile: (id: string, filename: string) =>
    req<void>(`/scripts/${id}/files/${filename}`, { method: "DELETE" }),

  /** Returns a streaming Response of venv-creation output lines */
  createVenv: (id: string, force = false) =>
    fetch(`${BASE}/scripts/${id}/venv${force ? "?force=true" : ""}`, { method: "POST" }),

  deleteVenv: (id: string) =>
    req<{ removed: boolean }>(`/scripts/${id}/venv`, { method: "DELETE" }),

  venvStatus: (id: string) =>
    req<{ exists: boolean }>(`/scripts/${id}/venv`),

  packages: (id: string) =>
    req<{ packages: { name: string; version: string }[]; error: string | null }>(`/scripts/${id}/packages`),

  lint: (id: string, source: string) =>
    req<{ issues: { line: number; col: number; end_line: number; end_col: number; message: string; severity: "error" | "warning" }[] }>(
      `/scripts/${id}/lint`,
      { method: "POST", body: JSON.stringify({ source, filename: "main.py" }) },
    ),

  install: (id: string) =>
    fetch(`${BASE}/scripts/${id}/install`, { method: "POST" }),
};

// ── Revisions ─────────────────────────────────────────────────────────────────

export const revisions = {
  list: (scriptId: string) =>
    req<ScriptRevision[]>(`/scripts/${scriptId}/revisions`),

  create: (scriptId: string, label = "") =>
    req<ScriptRevision>(`/scripts/${scriptId}/revisions`, {
      method: "POST", body: JSON.stringify({ label }),
    }),

  get: (scriptId: string, revId: string) =>
    req<ScriptRevisionDetail>(`/scripts/${scriptId}/revisions/${revId}`),

  updateLabel: (scriptId: string, revId: string, label: string) =>
    req<ScriptRevision>(`/scripts/${scriptId}/revisions/${revId}`, {
      method: "PATCH", body: JSON.stringify({ label }),
    }),

  delete: (scriptId: string, revId: string) =>
    req<void>(`/scripts/${scriptId}/revisions/${revId}`, { method: "DELETE" }),

  fork: (scriptId: string, revId: string, name: string) =>
    req<Script>(`/scripts/${scriptId}/revisions/${revId}/fork`, {
      method: "POST", body: JSON.stringify({ name }),
    }),
};

// ── Input Presets ─────────────────────────────────────────────────────────────

export const inputPresets = {
  list: (scriptId: string) =>
    req<ScriptInputPreset[]>(`/scripts/${scriptId}/presets`),

  create: (scriptId: string, data: { name: string; input_json: string }) =>
    req<ScriptInputPreset>(`/scripts/${scriptId}/presets`, {
      method: "POST", body: JSON.stringify(data),
    }),

  update: (scriptId: string, presetId: string, data: { name?: string; input_json?: string }) =>
    req<ScriptInputPreset>(`/scripts/${scriptId}/presets/${presetId}`, {
      method: "PATCH", body: JSON.stringify(data),
    }),

  delete: (scriptId: string, presetId: string) =>
    req<void>(`/scripts/${scriptId}/presets/${presetId}`, { method: "DELETE" }),
};

// ── Executions ─────────────────────────────────────────────────────────────────

export const executions = {
  list: (scriptId?: string) =>
    req<ExecutionSummary[]>(`/executions${scriptId ? `?script_id=${scriptId}` : ""}`),

  get: (id: string) => req<Execution>(`/executions/${id}`),

  create: (scriptId: string, inputData: Record<string, unknown> = {}) =>
    req<ExecutionSummary>("/executions", {
      method: "POST",
      body: JSON.stringify({ script_id: scriptId, input_data: inputData }),
    }),

  stop: (id: string) => req<{ stopped: boolean; status: string }>(`/executions/${id}/stop`, { method: "POST" }),
};

// ── LLM Configs ────────────────────────────────────────────────────────────────

export interface LLMConfigInput {
  name: string;
  provider: string;
  model: string;
  api_key?: string;
  base_url?: string;
  is_default: boolean;
  extra_config: Record<string, unknown>;
}

export const llmConfigs = {
  list: () => req<LLMConfig[]>("/llm-configs"),

  create: (data: LLMConfigInput) =>
    req<LLMConfig>("/llm-configs", { method: "POST", body: JSON.stringify(data) }),

  update: (id: string, data: Partial<LLMConfigInput>) =>
    req<LLMConfig>(`/llm-configs/${id}`, { method: "PATCH", body: JSON.stringify(data) }),

  delete: (id: string) => req<void>(`/llm-configs/${id}`, { method: "DELETE" }),

  setDefault: (id: string) => req<LLMConfig>(`/llm-configs/${id}/set-default`, { method: "POST" }),
};

// ── MCP Servers ────────────────────────────────────────────────────────────────

export const mcpServers = {
  list: () => req<MCPServerConfig[]>("/mcp-servers"),

  create: (data: Omit<MCPServerConfig, "id" | "created_at" | "updated_at">) =>
    req<MCPServerConfig>("/mcp-servers", { method: "POST", body: JSON.stringify(data) }),

  update: (id: string, data: Partial<Omit<MCPServerConfig, "id" | "created_at" | "updated_at">>) =>
    req<MCPServerConfig>(`/mcp-servers/${id}`, { method: "PATCH", body: JSON.stringify(data) }),

  delete: (id: string) => req<void>(`/mcp-servers/${id}`, { method: "DELETE" }),
};

// ── Conversations ──────────────────────────────────────────────────────────────

export const conversations = {
  list: (scriptId?: string) =>
    req<ConversationSummary[]>(`/conversations${scriptId ? `?script_id=${scriptId}` : ""}`),

  create: (data: { script_id: string; title?: string; context_turns?: number }) =>
    req<Conversation>("/conversations", { method: "POST", body: JSON.stringify(data) }),

  get: (id: string) => req<Conversation>(`/conversations/${id}`),

  update: (id: string, data: { title?: string; context_turns?: number }) =>
    req<ConversationSummary>(`/conversations/${id}`, { method: "PATCH", body: JSON.stringify(data) }),

  delete: (id: string) => req<void>(`/conversations/${id}`, { method: "DELETE" }),

  chatStart: (id: string, message: string) =>
    req<{ execution_id: string; user_msg_id: string }>(`/conversations/${id}/chat`, {
      method: "POST",
      body: JSON.stringify({ message }),
    }),

  confirm: (id: string, execution_id: string) =>
    req<ConversationMessage>(`/conversations/${id}/confirm`, {
      method: "POST",
      body: JSON.stringify({ execution_id }),
    }),

  deleteMessage: (convId: string, msgId: string) =>
    req<void>(`/conversations/${convId}/messages/${msgId}`, { method: "DELETE" }),
};

// ── Cron Jobs ──────────────────────────────────────────────────────────────────

export const cronJobs = {
  list: (scriptId?: string) =>
    req<CronJob[]>(`/cron-jobs${scriptId ? `?script_id=${scriptId}` : ""}`),

  create: (data: Omit<CronJob, "id" | "created_at" | "last_run_at" | "next_run_at">) =>
    req<CronJob>("/cron-jobs", { method: "POST", body: JSON.stringify(data) }),

  update: (id: string, data: Partial<Pick<CronJob, "label" | "cron_expression" | "input_data" | "enabled">>) =>
    req<CronJob>(`/cron-jobs/${id}`, { method: "PATCH", body: JSON.stringify(data) }),

  delete: (id: string) => req<void>(`/cron-jobs/${id}`, { method: "DELETE" }),
};
