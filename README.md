# ProjectGeneratorAgent

[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![OpenAI Compatible](https://img.shields.io/badge/API-OpenAI%20Compatible-purple.svg)](https://platform.openai.com/docs/api-reference)

> 一句话生成项目的独立智能体：输入自然语言需求，自动产出「需求文档 → 设计文档 → 完整代码 → 自检报告」全流程交付物。

---

**目录**

- [快速开始](#快速开始)
- [主要特性](#主要特性)
- [项目结构](#项目结构)
- [工作流模板](#工作流模板)
- [CLI 命令](#cli-命令)
- [REST API](#rest-api)
- [配置](#配置)
- [架构要点](#架构要点)
- [依赖](#依赖)
- [贡献指南](#贡献指南)
- [许可证](#许可证)

---

## 快速开始

```bash
# 1. 安装（editable：保证 skills/templates/web 与代码同源）
pip install -e .
# 或只装运行时依赖：pip install -r requirements.txt

# 2. 配置 LLM API Key
pga config set llm_api_key sk-xxxxxxxxxxxxxxxx

# 3. 一句话生成项目
pga run "做一个带用户登录的待办事项 Web 应用，前后端分离"

# 4. 按提示在检查点确认（或加 --auto 跳过）
pga approve <workflow_id>
pga show <workflow_id>

# 5. 查看产出
ls workspaces/<workflow_id>/code/
```

未安装为命令时，也可用 `python -m agent.cli ...` / `python -m agent.server`。

也可启动 Web 界面操作：

```bash
python -m agent.server
# 浏览器打开 http://127.0.0.1:8000
```

## 主要特性

- **一句话到项目** — 自然语言需求经 4~5 步流水线自动产出完整项目
- **工具调用驱动** — 基于 LLM function calling（write_file / read_file / list_files / run_command），模型自主决定写哪些文件
- **检查点机制** — 每步产出后可暂停审核，支持 approve / reject / revise（结构化打回带目标章节与严重度）
- **多层健康检查** — 主产物大小 + 二级文件齐全 + 代码语法检查 + dev-selfcheck 真实执行测试（`strict` 模式下额外做运行时验证），失败按原因分类驱动补全重试
- **自动调试** — 健康检查重试耗尽后自动调用 `dev-debug` 定位根因并修复，修好后继续收尾；`pga debug` 可对失败步骤手动介入
- **重试与容错** — LLM 调用指数退避重试、无输出超时看门狗、循环检测、上下文压缩、state.json 原子写 + 备份
- **命令沙箱** — 拦截 `rm -rf` / `format` / 外发请求等危险操作，支持 Windows 盘符保护
- **SKILL 版本化** — 支持 `skills/<name>/<version>/SKILL.md` 目录级版本隔离，`rerun --latest` 升级
- **USD 成本追踪** — 内置模型价目表，按步累计 prompt/completion tokens 与 USD 成本，`pga show` 展示
- **任意 LLM 后端** — 兼容 DeepSeek / Qwen / Moonshot / OpenAI / 本地 vLLM 等所有 OpenAI 兼容 API
- **两种运行形态** — CLI 单进程 + FastAPI 服务（含 WebSocket 实时日志、Token 认证、CORS 白名单）
- **Web 前端** — 创建工作流、实时日志、文件浏览、检查点交互、设置页
- **设计系统生成** — dev-design 产出 DESIGN_SYSTEM.md（语义化 color/typography/spacing/motion token），dev-code 落地为 tokens.css，前端组件禁止裸 hex/任意 px
- **UI 质量门禁** — `agent/ui_gate.py` 静态执行并产出 `UI_GATE.md`：token 纪律（裸 hex）、WCAG 对比度、img alt / 按钮可访问名 / input label、viewport / @media / reduced-motion、emoji 结构图标、触控目标启发式；block 模式驱动重试
- **Git 集成** — 工作区自动 git init/commit/branch，dev-review 基于 git diff 做增量评审，rerun 在独立分支隔离
- **多 Agent 协作** — dev-review 通过 dispatch_subagent 派发独立子代理评审，避免"自己审自己"盲区；dev-debug 四阶段科学调试

## 项目结构

```
ProjectGeneratorAgent/
├── agent/                     # 核心 Python 包
│   ├── config.py              #   配置：LLMConfig（含价目表）、WorkflowConfig、路径常量
│   ├── llm_client.py          #   OpenAI 兼容客户端（流式 + tool calling）
│   ├── resilience.py          #   重试策略：retry_async、熔断器、token 估算
│   ├── security.py            #   命令沙箱：校验 run_command 安全性
│   ├── skill_loader.py        #   SKILL.md 加载、渲染、版本解析（目录级版本化）
│   ├── workspace.py           #   工作区管理、上下文摘要、原子写、备份
│   ├── checkpoint_store.py    #   检查点落盘信号（_checkpoints/{step}.json，跨进程）
│   ├── ui_gate.py             #   静态 UI 质量门（token/对比度/可访问性/响应式 → UI_GATE.md）
│   ├── health_check.py        #   三层健康检查 + 产物契约校验
│   ├── agent_loop.py          #   LLM 工具循环核心（看门狗/循环检测/上下文压缩）
│   ├── workflow_engine.py     #   工作流引擎（调度/检查点/状态持久化/成本累计）
│   ├── cli.py                 #   CLI 入口（pga 命令）
│   └── server.py              #   FastAPI 服务（REST + WebSocket + 认证）
├── templates/                 # 工作流模板
│   ├── grad_project.yaml      #   全栈项目（4~5 步，含可选评审）
│   ├── script_only.yaml       #   纯脚本（3~4 步，跳过重型设计）
│   └── api_only.yaml          #   纯后端 API（4~5 步，无前端）
├── skills/                    # Skill 指令书
│   ├── dev-requirement/       #   需求分析 → REQUIREMENT.md
│   ├── dev-design/            #   系统设计 → DESIGN.md + DESIGN_SYSTEM.md（设计 token）
│   ├── dev-code/              #   编码实现 → code/ + RUN.md（消费 token，产出 tokens.css）
│   ├── dev-review/            #   代码评审 → REVIEW.md（可选，含 UI 合规维度）
│   ├── dev-selfcheck/         #   自测验证 → SELF_CHECK.md（含 UI 质量门禁）
│   ├── dev-debug/             #   系统调试 → DEBUG_REPORT.md（四阶段科学调试）
│   └── _shared/               #   共享设计知识（非 skill，供各 skill 引用）
│       ├── design-principles.md       #   UI 风格速查（14 种主流风格）
│       ├── color-theory.md            #   语义 token + WCAG + 行业配色基线
│       ├── typography-pairing.md      #   精选字体配对 + Google Fonts
│       ├── motion-basics.md           #   动效时长/缓动/reduced-motion
│       └── accessibility-checklist.md #   WCAG AA 核心项
├── web/                       # 前端界面
│   ├── index.html             #   主页：创建工作流 + 列表
│   ├── workflow.html          #   工作流详情：实时日志 + 文件浏览
│   ├── settings.html          #   设置页：LLM / 服务配置
│   └── assets/                #   CSS + JS
├── tests/                     # pytest 单测（恢复语义 / 检查点 / usage / 验证门禁）
├── local_config.example.json  #   配置模板（复制为 local_config.json 使用）
├── pyproject.toml             #   打包与 console_scripts（pga / pga-server）
├── requirements.txt           #   Python 依赖
└── README.md
```

## 工作流模板

### grad_project — 全栈项目

| 步骤 | Skill | 检查点 | 产出 | 条件 |
| ---- | ----- | ------ | ---- | ---- |
| 1 | `dev-requirement` | ✅ approve | `REQUIREMENT.md` | 必选 |
| 2 | `dev-design` | ✅ feedback | `DESIGN.md` + `DESIGN_SYSTEM.md` | 必选 |
| 3 | `dev-code` | ✅ approve | `code/` + `RUN.md`（含 `tokens.css`） | 必选 |
| 4 | `dev-review` | — | `REVIEW.md`（含 UI 合规维度） | `enable_review=true` |
| 5 | `dev-selfcheck` | — | `SELF_CHECK.md`（含 UI 质量门禁） | 必选 |

### script_only — 纯脚本

需求 → 轻量设计 → 编码 → 自测，跳过重型架构设计。适用于数据清洗、定时抓取、批处理脚本。

### api_only — 纯后端 API

不含前端代码生成，dev-code 只产出 `backend/`。

## CLI 命令

```bash
pga run "需求"                        # 启动工作流
  --template <key>                     #   指定模板（默认 grad_project）
  --project-type <type>                #   项目类型：fullstack/frontend_only/backend_only/cli/script
  --enable-review                      #   启用 dev-review 评审步骤
  --auto                               #   自动继续（跳过检查点暂停）
  --no-checkpoint                      #   关闭检查点
  --max-iter <N>                       #   agent 最大迭代（默认 30）
  --verification-gate <mode>           #   strict / tests（默认）/ off，dev-selfcheck 门禁
  --ui-gate <mode>                     #   block（默认）/ warn / off，静态 UI 质量门

pga list                               # 列出所有工作流
pga show <id>                          # 查看详情（含版本/成本/指标汇总）
pga resume <id>                        # 恢复暂停的工作流

pga approve <id> [反馈]                # 检查点通过（写 _checkpoints/ 信号）
  --no-run                             #   已废弃，兼容保留

pga reject <id> <反馈>                 # 检查点打回
pga revise <id> <反馈>                 # 结构化打回（带目标章节与严重度）
  --target-section <section>           #   指定要修改的文件/章节
  --severity <level>                   #   blocker / major / minor / nit

pga rerun <id> <skill>                 # 重跑某步骤（后续步骤自动级联重跑）
  --clean                              #   重跑前清理该步主产物
  --latest                             #   升级到最新 SKILL 版本

pga debug <id>                         # 对失败步骤运行 dev-debug
  --step <skill>                       #   指定步骤（默认第一个 failed）
  --reason <text>                      #   补充失败现象/线索
  --no-recheck                         #   只跑调试，不重新健康检查
  --resume                             #   修复后继续执行后续步骤

pga delete <id>                        # 删除工作流
pga templates                          # 列出模板
pga skills                             # 列出 skills

pga config set <key> <value>           # 设置配置
pga config get [key]                   # 查看配置
pga config path                        # 显示配置文件路径
pga config list-keys                   # 列出可配置项
```

## REST API

```bash
python -m agent.server --host 127.0.0.1 --port 8000
```

| 方法 | 路径 | 说明 |
| ---- | ---- | ---- |
| POST | `/api/workflows` | 创建工作流 |
| POST | `/api/workflows/{id}/start` | 启动工作流（后台异步） |
| GET | `/api/workflows` | 列出工作流 |
| GET | `/api/workflows/{id}` | 查看详情 |
| GET | `/api/workflows/{id}/files` | 列出工作区文件 |
| GET | `/api/workflows/{id}/files/{path}` | 读取文件内容（受保护文件拦截） |
| GET | `/api/workflows/{id}/export` | 导出为 zip |
| DELETE | `/api/workflows/{id}` | 删除工作流 |
| POST | `/api/workflows/{id}/checkpoint` | 提交检查点响应（支持 approve/reject/revise） |
| POST | `/api/workflows/{id}/rerun/{skill}?clean=&latest=` | 重跑步骤 |
| GET | `/api/templates` | 列出模板 |
| GET | `/api/skills` | 列出 skills |
| GET | `/api/config` | 查看配置（API Key 脱敏） |
| PUT | `/api/config` | 更新配置 |
| GET | `/api/health` | 健康检查 |
| WS | `/ws/workflows/{id}` | 实时日志推送 |

服务安全：Bearer Token 认证（`~/.project_generator/server_token`），覆盖工作流读取/创建/导出、检查点、重跑与配置读写；WebSocket 通过 `?token=` 传递同一 token 并校验 Origin；CORS 白名单（默认仅 localhost）；受保护文件拦截（state.json / project.json 等）。`/api/health`、`/api/templates`、`/api/skills` 为公开只读端点。

## 配置

配置优先级（从高到低）：

1. **环境变量**：`LLM_API_KEY` / `LLM_MODEL` / `LLM_BASE_URL` / `OPENAI_API_KEY` 等
2. **用户配置文件**：`~/.project_generator/config.json`（通过 `pga config set` 写入）
3. **项目配置降级**：`local_config.json`（项目根目录，含 API Key，已 gitignore）
4. **代码内默认值**

资源目录（`skills/` / `templates/` / `web/`）默认按「包所在目录 → 当前工作目录」查找；非 editable 安装时用 `PGA_HOME=/path/to/checkout` 指向资源目录。

常用配置项：

| Key | 说明 | 默认值 |
| --- | ---- | ------ |
| `llm_api_key` | LLM API Key | — |
| `llm_model` | 模型名 | `deepseek-chat` |
| `llm_base_url` | API 地址 | `https://api.deepseek.com/v1` |
| `llm_price_input_per_1m` | 输入单价 USD/1M tokens | 自动查 MODEL_PRICING 表 |
| `llm_price_output_per_1m` | 输出单价 USD/1M tokens | 自动查 MODEL_PRICING 表 |
| `server_enable_auth` | 是否启用 Token 认证 | `true` |
| `server_allowed_origins` | CORS 白名单（逗号分隔） | `http://localhost:*,http://127.0.0.1:*` |
| `server_max_concurrent_workflows` | 并发工作流上限 | `2` |

常见 LLM 后端：

| 后端 | base_url | model |
| ---- | -------- | ----- |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |
| Qwen | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` |
| Moonshot | `https://api.moonshot.cn/v1` | `moonshot-v1-32k` |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o` |
| 本地 vLLM | `http://localhost:8000/v1` | 自定义 |

## 架构要点

**容错链路**：LLM 调用 → 业务层指数退避重试（`resilience.py`）→ agent_loop 无输出看门狗 + 循环检测 + 上下文压缩 → 健康检查分类补全重试 → state.json 原子写 + .bak 备份

**成本追踪**：`AgentRunResult` 分别累计 prompt/completion tokens → `StepState.cost_usd` 按 `LLMConfig.estimate_cost()` 折算 USD → `WorkflowState.computed_cost_usd` 实时汇总 → `pga show` 展示

**检查点**：结构化响应 schema（`action: approve|reject|revise` + `target_section` + `severity: blocker|major|minor|nit` + `specific_issues`），旧版 `approved` 字段自动归一化兼容。revise 反馈精准注入 CONTEXT.md。检查点信号落盘到工作区 `_checkpoints/{step}.json`，运行中的工作流每 0.5s 轮询——`pga approve/reject/revise` 因此可以跨进程生效；进程退出后 `pga resume` 会消费已有决策（approve 直接收尾、不重跑该步），`failed` 步骤则重置为待执行并重跑，全部步骤 `completed/skipped` 才允许标记 `completed`。

**自动调试**：`dev-code` / `dev-selfcheck` 健康检查重试耗尽后，`_maybe_escalate_debug` 渲染 dev-debug prompt（失败原因 + 文件清单 + 修复要求）并执行一轮根因调试，随后重跑健康检查；修好则继续收尾，修不好才判 failed。`auto_debug` / `debug_max_rounds` 可配，LLM/网络错误不触发（避免掩盖基础设施问题）。`pga debug` 复用同一实现，支持 `--no-recheck` 与 `--resume`。

**版本化**：SKILL 支持双布局——平铺 `skills/<name>/SKILL.md`（默认）和版本目录 `skills/<name>/<version>/SKILL.md`（semver 降序排列）。`state.json` 记录每步实际版本，`rerun --latest` 升级到最新。

**设计系统链路**：dev-design 产出 `DESIGN_SYSTEM.md`（语义化 color/typography/spacing/motion token + 行业反模式清单）→ dev-code 落地为 `code/frontend/src/styles/tokens.css`（+ `tailwind.config.js` 扩展），前端组件通过 `var(--*)` / Tailwind token 类消费，禁止裸 hex 与任意 px → dev-review 评审 token 合规性 → dev-selfcheck 由 `agent/ui_gate.py` 静态执行 UI 质量门禁（token 纪律 / 裸 hex / WCAG 对比度 / 可访问性 / 响应式），产出 `UI_GATE.md`，block 模式阻断并驱动重试。共享设计知识沉淀在 `skills/_shared/`（curated references，非 CSV 数据库），由 SKILL.md front matter 的 `shared: [..]` 按需注入——如 dev-requirement 不加载设计知识，dev-code 只加载 color/typography，避免每个 skill 背 34KB 无关上下文。

**Git 集成**：工作区自动 `git init` + 每步产出后 `git commit`；dev-review 基于 `git diff <base>..HEAD` 做增量评审（仅审变更，非全扫）；`rerun` 在独立分支隔离，支持增量复审。`enable_git=False` 可关闭。

## 依赖

| 包 | 用途 |
| -- | ---- |
| `openai>=1.30` | LLM 客户端（tool calling + 流式） |
| `pyyaml>=6.0` | 模板 YAML 解析 |
| `rich>=13.0` | CLI 美化输出（可选，未装时自动降级为 print） |
| `fastapi>=0.115` | REST API 服务（可选） |
| `uvicorn[standard]>=0.30` | ASGI 服务器（可选） |

开发与测试依赖：`pip install -e ".[dev]" && python -m pytest tests`

## 贡献指南

欢迎提交 Issue 和 Pull Request。

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 提交 Pull Request

**代码规范**：
- 遵循 PEP 8 风格指南
- 新增功能需补充文档说明与 pytest 用例（`python -m pytest tests`）
- 确保 Python 语法检查通过

## 许可证

本项目基于 [MIT License](LICENSE) 开源。

Copyright (c) 2026 zuili1204

---

**项目维护者**：[zuili1204](https://github.com/zuili1204)