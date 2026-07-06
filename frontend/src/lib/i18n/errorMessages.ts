import i18n from "./config";

/**
 * Backend HTTPException `detail` strings are stable English identifiers by
 * convention (see CLAUDE.md) — the backend does not localize them. This table
 * maps the known/stable ones to a friendly Chinese translation; anything not
 * listed here (including dynamic/interpolated messages) passes through
 * unchanged in English, which is still a correct, readable fallback.
 */
const ERROR_MESSAGES: Record<string, string> = {
  "Name required": "名称不能为空",
  "File not found": "文件不存在",
  "Folder not found": "文件夹不存在",
  "Skill not found": "技能不存在",
  "secret key already exists": "密钥名称已存在",
  "secret not found": "密钥不存在",
  "Cannot delete main file": "无法删除主文件",
  "Create venv first": "请先创建虚拟环境",
  "Preset with this name already exists": "同名预设已存在",
  "Script not found": "脚本不存在",
  "script not found": "脚本不存在",
  "Revision not found": "版本不存在",
  "Preset not found": "预设不存在",
  "Input JSON must be an object": "输入 JSON 必须是一个对象",
  "empty file": "文件为空",
  "file not found": "文件不存在",
  "blob missing on disk": "文件内容在磁盘上缺失",
  "Admin account already initialized": "管理员账户已初始化",
  "Invalid username or password": "用户名或密码错误",
  "Current password is incorrect": "原密码错误",
  "Cron job not found": "定时任务不存在",
  "LLM config not found": "LLM 配置不存在",
  "API key not found": "API 密钥不存在",
  "Conversation not found": "对话不存在",
  "Message not found": "消息不存在",
  "A reply is already being generated for this conversation": "该对话正在生成回复,请稍候",
  "Execution not found": "执行记录不存在",
  "execution not found": "执行记录不存在",
  "q is required": "缺少参数 q",
  "provide githubUrl or owner+repo": "请提供 githubUrl 或 owner+repo",
  "no SKILL.md found at that location": "该位置未找到 SKILL.md",
  "max_retries must be between 0 and 10": "max_retries 必须在 0 到 10 之间",
  "Stop the run before deleting it": "请先停止运行,再删除",
  "invalid path": "路径无效",
  "artifact not found": "产物不存在",
  "OAuth applies to network transports (http/sse/websocket)": "OAuth 仅适用于网络传输方式 (http/sse/websocket)",
  "server has no URL": "服务器未配置 URL",
  "MCP server not found": "MCP 服务器不存在",
  "channel could not be created": "渠道创建失败",
  "model is not served by this channel": "该渠道未提供此模型",
  "channel not found": "渠道不存在",
  "Not authenticated": "未登录",
  "Invalid or missing API key": "API 密钥无效或缺失",
};

/** Translate a backend error `detail` string for display, given the current UI language. */
export function translateApiError(detail: string): string {
  const zh = ERROR_MESSAGES[detail.trim()];
  if (!zh) return detail;
  return i18n.language?.startsWith("zh") ? zh : detail;
}
