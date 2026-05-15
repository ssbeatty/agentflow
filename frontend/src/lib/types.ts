export interface ScriptFile {
  id: string;
  script_id: string;
  filename: string;
  content: string;
  is_main: boolean;
  updated_at: string;
}

export interface Script {
  id: string;
  name: string;
  description: string;
  entry_function: string;
  requirements: string;
  created_at: string;
  updated_at: string;
  files: ScriptFile[];
}

export interface ScriptSummary {
  id: string;
  name: string;
  description: string;
  entry_function: string;
  created_at: string;
  updated_at: string;
}

export interface ExecutionLog {
  id: string;
  timestamp: string;
  level: "info" | "warning" | "error" | "node" | "debug" | "raw";
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
}

export interface LLMConfig {
  id: string;
  name: string;
  provider: string;
  model: string;
  api_key?: string;
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

// WebSocket events
export type WsEvent =
  | { type: "log"; level: string; message: string; data?: unknown; step?: string; timestamp: string }
  | { type: "status"; status: Execution["status"]; output?: unknown; error?: string }
  | { type: "ping" };
