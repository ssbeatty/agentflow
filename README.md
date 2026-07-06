# AgentFlow

**在浏览器里写 LangGraph / LangChain Python 脚本，一键跑成线上 AI Agent。**

给每个脚本自动建隔离 venv，配好 LLM 就能运行 —— 支持实时日志、内置聊天调试、定时触发、HTTP / MCP 调用，以及 MCP 工具与 Agent Skills 扩展。自托管、单镜像、`docker compose up` 即用。

<p align="center">
  <img src="docs/images/dashboard.png" alt="AgentFlow 首页" width="900">
</p>

> 适合想给团队 / 自己搭一个轻量 AI 脚本中台的人 —— 不需要 Airflow / Dify 那种重型框架，也不用为每个 agent 单独写 Dockerfile、配环境、搭接口。

---

## ✨ 能做什么

| | |
|---|---|
| 🐍 **浏览器代码编辑器** | Monaco + Python 语法高亮 + 实时语法检查，写完即存 |
| 📦 **隔离 venv** | 每个脚本一套独立环境，自动预装 langchain / langgraph 全家桶 |
| 🔌 **接任何 LLM** | OpenAI / Anthropic / DeepSeek / Ollama / 任何 OpenAI 兼容网关，UI 配置、脚本里 `get_llm()` 即用 |
| ▶️ **运行 & 调试** | WebSocket 实时日志流、结构化日志、Output / Flow / Artifacts 面板、历史回看 |
| 📊 **成本可观测** | 每次运行自动记录 LLM token 用量,首页看近 7 天趋势 / 消耗 Top 脚本,Runs 里每条带 token 数 |
| 🧪 **评估 & 回归** | 给脚本建测试集(输入 + 断言,支持包含/正则/LLM 裁判),一键跑批出通过率,和上一版对比防回归 |
| 💬 **内置聊天页** | 选个脚本直接对话，自动维护上下文；支持流式输出与「思考过程」折叠展示 |
| 🔧 **MCP 工具 & 🧩 Skills** | 接外部 MCP server、装可复用的 Agent Skill，按脚本勾选后自动注入 agent |
| ⏰ **定时触发** | cron 表达式（APScheduler）后台跑 |
| 🌐 **HTTP / MCP 接口** | 外部系统用 API Key 直接 `POST` 调用；也能让 Claude Code / Cursor 连上来开发脚本 |
| 🔐 **登录鉴权** | 整站管理后台登录保护，对外接口用签发的 API Key |
| 🗄️ **多数据库** | SQLite（本地零依赖）/ Postgres / MySQL，切 `DATABASE_URL` 即可 |
| 🐳 **Docker 化** | 前端编译进单镜像，`docker compose` 一键起 |

---

## 🚀 5 分钟上手

### 方式 1 · Docker（推荐，本地 / 内网）

直接拉 GHCR 上由 CI 构建的镜像 `ghcr.io/ssbeatty/agentflow:latest`：

```bash
cp .env.example .env      # 想跑 Postgres 就改个 POSTGRES_PASSWORD；用 SQLite 见下方注释
docker compose pull
docker compose up -d
```

打开 <http://localhost:8000> → 首次访问进入 **创建管理员** 页，设好账号密码就能用。

<p align="center">
  <img src="docs/images/setup.png" alt="首次初始化 —— 创建管理员" width="440">
</p>

> **想更轻量？** 不带 Postgres、只用内置 SQLite：
> ```bash
> DATABASE_URL=sqlite:////app/backend/data/agentflow.db docker compose up -d app --no-deps
> ```
> **想钉版本 / 本地构建？**
> ```bash
> AGENTFLOW_IMAGE=ghcr.io/ssbeatty/agentflow:v1.2.3 docker compose up -d   # 指定版本
> docker build -t agentflow:local . && AGENTFLOW_IMAGE=agentflow:local docker compose up -d   # 从源码构建
> ```

### 方式 2 · HTTPS 上线（Traefik 自动证书）

公网部署最省事的方式：Traefik 在前面终结 TLS、自动申请 Let's Encrypt 证书、`80 → 443` 跳转。

**前置**：一个解析到本机的域名（A 记录），放开 `80` / `443` 端口。

新建 `.env`，**只填两行**：

```env
DOMAIN=agentflow.example.com
SSL_EMAIL=you@example.com
```

然后起：

```bash
docker compose -f docker-compose.traefik.yml up -d
```

打开 `https://你的域名` → 创建管理员，完事。

Traefik 会自动帮你把 `PUBLIC_BASE_URL` / `COOKIE_SECURE` / `CORS_ORIGINS` 设好，所以 **登录 Cookie 和 MCP OAuth 在 https 下都开箱即用**，不用再手动折腾。

> 🔒 **正式生产**再补两个：`SECRET_KEY=<随机串>`（重启 / 多副本后登录态不失效）、`POSTGRES_PASSWORD=<强密码>`。
> 🧭 **用别的反代**（Nginx / Caddy，不走 Traefik）时，记得自己设 `PUBLIC_BASE_URL=https://你的域名`，否则 MCP OAuth 回调地址会用到内网 http 地址被拒。

### 方式 3 · 本地开发

需要 Python 3.12+、Node 20+：

```bash
# 后端
cd backend
python -m venv .venv
.venv\Scripts\activate           # Windows；macOS/Linux 用 source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --port 8000

# 另开一个终端 —— 前端 dev server（热更新，:3000）
cd frontend
npm install
npm run dev
```

> VS Code 用户：直接按 `F5`，会先编译前端再启动带 debugpy 的后端。

---

## 🖥️ 界面速览

<table>
  <tr>
    <td width="50%">
      <b>① 写脚本</b> —— 从模板起步：ReAct Agent / 流式聊天 / Deep Agent / LangGraph 循环 …<br>
      <img src="docs/images/new-script.png" alt="新建脚本，内置多种模板">
    </td>
    <td width="50%">
      <b>② 编辑 & 运行</b> —— Monaco 编辑器 + 右侧配置面板 + 底部日志 / Output / Flow。<br>
      <img src="docs/images/editor.png" alt="脚本编辑器">
    </td>
  </tr>
  <tr>
    <td width="50%">
      <b>③ 聊天调试</b> —— 选脚本直接对话，Markdown 渲染 + 折叠「思考过程」。<br>
      <img src="docs/images/chat.png" alt="内置聊天页">
    </td>
    <td width="50%">
      <b>④ 配 LLM 渠道</b> —— 一个渠道 = 一个供应商端点 + 一组模型，按优先级择优。<br>
      <img src="docs/images/settings.png" alt="LLM 渠道设置">
    </td>
  </tr>
  <tr>
    <td width="50%">
      <b>⑤ 工具 & 技能</b> —— 内置 web 搜索、接 MCP server、装 Agent Skill。<br>
      <img src="docs/images/tools.png" alt="工具 / MCP / 技能">
    </td>
    <td width="50%">
      <b>⑥ 对外接口</b> —— HTTP 同步调用，或让 Claude Code / Cursor 连 MCP 进来开发。<br>
      <img src="docs/images/api-docs.png" alt="API 参考页">
    </td>
  </tr>
</table>

---

## ✍️ 写第一个脚本

点右上角 **New Script** → 选个模板（或空白）→ 编辑器里就是一个 `run(input)` 函数：

```python
from agentflow import log, get_llm

def run(input: dict) -> dict:
    msg = input.get("message", "hello")
    log("收到消息", data={"msg": msg}, step="recv")

    llm = get_llm()                 # 取默认渠道的默认模型
    if llm is None:
        return {"reply": "还没配置 LLM，去 Settings 加一个渠道"}

    resp = llm.invoke(f"用大写复述这句话：{msg}")
    return {"reply": resp.content}
```

右侧面板点 **Create venv**（自动装 baseline 依赖）→ **Run**。日志、返回值会实时出现在底部面板。

> 入口函数默认叫 `run`、签名 `def run(input: dict) -> Any`，返回值就是这次执行的输出。可在脚本配置里改入口名。

### 想要一个能用工具的 Agent？

`get_agent()` 一行拿到带内置工具（web 搜索 / 抓网页）、以及你为该脚本勾选的 MCP 工具、Skill 的 ReAct agent：

```python
from agentflow import get_agent

def run(input: dict) -> dict:
    agent = get_agent(system_prompt="你是研究助手，用 web_search 查资料并给出来源。")
    result = agent.invoke({"messages": [("human", input["question"])]})
    return {"answer": result["messages"][-1].content}
```

### 一个 LangGraph 例子

```python
from typing import TypedDict
from agentflow import get_llm
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

内置 SDK 常用函数：`log()` 打日志、`get_llm()` / `get_agent()` / `get_deep_agent()` 拿模型和 agent、`get_tools()` 拿工具、`get_secret()` 读密钥、`web_search()` / `web_fetch()` 联网、`markdown()` / `table()` / `image()` 在聊天里渲染卡片。完整清单见平台内 `/docs` 页。

---

## 🔌 配置 LLM 渠道

进 **Settings** → **Add channel**。一个「渠道」= 一个供应商端点（key + base_url）服务一组模型；脚本用 `get_llm("<模型 id>")` 取，`get_llm()` 取默认。同一个模型被多个渠道服务时，按 `priority` 择优。

| 供应商 | provider | base_url 示例 |
|---|---|---|
| OpenAI | `openai` | 留空 |
| DeepSeek | `openai` | `https://api.deepseek.com/v1` |
| 月之暗面 / Kimi | `openai` | `https://api.moonshot.cn/v1` |
| 智谱 / GLM | `openai` | `https://open.bigmodel.cn/api/paas/v4` |
| Anthropic | `anthropic` | — |
| Ollama | `ollama` | `http://localhost:11434` |

国内大多数平台都是 OpenAI 兼容协议，`provider` 选 `openai` 填 `base_url` 即可（`anthropic` / `ollama` 走独立分支）。渠道卡片上标 ⭐ 的模型就是 `get_llm()` 的默认返回。

---

## 🔐 鉴权与对外调用

整个管理后台（所有页面 + `/api/*` 管理接口）都在**管理员登录**之后。首次访问自动进入创建管理员页；密码经 PBKDF2 哈希存库，会话用 httpOnly Cookie 维持。改密码 / 签发 API Key 在导航栏 🛡️ **安全设置**。

**外部系统调用脚本** —— 用 API Key 走同步运行接口，无需登录：

```bash
curl -X POST 'http://localhost:8000/api/executions/run?timeout=120' \
  -H 'X-API-Key: af_xxxxxxxx' \
  -H 'Content-Type: application/json' \
  -d '{"script_id":"<脚本 UUID>","input_data":{"message":"hi"}}'
# 阻塞直到脚本跑完，返回 {id,status,output_data,error,...}
```

`script_id` 从编辑器顶栏 📋 复制。API Key **只显示一次**，服务端只存哈希，丢了重新签发即可。

**长任务别干等 —— 异步提交 + 回调（webhook）** —— 加 `wait=false` 立即拿到 `id` 返回，脚本在后台跑；再给个 `callback_url`，跑完（无论成功/失败）平台会把结果 `POST` 过去：

```bash
curl -X POST 'http://localhost:8000/api/executions/run?wait=false' \
  -H 'X-API-Key: af_xxxxxxxx' -H 'Content-Type: application/json' \
  -d '{"script_id":"<UUID>","input_data":{...},"callback_url":"https://你的服务/hook"}'
# 立即返回 {"id":"...","status":"queued",...}
```

之后可以用同一个 API Key 轮询 `GET /api/executions/{id}` 看状态/结果；或者干脆等回调 —— 回调体是 `{id,script_id,status,output_data,error,started_at,finished_at,retry_count,total_tokens}`。回调是**尽力而为**（失败会重试几次再放弃，绝不影响脚本本身运行）。

**让 Claude Code / Cursor 连进来开发脚本** —— AgentFlow 自身暴露一个 MCP 端点，编程 agent 可以直接建/改脚本、装 venv、跑脚本、读报错：

```bash
claude mcp add --transport http agentflow http://localhost:8000/mcp --header "X-API-Key: af_…"
```

> 生产 HTTPS 记得 `COOKIE_SECURE=true`；多副本部署显式设 `SECRET_KEY`（否则各副本会话不互通）。

---

## 🗄️ 数据库切换

环境变量 `DATABASE_URL` 控制，**无需改代码**：

```bash
DATABASE_URL=sqlite:///./data/agentflow.db                              # SQLite（默认，零依赖）
DATABASE_URL=postgresql+psycopg2://user:pass@host:5432/dbname           # Postgres
DATABASE_URL=mysql+pymysql://user:pass@host/dbname                      # MySQL（取消 requirements 里 pymysql 注释）
```

表结构由 **Alembic** 管理，应用启动时自动 `upgrade head`（sqlite / postgres 通用）。旧库、空库都能自愈接管，无需手工干预。

---

## ⚙️ 配置项参考

通过环境变量 / `.env` 设置：

| key | 默认 | 说明 |
|---|---|---|
| `DATABASE_URL` | sqlite 本地文件 | SQLAlchemy URL |
| `DATA_DIR` | `./data/scripts` | 每脚本 venv 存放目录 |
| `CORS_ORIGINS` | `*` | 逗号分隔的允许来源，或 `*` |
| `APP_PORT` | `8000` | 仅 docker-compose 用 |
| `SECRET_KEY` | 自动生成并存 `data/.secret_key` | 签发登录 Cookie 的密钥；多副本部署需显式设置 |
| `SESSION_TTL_HOURS` | `168` | 登录有效期（小时） |
| `COOKIE_SECURE` | `false` | HTTPS 部署设 `true` |
| `PUBLIC_BASE_URL` | 空（用请求地址） | **非 Traefik 的反代/HTTPS 部署必填**，如 `https://域名`；用于拼 MCP OAuth 回调地址（Traefik 版会自动设） |
| `DOMAIN` / `SSL_EMAIL` | — | 仅 `docker-compose.traefik.yml` 用：域名 + Let's Encrypt 邮箱 |
| `POSTGRES_PASSWORD` | `agentflow` | 用 Postgres 时改成强密码 |

---

## 🧱 架构一览

```
┌─────────────────────────────────────────────┐
│  Next.js 前端（静态导出，由 FastAPI 托管）    │
│  首页 · 编辑器 · 聊天 · 工具 · 设置 · API 文档 │
└───────────────────┬─────────────────────────┘
                    │ REST + WebSocket
┌───────────────────▼─────────────────────────┐
│  FastAPI（uvicorn）                          │
│  scripts / executions / channels / cron /    │
│  mcp-servers / skills / ws 日志流 …          │
└───────┬──────────────────┬──────────────────┘
        │                  │
   ┌────▼─────┐      ┌─────▼──────────────────┐
   │ 数据库    │      │ subprocess.Popen         │
   │ (SQL*)   │      │ 每脚本独立 .venv/python  │
   └──────────┘      │ + 线程队列 → WS 实时推送 │
                     └──────────────────────────┘
```

- 每次 run 在脚本自己的 venv 里 fork 一个 python 子进程，依赖隔离
- 子进程 stdout / 结构化日志经后台线程 → asyncio 队列 → WebSocket 实时推
- 重启 backend 不影响正在跑的脚本（进程组隔离）

后端两个 Python 运行时的分工、子进程细节、迁移策略等更深入的说明见仓库根目录的 [`CLAUDE.md`](CLAUDE.md)。

---

## ❓ 常见问题

**venv 创建很慢？** 镜像内置 `uv`，优先用它替代 pip（快 ~10×）；没装 uv 会回落到 `python -m venv` + `pip`。

**Windows 上 `NotImplementedError: subprocess`？** 已全程绕开 asyncio 子进程，用同步 `subprocess.Popen` + 线程队列，正常不会遇到。

**改了 backend 代码、正在跑的脚本 DB 状态卡在 `running`？** 开发模式 `--reload` 会重启后端；子进程虽不被杀但 DB 记录可能停在 running。测试脚本时别开 `--reload`，或在 UI 点 Stop。

**国内网络慢？** pip 慢 → 给容器加 `PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple`；LLM 调用慢 → 渠道 `extra_config` 里加 `{"timeout": 120}`。

---

## 🧰 技术栈

| 层 | 选型 |
|---|---|
| 前端 | Next.js 15 / React 19 / TailwindCSS 4 / shadcn 风格 UI / Monaco Editor |
| 后端 | FastAPI / SQLAlchemy 2 / Alembic / APScheduler / pydantic-settings |
| Agent SDK | LangChain / LangGraph / deepagents / langchain-mcp-adapters |
| 包管理 | uv（回落 pip） |
| 数据库 | SQLite / Postgres / MySQL |

---

## 🧭 架构局限与 Roadmap

AgentFlow 的定位是**单机 / 小团队自托管**的轻量 AI 脚本中台 —— 一个人或一个小组、一台机器，把散落的 agent 脚本收拢到一处跑起来。为了守住「写个 `run()` 函数就能上线」的简单，它在一些维度上**刻意没做重**。下面如实列出当前架构的边界和背后的取舍，方便你判断它是否适合你的场景。

### 已知局限

| 维度 | 现状 | 原因 / 影响 |
|---|---|---|
| **水平扩展** | 单机架构：执行是本机 `subprocess.Popen`，venv 在本地磁盘，并发由单个进程内 semaphore 控制；cron（APScheduler）、暖 worker 池、WS 重放缓冲都在进程内。 | **能 scale up（换大机器），不能 scale out**。多副本会重复触发 cron、无法共享执行负载。集群化需要把执行层抽成独立 worker + 外部队列（见 Roadmap）。 |
| **隔离强度** | 主执行路径的沙箱（rlimit + bubblewrap）是**纵深防御、尽力而为**：仅 POSIX 生效，Windows / 无 bwrap 时自动降级为无隔离；网络与环境变量**不做隔离**（脚本需要自己的密钥和外网）。 | 能防「脚本把宿主 OOM / 窥探别的脚本文件」，但**不是硬多租户边界**，替代不了容器 / gVisor / VM per-run。需配合单管理员信任模型使用。 |
| **信任模型** | 单管理员门禁 + 签发 API Key，无多用户 / RBAC / 租户。密钥全局共享 —— 每个脚本都能读到所有 Secret。 | 适合「自己 / 小团队」，不适合把不同租户的不可信脚本混跑在同一实例里。 |
| **密钥静态存储** | `Secret.value`、渠道 `api_key`、OAuth token 在库里是**明文**（受「仅标准库、不引入加密依赖」约束，依赖数据卷本身受保护）。 | 没有静态加密 / KMS / Vault 集成 —— 数据库泄露即密钥泄露。 |
| **对外接口** | API Key 走的对外接口只有**同步阻塞**的 `POST /run`（撑到脚本跑完才返回）；异步创建接口只对管理员开放。 | 缺「提交即返回 + 完成回调（webhook）」，长任务只能靠长连接或轮询。 |
| **配额与限流** | API Key 无速率限制、无 token 预算、无脚本粒度权限（一个 key 通过 `/mcp` 即拥有全量脚本 CRUD + 运行权）。运行仅有墙钟超时 + 内存 rlimit 兜底。 | 跑飞的脚本能烧掉 API 预算；key 泄露影响面较大。 |
| **可观测性** | 有 per-run token 用量、结构化日志、loguru 运维日志、失败通知渠道，但**没有** metrics 端点（Prometheus）/ 分布式追踪 / 更细粒度告警。 | 单机自查够用，接入现有监控体系需自己补。 |
| **磁盘 / venv** | 每脚本一套完整 venv（数百 MB），无共享基础层去重；baseline 依赖升级不会自动同步到已建 venv；磁盘仅在删除 / 保留策略裁剪时回收。 | 脚本多时磁盘增长快；冷启动每次重导入全套 langchain（暖 worker 池可缓解 run #2+）。 |
| **前端测试** | 后端有 pytest 回归套件；**前端无自动化测试**，静态导出也决定了没有服务端路由 / 中间件。 | UI 回归靠手动跑。 |

### Roadmap

按「是否需要动架构」分两档，从高价值、低成本的先做。欢迎按实际需求提 issue 排优先级。

**近期 · 增量改进（不改整体架构）**

- [x] **对外接口异步化**：`/run?wait=false` 立即返回 execution id + 可选 `callback_url` 完成回调，长任务不再阻塞 ✅
- [ ] **API Key 粒度 & 配额**：按 key 限定可访问脚本 / 速率 / token 预算，`/mcp` 写权限可单独关闭
- [ ] **密钥静态加密**：可选 `ENCRYPTION_KEY`，落库前加密 Secret / 渠道 key / OAuth token
- [ ] **指标导出**：`/metrics`（Prometheus）暴露运行数、时延、token、失败率
- [ ] **venv 瘦身**：共享 baseline 层 / 缓存，降低磁盘占用与冷启动

**远期 · 需要架构演进**

- [ ] **水平扩展**：执行层从进程内 subprocess 抽成独立 worker + 外部队列（Redis / Celery 等），调度换成带分布式锁的方案，WS 重放挪到 Redis，多副本无重复触发
- [ ] **更硬的隔离**：容器 / gVisor / microVM per-run，可选网络策略（默认放通、按脚本白名单出网）
- [ ] **多用户 / RBAC**：从单管理员门禁演进到团队 + 角色 + 每用户脚本 + 审计日志
- [ ] **前端测试**：补 Playwright e2e / 关键组件测试

**明确不做**（当前定位下的取舍，不是遗漏）

- **不做 Airflow / Dify 级的重型 DAG 编排** —— 保持「一个 `run()` 函数就能跑」的心智
- **不追求把 agentflow SDK 发成独立 pip 包** —— 它靠 runner 往 `sys.path` 注入，刻意随平台版本走
- **不在主执行路径上做硬网络隔离** —— 脚本本就需要访问 LLM / MCP / 自己的外部服务

---

## License

MIT
