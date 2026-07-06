import type {
  Script, ScriptSummary, ScriptFile,
  Execution, ExecutionSummary, UsageStats,
  EvalCase, EvalRun, Assertion,
  LLMConfig,
  CronJob,
  Channel,
  MCPServerConfig, MCPProbeResult,
  Conversation, ConversationSummary, ConversationMessage,
  ScriptRevision, ScriptRevisionDetail,
  ScriptInputPreset,
  UploadedFile,
  AuthStatus, AuthResult, ApiKey, ApiKeyCreated,
  Secret,
  SearchConfig,
  Skill, SkillSummary, SkillFile,
  MarketplaceSkill, RegistrySkill,
} from "./types";

import { translateApiError } from "./i18n/errorMessages";

const BASE = "/api";

/** On a 401 (session expired / not logged in), bounce to the login page —
 *  except for the auth endpoints themselves, whose 401s are handled inline. */
function handleUnauthorized(path: string) {
  if (typeof window === "undefined") return;
  if (path.startsWith("/auth/")) return;
  // trailingSlash:true → pathname is "/login/"; normalize before comparing.
  const p = window.location.pathname.replace(/\/$/, "");
  if (p !== "/login" && p !== "/setup") {
    window.location.href = "/login";
  }
}

/** Extract a readable message from a failed response: FastAPI's error body is
 *  `{"detail": "..."}` JSON — parse it out instead of throwing the raw JSON
 *  text — then translate known stable backend error strings for display. */
async function extractErrorMessage(res: Response): Promise<string> {
  const raw = await res.text().catch(() => "");
  let message = raw || res.statusText || `HTTP ${res.status}`;
  if (raw) {
    try {
      const body = JSON.parse(raw);
      if (typeof body?.detail === "string") message = body.detail;
      else if (body?.detail != null) message = JSON.stringify(body.detail);
    } catch {
      // not JSON — use the raw text as-is
    }
  }
  return translateApiError(message);
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin", // send the admin session cookie
    ...init,
  });
  if (!res.ok) {
    if (res.status === 401) handleUnauthorized(path);
    throw new Error(await extractErrorMessage(res));
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

  update: (id: string, data: Partial<Pick<Script, "name" | "description" | "entry_function" | "requirements" | "mcp_server_ids" | "skill_ids" | "max_executions" | "input_schema" | "warm" | "keep_warm">>) =>
    req<Script>(`/scripts/${id}`, { method: "PATCH", body: JSON.stringify(data) }),

  delete: (id: string) => req<void>(`/scripts/${id}`, { method: "DELETE" }),

  /** Re-derive the input schema from the script's code (INPUT_SCHEMA). */
  syncSchema: (id: string) =>
    req<Script>(`/scripts/${id}/schema/sync`, { method: "POST" }),

  /** Eagerly spawn + preheat the warm worker (no-op unless warm workers on). */
  preheat: (id: string) =>
    req<{ enabled: boolean; ready: boolean; reused: boolean }>(`/scripts/${id}/preheat`, { method: "POST" }),

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

  usageStats: (days = 7) => req<UsageStats>(`/executions/usage-stats?days=${days}`),

  get: (id: string) => req<Execution>(`/executions/${id}`),

  create: (scriptId: string, inputData: Record<string, unknown> = {}) =>
    req<ExecutionSummary>("/executions", {
      method: "POST",
      body: JSON.stringify({ script_id: scriptId, input_data: inputData }),
    }),

  stop: (id: string) => req<{ stopped: boolean; status: string }>(`/executions/${id}/stop`, { method: "POST" }),

  delete: (id: string) => req<void>(`/executions/${id}`, { method: "DELETE" }),

  clear: (scriptId: string) =>
    req<{ deleted: number }>(`/executions?script_id=${encodeURIComponent(scriptId)}`, { method: "DELETE" }),
};

// ── Evals (test cases + regression runs) ─────────────────────────────────────

export const evals = {
  listCases: (scriptId: string) =>
    req<EvalCase[]>(`/evals/cases?script_id=${encodeURIComponent(scriptId)}`),

  createCase: (body: { script_id: string; name: string; input_json: string; assertions: Assertion[] }) =>
    req<EvalCase>("/evals/cases", { method: "POST", body: JSON.stringify(body) }),

  updateCase: (id: string, body: Partial<{ name: string; input_json: string; assertions: Assertion[] }>) =>
    req<EvalCase>(`/evals/cases/${id}`, { method: "PATCH", body: JSON.stringify(body) }),

  deleteCase: (id: string) => req<void>(`/evals/cases/${id}`, { method: "DELETE" }),

  listRuns: (scriptId: string) =>
    req<EvalRun[]>(`/evals/runs?script_id=${encodeURIComponent(scriptId)}`),

  getRun: (id: string) => req<EvalRun>(`/evals/runs/${id}`),

  startRun: (body: { script_id: string; revision_number?: number | null }) =>
    req<EvalRun>("/evals/runs", { method: "POST", body: JSON.stringify(body) }),

  deleteRun: (id: string) => req<void>(`/evals/runs/${id}`, { method: "DELETE" }),
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

// ── Channels (NewAPI-style provider endpoints serving multiple models) ─────────

type ChannelWritable = {
  name: string;
  provider: string;
  api_key?: string;
  base_url?: string;
  models?: string[];
  priority?: number;
  enabled?: boolean;
  extra_config?: Record<string, unknown>;
};

export const channels = {
  list: () => req<Channel[]>("/channels"),

  create: (data: ChannelWritable) =>
    req<Channel>("/channels", { method: "POST", body: JSON.stringify(data) }),

  update: (id: string, data: Partial<ChannelWritable>) =>
    req<Channel>(`/channels/${id}`, { method: "PATCH", body: JSON.stringify(data) }),

  delete: (id: string) => req<void>(`/channels/${id}`, { method: "DELETE" }),

  /** Mark one of the channel's models as the global default for get_llm(). */
  setDefault: (id: string, model?: string) =>
    req<Channel>(`/channels/${id}/set-default`, { method: "POST", body: JSON.stringify({ model }) }),

  /** Fetch available model ids from the provider's API. */
  listModels: (data: { provider: string; api_key?: string; base_url?: string }) =>
    req<{ models: string[]; error: string | null }>(
      "/channels/list-models", { method: "POST", body: JSON.stringify(data) },
    ),
};

// ── MCP Servers ────────────────────────────────────────────────────────────────

type MCPServerWritable =
  Partial<Omit<MCPServerConfig, "id" | "created_at" | "updated_at" | "oauth_connected" | "oauth_scope">>
  & { oauth_config?: Record<string, unknown> };

export const mcpServers = {
  list: () => req<MCPServerConfig[]>("/mcp-servers"),

  create: (data: MCPServerWritable) =>
    req<MCPServerConfig>("/mcp-servers", { method: "POST", body: JSON.stringify(data) }),

  update: (id: string, data: MCPServerWritable) =>
    req<MCPServerConfig>(`/mcp-servers/${id}`, { method: "PATCH", body: JSON.stringify(data) }),

  delete: (id: string) => req<void>(`/mcp-servers/${id}`, { method: "DELETE" }),

  /** Connect to the server and list its tools (used by the "Test" button). */
  probe: (id: string) =>
    req<MCPProbeResult>(`/mcp-servers/${id}/probe`, { method: "POST" }),

  /** Get the provider authorization URL to open in a browser popup. */
  oauthAuthorizeUrl: (id: string) =>
    req<{ authorize_url: string }>(`/mcp-servers/${id}/oauth/authorize-url`),

  /** Clear the stored OAuth token. */
  oauthDisconnect: (id: string) =>
    req<MCPServerConfig>(`/mcp-servers/${id}/oauth/disconnect`, { method: "POST" }),
};

// ── Skills (Agent Skills: SKILL.md + supporting files) ──────────────────────────

export const skills = {
  list: () => req<SkillSummary[]>("/skills"),

  get: (id: string) => req<Skill>(`/skills/${id}`),

  create: (data: { name: string; description?: string; enabled?: boolean }) =>
    req<Skill>("/skills", { method: "POST", body: JSON.stringify(data) }),

  update: (id: string, data: Partial<Pick<Skill, "name" | "description" | "enabled">>) =>
    req<Skill>(`/skills/${id}`, { method: "PATCH", body: JSON.stringify(data) }),

  delete: (id: string) => req<void>(`/skills/${id}`, { method: "DELETE" }),

  upsertFile: (id: string, file: { filename: string; content: string; is_main?: boolean }) =>
    req<SkillFile>(`/skills/${id}/files`, { method: "PUT", body: JSON.stringify(file) }),

  deleteFile: (id: string, filename: string) =>
    req<void>(`/skills/${id}/files/${encodeURIComponent(filename)}`, { method: "DELETE" }),

  createDir: (id: string, path: string) =>
    req<{ ok: boolean; path: string }>(`/skills/${id}/dirs`, {
      method: "POST", body: JSON.stringify({ path }),
    }),

  deleteDir: (id: string, path: string) => {
    // Strip leading/trailing slashes so the URL never degenerates to `/dirs/`
    // (a trailing slash triggers a 307 redirect that turns into 405 on the POST
    // route) or `/dirs` (empty path). Refuse an empty path outright.
    const clean = (path || "").replace(/^\/+|\/+$/g, "");
    if (!clean) return Promise.reject(new Error("folder path is required"));
    return req<void>(`/skills/${id}/dirs/${clean.split("/").map(encodeURIComponent).join("/")}`, {
      method: "DELETE",
    });
  },
};

// ── Skill marketplace (browse official repo + community registry, install) ──────

export const marketplace = {
  sources: () =>
    req<{
      official: { owner: string; repo: string; has_token: boolean };
      registries: { provider: string; has_key: boolean }[];
    }>("/marketplace/sources"),

  official: (refresh = false) =>
    req<{ skills: MarketplaceSkill[]; has_token: boolean }>(
      `/marketplace/official${refresh ? "?refresh=true" : ""}`,
    ),

  // provider: "skillsmp" (anon-friendly) | "skillssh" (needs SKILLS_SH_TOKEN)
  search: (q: string, provider = "skillsmp", page = 1, sort = "stars") =>
    req<{
      provider?: string;
      skills: RegistrySkill[];
      pagination: { page?: number; total?: number; totalPages?: number };
      rate_remaining: number | null;
      has_key: boolean;
      auth_required?: boolean;
    }>(`/marketplace/registry/search?q=${encodeURIComponent(q)}&provider=${provider}&page=${page}&sort=${sort}`),

  install: (body: {
    owner?: string; repo?: string; ref?: string | null;
    subpath?: string; githubUrl?: string; refresh?: boolean;
  }) =>
    req<{
      installed?: boolean;
      already_installed?: boolean;
      skill?: SkillSummary;
      needs_choice?: boolean;
      owner?: string;
      repo?: string;
      ref?: string | null;
      skills?: MarketplaceSkill[];
    }>("/marketplace/install", { method: "POST", body: JSON.stringify(body) }),
};

// ── Conversations ──────────────────────────────────────────────────────────────

export const conversations = {
  list: (scriptId?: string) =>
    req<ConversationSummary[]>(`/conversations${scriptId ? `?script_id=${scriptId}` : ""}`),

  create: (data: { script_id: string; title?: string; context_turns?: number; reasoning_effort?: string }) =>
    req<Conversation>("/conversations", { method: "POST", body: JSON.stringify(data) }),

  get: (id: string) => req<Conversation>(`/conversations/${id}`),

  update: (id: string, data: { title?: string; context_turns?: number; reasoning_effort?: string }) =>
    req<ConversationSummary>(`/conversations/${id}`, { method: "PATCH", body: JSON.stringify(data) }),

  delete: (id: string) => req<void>(`/conversations/${id}`, { method: "DELETE" }),

  chatStart: (id: string, message: string) =>
    req<{ execution_id: string; user_msg_id: string }>(`/conversations/${id}/chat`, {
      method: "POST",
      body: JSON.stringify({ message }),
    }),

  confirm: (id: string, execution_id: string, reasoning?: string) =>
    req<ConversationMessage>(`/conversations/${id}/confirm`, {
      method: "POST",
      body: JSON.stringify({ execution_id, reasoning }),
    }),

  deleteMessage: (convId: string, msgId: string) =>
    req<void>(`/conversations/${convId}/messages/${msgId}`, { method: "DELETE" }),
};

// ── Uploaded Files ────────────────────────────────────────────────────────────

export const files = {
  list: (scriptId?: string) =>
    req<UploadedFile[]>(`/files${scriptId ? `?script_id=${scriptId}` : ""}`),

  upload: async (file: File, scriptId?: string): Promise<UploadedFile> => {
    const fd = new FormData();
    fd.append("file", file);
    if (scriptId) fd.append("script_id", scriptId);
    const res = await fetch(`${BASE}/files/upload`, { method: "POST", body: fd });
    if (!res.ok) {
      throw new Error(await extractErrorMessage(res));
    }
    return res.json();
  },

  delete: (id: string) => req<void>(`/files/${id}`, { method: "DELETE" }),

  downloadUrl: (id: string) => `${BASE}/files/${id}`,
};

// ── Auth ───────────────────────────────────────────────────────────────────────

export const auth = {
  /** Public — used by the auth gate to decide setup vs login vs through. */
  status: () => req<AuthStatus>("/auth/status"),

  /** First-run only: create the admin account. */
  setup: (username: string, password: string) =>
    req<AuthResult>("/auth/setup", { method: "POST", body: JSON.stringify({ username, password }) }),

  login: (username: string, password: string) =>
    req<AuthResult>("/auth/login", { method: "POST", body: JSON.stringify({ username, password }) }),

  logout: () => req<{ ok: boolean }>("/auth/logout", { method: "POST" }),

  changePassword: (old_password: string, new_password: string) =>
    req<{ ok: boolean }>("/auth/change-password", {
      method: "POST", body: JSON.stringify({ old_password, new_password }),
    }),

  me: () => req<{ username: string }>("/auth/me"),
};

// ── API Keys ───────────────────────────────────────────────────────────────────

export const apiKeys = {
  list: () => req<ApiKey[]>("/api-keys"),

  /** Returns the full plaintext key once — store it immediately. */
  create: (name: string) =>
    req<ApiKeyCreated>("/api-keys", { method: "POST", body: JSON.stringify({ name }) }),

  delete: (id: string) => req<void>(`/api-keys/${id}`, { method: "DELETE" }),
};

// ── Secrets (externally-managed credentials read by get_secret() in scripts) ───

export const secrets = {
  list: () => req<Secret[]>("/secrets"),

  create: (data: { key: string; value: string; description?: string }) =>
    req<Secret>("/secrets", { method: "POST", body: JSON.stringify(data) }),

  update: (id: string, data: { value?: string; description?: string }) =>
    req<Secret>(`/secrets/${id}`, { method: "PATCH", body: JSON.stringify(data) }),

  delete: (id: string) => req<void>(`/secrets/${id}`, { method: "DELETE" }),
};

// ── Web search provider config (built-in web_search / web_fetch tools) ─────────

export const searchConfig = {
  get: () => req<SearchConfig>("/search-config"),

  update: (data: { provider?: string; tavily_api_key?: string }) =>
    req<SearchConfig>("/search-config", { method: "PUT", body: JSON.stringify(data) }),

  test: (data: { tavily_api_key?: string }) =>
    req<{ ok: boolean; error?: string; results?: number }>(
      "/search-config/test", { method: "POST", body: JSON.stringify(data) },
    ),
};

// ── AI Assistant (in-editor script-writing agent) ──────────────────────────────

export const assistant = {
  /** The built-in assistant script id + whether its venv is ready. Seeds on demand. */
  info: () => req<{ script_id: string; venv_ready: boolean }>("/assistant/info"),
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
