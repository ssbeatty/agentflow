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
- **🔧 MCP 工具接入** — 配置外部 MCP server，按脚本选择后注入到 `get_tools()` / `get_agent()`
- **🔐 鉴权** — 管理后台整站登录保护（首次访问设置管理员）；对外运行接口用签发的 API Key 鉴权
- **🗄️ 多数据库** — SQLite（本地）/ Postgres / MySQL，切 `DATABASE_URL` 即可
- **🐳 Docker 化** — 单镜像（前端 baked-in） + docker-compose 一键起

---

## 截图

> 占位 — 主页 / 编辑器 / 聊天页 / API Docs

---

## 快速开始

### 方式 1：Docker（推荐）

直接拉取 GHCR 上由 CI 构建的镜像 `ghcr.io/ssbeatty/agentflow:latest`：

```bash
cp .env.example .env          # 改个 POSTGRES_PASSWORD（生产建议设 SECRET_KEY / COOKIE_SECURE）
docker compose pull
docker compose up -d
```

打开 <http://localhost:8000>，首次访问会进入 `/setup` 创建管理员。

> 想钉某个版本：`AGENTFLOW_IMAGE=ghcr.io/ssbeatty/agentflow:v1.2.3 docker compose up -d`
> 想从源码本地构建：`docker build -t agentflow:local . && AGENTFLOW_IMAGE=agentflow:local docker compose up -d`

### 方式 1b：HTTPS 上线（Traefik + Let's Encrypt）

公网部署用 `docker-compose.traefik.yml`：Traefik 在前面终结 TLS、自动申请证书（ACME TLS challenge）、`80 → 443` 跳转，并反代到 app。它会自动设好 `PUBLIC_BASE_URL` / `COOKIE_SECURE` / `CORS_ORIGINS`，所以 **MCP OAuth 和登录 Cookie 在 https 下都正常**。

前置：域名 A 记录指向本机，开放 80 / 443 端口。

```bash
cp .env.example .env
# 至少填：DOMAIN=your.domain.com  SSL_EMAIL=you@example.com
#         POSTGRES_PASSWORD=...   SECRET_KEY=<随机串>
docker compose -f docker-compose.traefik.yml pull
docker compose -f docker-compose.traefik.yml up -d
```

打开 `https://your.domain.com` → 进入 `/setup` 创建管理员。

> **MCP OAuth 注意**：自托管（非 Traefik）的反代部署，必须设 `PUBLIC_BASE_URL=https://你的域名`，否则 OAuth 注册时会用 http/内网地址、被 Todoist 等 provider 拒绝（400）。

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

## 鉴权与安全

整个管理后台（所有 UI 页面 + `/api/*` 管理接口）都在**管理员登录**之后。

- **首次启动** 访问站点会自动进入 `/setup` 创建管理员（用户名 + 密码，密码经 PBKDF2 哈希存库）。之后用 `/login` 登录，会话用 httpOnly Cookie 维持。
- **修改密码 / 签发 API Key** 在导航栏 🛡️ → **安全设置**（`/security`）。
- **API Key 仅显示一次**，请创建后立即保存；服务端只存 SHA-256 哈希，丢失只能重新签发，可随时吊销。
- 生产环境用 HTTPS 时设 `COOKIE_SECURE=true`；多副本部署时显式设置 `SECRET_KEY`（否则各副本各自生成、会话不互通）。

**外部系统调用脚本**用 API Key 走同步运行接口（无需登录）：

```bash
curl -X POST 'http://localhost:8000/api/executions/run?timeout=120' \
  -H 'X-API-Key: af_xxxxxxxx' \
  -H 'Content-Type: application/json' \
  -d '{"script_id":"<UUID>","input_data":{"message":"hi"}}'
```

---

## HTTP API

详细文档在平台内置的 `/docs` 页面。除对外的 `/api/executions/run`（用 API Key）外，下列管理接口都需要管理员登录态（浏览器里自动带 Cookie；脚本里加 `Authorization: Bearer <登录返回的 token>`）：

```bash
# 同步执行（等结果）— 对外接口，用 API Key 鉴权
curl -X POST 'http://localhost:8000/api/executions/run?timeout=120' \
  -H 'X-API-Key: af_xxxxxxxx' \
  -H 'Content-Type: application/json' \
  -d '{"script_id":"<UUID>","input_data":{"message":"hi"}}'

# 异步触发 + 轮询（管理接口，需登录态）
curl -X POST http://localhost:8000/api/executions \
  -H 'Authorization: Bearer <TOKEN>' \
  -d '{"script_id":"<UUID>","input_data":{}}'
curl http://localhost:8000/api/executions/<EXECUTION_ID> -H 'Authorization: Bearer <TOKEN>'

# 实时日志（WebSocket）— 浏览器同源握手自动带 Cookie
ws://localhost:8000/ws/executions/<EXECUTION_ID>
```

`script_id` 从编辑器顶栏 📋 复制按钮获取。`<TOKEN>` 来自 `POST /api/auth/login` 的返回。

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
DATABASE_URL=sqlite:///./data/agentflow.db

# Postgres
DATABASE_URL=postgresql+psycopg2://user:pass@host:5432/dbname

# MySQL (取消 requirements.txt 里的 pymysql)
DATABASE_URL=mysql+pymysql://user:pass@host/dbname
```

表结构在应用启动时自动 `create_all`（仅建表，不补列）。Schema 变更通过 `backend/migrations/` 管理，运行 `python migrations/apply.py` 应用。

---

## 架构

```
┌─────────────────────────────────────────────┐
│  Next.js (static export → served by FastAPI)│
│  ├ /          Dashboard                     │
│  ├ /script    Editor + Logs + Runs          │
│  ├ /converse  Chat with any script          │
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
| `APP_ENV` | `development` | 标识用 |
| `APP_PORT` | `8000` | 仅 docker-compose 用 |
| `SECRET_KEY` | 自动生成并存 `data/.secret_key` | 签发管理员会话 Cookie 的密钥；多副本部署需显式设置 |
| `SESSION_TTL_HOURS` | `168` | 登录有效期（小时） |
| `COOKIE_SECURE` | `false` | HTTPS 部署设 `true`，会话 Cookie 标记为 Secure |
| `PUBLIC_BASE_URL` | 空（用请求地址） | 反代/HTTPS 部署必填，如 `https://域名`；用于拼 MCP OAuth 回调地址 |
| `DOMAIN` / `SSL_EMAIL` | — | 仅 `docker-compose.traefik.yml` 用：域名 + Let's Encrypt 邮箱 |

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
