# AgentFlow

一个自托管的 LangGraph / LangChain 脚本运行平台。在浏览器里写 Python agent → 自动创建隔离 venv → 一键运行 / 定时触发 / HTTP 调用 / 内置聊天测试。

> 适合：想给团队/自己搭一个轻量的 AI 脚本中台，不需要 Airflow/Dify 那种重型框架。

---

## 核心功能

- **🐍 Web 代码编辑器** — Monaco + Python 语法高亮 + 实时语法错误检查
- **📦 隔离环境** — 每个脚本自己的 venv，自动预装 `langchain-core / langchain-openai / langgraph`
- **🔌 多 LLM 支持** — OpenAI / Anthropic / Ollama / DeepSeek / 任何 OpenAI 兼容 API；UI 配置，脚本里 `get_llm()` 即用
- **▶️ 运行 & 调试** — 实时 WebSocket 日志流、structured logs、Output 面板、历史回看
- **⏰ 定时触发** — cron 表达式（APScheduler）
- **💬 内置聊天页** — 选脚本直接聊，自动维护对话历史
- **🌐 HTTP API** — 同步 / 异步 / WebSocket 三种调用方式，外部服务直接 invoke
- **🧠 MCP Server** — AI 客户端可直接创建 / 修改 / 运行脚本，并读取规则、日志和调试上下文
- **🗄️ 多数据库** — SQLite（本地）/ Postgres / MySQL，切 `DATABASE_URL` 即可
- **🐳 Docker 化** — 单镜像（前端 baked-in） + docker-compose 一键起

---

## 截图

> 占位 — 主页 / 编辑器 / 聊天页 / API Docs

---

## 快速开始

### 方式 1：Docker（推荐）

```bash
cp .env.example .env          # 改个 POSTGRES_PASSWORD
docker compose up -d --build
```

打开 <http://localhost:8000>

### 方式 2：本地开发

需要：Python 3.12+、Node 20+

```bash
# backend
cd backend
python -m venv .venv
.venv\Scripts\activate           # Windows
# source .venv/bin/activate      # macOS/Linux
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000

# 另开一个终端 — 前端 dev server（热更新）
cd frontend
npm install
npm run dev
# 访问 http://localhost:3000
```

如果只想跑生产模式（前端编译进后端 serve）：
```bash
cd frontend && npm run build      # 产物在 frontend/out
cd ../backend && uvicorn app.main:app --port 8000
# 访问 http://localhost:8000
```

### 方式 3：VS Code 一键调试

按 `F5` 启动 Backend 配置 — 会先执行 `Build Frontend` task 编译前端，再启动 uvicorn + debugpy。

---

## 写一个脚本

UI 上 `New Script` → 编辑器里粘代码：

```python
from agentflow import log, get_llm

def run(input: dict) -> dict:
    msg = input.get("message", "hello")
    log("Got message", data={"msg": msg}, step="recv")

    llm = get_llm()  # 拿 is_default=True 的那条 LLM 配置
    if llm is None:
        return {"reply": "no LLM configured"}

    resp = llm.invoke(f"Repeat back in uppercase: {msg}")
    return {"reply": resp.content}
```

底部 **Dependencies** → `Create venv`（自动预装 baseline）→ `Run`。

### Agentflow SDK

```python
from agentflow import log, get_llm, list_llms

log("message", data={...}, level="info", step="step-name")
# level: info / warning / error / node / debug

llm = get_llm()                  # is_default=True 那条
llm = get_llm("my-config-name")  # 按 name 查找（大小写不敏感）
list_llms()                      # → ["deepseek", "claude", ...]
```

### LangGraph 例子

```python
from typing import TypedDict
from agentflow import log, get_llm
from langgraph.graph import StateGraph, END

class State(TypedDict):
    count: int

def tick(s): return {"count": s["count"] + 1}
def cond(s): return "loop" if s["count"] < 3 else "done"

def build():
    g = StateGraph(State)
    g.add_node("tick", tick)
    g.set_entry_point("tick")
    g.add_conditional_edges("tick", cond, {"loop": "tick", "done": END})
    return g.compile()

def run(input):
    return build().invoke({"count": 0})
```

---

## HTTP API

详细文档在平台内置的 `/docs` 页面。常用：

```bash
# 同步执行（等结果）
curl -X POST 'http://localhost:8000/api/executions/run?timeout=120' \
  -H 'Content-Type: application/json' \
  -d '{"script_id":"<UUID>","input_data":{"message":"hi"}}'

# 异步触发 + 轮询
curl -X POST http://localhost:8000/api/executions \
  -d '{"script_id":"<UUID>","input_data":{}}'
curl http://localhost:8000/api/executions/<EXECUTION_ID>

# 实时日志（WebSocket）
ws://localhost:8000/ws/executions/<EXECUTION_ID>
```

`script_id` 从编辑器顶栏 📋 复制按钮获取。

---

## MCP 给 AI 用

AgentFlow 内置 MCP server，暴露脚本 CRUD、venv / requirements、同步运行、异步运行、停止执行、日志读取、LLM 配置只读列表，以及 `agentflow://rules` / `agentflow://scripts/{id}` / `agentflow://executions/{id}` 等资源。

URL 模式随 FastAPI 启动，这是推荐接法：

```bash
cd backend
uvicorn app.main:app --port 8000
# MCP endpoint: http://localhost:8000/mcp/
```

MCP 客户端配置通常长这样（不同客户端字段名可能略有差异，核心是 `url` 指向 `/mcp/`）：

```json
{
  "mcpServers": {
    "agentflow": {
      "type": "streamable-http",
      "url": "http://localhost:8000/mcp/"
    }
  }
}
```

如果设置了 `MCP_AUTH_TOKEN`：

```json
{
  "mcpServers": {
    "agentflow": {
      "type": "streamable-http",
      "url": "http://localhost:8000/mcp/",
      "headers": {
        "Authorization": "Bearer <MCP_AUTH_TOKEN>"
      }
    }
  }
}
```

安全提示：MCP 工具能写入并执行 Python 脚本，本质上是高权限开发入口。默认开启；如要关闭设 `MCP_ENABLED=false`。如要保护 HTTP `/mcp/`，设 `MCP_AUTH_TOKEN=...`，客户端请求需带 `Authorization: Bearer <token>`。

---

## 配置 LLM

侧栏 **Settings** → 添加 LLM 配置：

| 提供商 | provider | base_url 示例 |
|---|---|---|
| OpenAI | `openai` | 留空 |
| DeepSeek | `openai` | `https://api.deepseek.com/v1` |
| 月之暗面 / Kimi | `openai` | `https://api.moonshot.cn/v1` |
| 智谱 / GLM | `openai` | `https://open.bigmodel.cn/api/paas/v4` |
| Anthropic | `anthropic` | — |
| Ollama | `ollama` | `http://localhost:11434` |

国内大多数 LLM 平台都是 OpenAI 兼容协议，provider 选 `openai` 即可（`anthropic` 和 `ollama` 用独立分支）。

勾选 **is_default** 那条会被 `get_llm()` 默认取到。

---

## 数据库切换

环境变量 `DATABASE_URL` 控制，**无需改代码**：

```bash
# SQLite (默认，零依赖)
DATABASE_URL=sqlite:///./data/opengraph.db

# Postgres
DATABASE_URL=postgresql+psycopg2://user:pass@host:5432/dbname

# MySQL (取消 requirements.txt 里的 pymysql)
DATABASE_URL=mysql+pymysql://user:pass@host/dbname
```

表结构在应用启动时自动 `create_all`。生产想做 schema 迁移再加 Alembic。

---

## 架构

```
┌─────────────────────────────────────────────┐
│  Next.js (static export → served by FastAPI)│
│  ├ /          Dashboard                     │
│  ├ /script    Editor + Logs + Runs          │
│  ├ /chat      Chat with any script          │
│  ├ /docs      API reference                 │
│  └ /settings  LLM configs                   │
└───────────────────┬─────────────────────────┘
                    │ REST + WebSocket
┌───────────────────▼─────────────────────────┐
│  FastAPI (uvicorn)                          │
│  ├ /api/scripts        CRUD + venv/install  │
│  ├ /api/executions     run / stop / list    │
│  ├ /api/llm-configs    LLM CRUD             │
│  ├ /api/cron-jobs      schedule             │
│  ├ /mcp                MCP tools/resources   │
│  └ /ws/executions/*    log streaming        │
└───────┬──────────────────┬──────────────────┘
        │                  │
   ┌────▼─────┐      ┌─────▼──────────────────┐
   │ DB       │      │ subprocess.Popen        │
   │ (SQL*)   │      │ per-script .venv/python │
   └──────────┘      │ + thread queue pump     │
                     └─────────────────────────┘
```

- **每次 run** 在脚本自己的 venv 里 fork 一个 python 子进程（隔离依赖）
- 子进程 stdout/stderr 通过后台线程 → asyncio.Queue → WebSocket 实时推
- 结构化日志走 `__AGENTFLOW__<json>` 前缀协议，自动 persist 到 DB
- 重启 backend 不影响正在跑的脚本（`CREATE_NEW_PROCESS_GROUP` 隔离）

---

## 项目结构

```
.
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app + catch-all serving frontend/out
│   │   ├── config.py            # pydantic-settings
│   │   ├── database.py          # SQLAlchemy engine, multi-DB aware
│   │   ├── mcp_server.py        # MCP tools/resources for AI clients
│   │   ├── models.py            # ORM: Script / Execution / LLMConfig / CronJob
│   │   ├── schemas.py           # Pydantic IO models
│   │   └── routers/             # scripts / executions / llm_configs / cron_jobs / ws
│   ├── services/
│   │   ├── venv_manager.py      # uv/pip venv + install + package list
│   │   ├── execution_engine.py  # subprocess runner + WS broadcast + replay buffer
│   │   └── scheduler.py         # APScheduler cron triggers
│   ├── agentflow/__init__.py    # In-script SDK: log / get_llm / list_llms
│   ├── data/                    # ⚠ runtime: db file + per-script venvs
│   └── requirements.txt
├── frontend/
│   └── src/app/                 # Next.js App Router
│       ├── page.tsx             # dashboard
│       ├── script/page.tsx      # editor
│       ├── chat/page.tsx        # chat
│       ├── docs/page.tsx        # API reference
│       └── settings/page.tsx    # LLM configs
├── .vscode/
│   ├── launch.json              # F5 → Build Frontend → start backend
│   └── tasks.json
├── Dockerfile                   # multi-stage: node build → python runtime
├── docker-compose.yml           # app + postgres
└── .env.example
```

---

## 配置项参考

通过环境变量 / `.env` 文件设置：

| key | 默认 | 说明 |
|---|---|---|
| `DATABASE_URL` | sqlite 本地文件 | SQLAlchemy URL |
| `DATA_DIR` | `./data/scripts` | 每脚本 venv 存放目录 |
| `CORS_ORIGINS` | `http://localhost:3000` | 逗号分隔 |
| `MCP_ENABLED` | `true` | 是否挂载 URL MCP endpoint `/mcp/` |
| `MCP_AUTH_TOKEN` | 空 | 非空时 `/mcp` 要求 Bearer token |
| `APP_ENV` | `development` | 标识用 |
| `APP_PORT` | `8000` | 仅 docker-compose 用 |

---

## 常见问题

**venv 创建很慢？**
镜像内置了 `uv`，会优先用它替代 pip（快 10×）。如果本地没装 uv，会回落到内置 `python -m venv` + `pip install`。

**Windows 上 `NotImplementedError: subprocess`？**
asyncio 子进程在 Windows 需要 ProactorEventLoop。我们已经绕开 asyncio，全部用同步 `subprocess.Popen` + 线程队列。如果还有问题检查是不是 debugpy 注入了 SelectorEventLoop —— launch.json 已设 `subProcess: false` 防止注入。

**改了 backend 代码，正在跑的脚本被杀？**
开发模式 `--reload` 会重启 backend；子进程虽然用 `CREATE_NEW_PROCESS_GROUP` 隔离信号不会被杀，但 DB 记录可能停在 `running` 状态。测试脚本时建议不开 `--reload`，或在 UI 上点 Stop 强制清理。

**国内访问慢/网络问题？**
- pip 慢：镜像里加 `PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple` 环境变量
- LLM 调用慢：`ChatOpenAI` 默认 `timeout=60`，可在 LLM 配置 `extra_config` 里加 `{"timeout": 120}` 覆盖

---

## 技术栈

| 层 | 选型 |
|---|---|
| 前端 | Next.js 15 / React 19 / TailwindCSS 4 / shadcn-style UI / Monaco Editor |
| 后端 | FastAPI / SQLAlchemy 2 / APScheduler / pydantic-settings |
| Python SDK | LangChain / LangGraph |
| 包管理 | uv（fallback to pip） |
| 数据库 | SQLite / Postgres / MySQL |

---

## License

MIT
