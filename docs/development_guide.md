# ProjectGeneratorAgent 开发文档

> 一个独立运行的项目生成智能体：用户输入一句话需求，自动产出「需求文档 + 设计文档 + 完整代码 + 自检报告」。
> 本文档描述其架构、模块、工作流、扩展方法，对应源码位于 `ProjectGeneratorAgent/`。

***

## 目录

1. [项目概述](#1-项目概述)
2. [架构设计](#2-架构设计)
3. [目录结构](#3-目录结构)
4. [核心模块详解](#4-核心模块详解)
5. [工作流执行流程](#5-工作流执行流程)
6. [Skill 开发指南](#6-skill-开发指南)
7. [模板开发指南](#7-模板开发指南)
8. [CLI 使用指南](#8-cli-使用指南)
9. [REST API 参考](#9-rest-api-参考)
10. [WebSocket 协议](#10-websocket-协议)
11. [扩展与自定义](#11-扩展与自定义)
12. [部署](#12-部署)

***

## 1. 项目概述

### 1.1 定位

ProjectGeneratorAgent 是「一句话生成项目」的独立智能体应用。

### 1.2 核心能力

- **一句话到项目**：用户输入自然语言需求，自动完成需求分析、系统设计、编码实现、自测验证四步流水线
- **工具调用驱动**：基于 LLM function calling（write\_file / read\_file / list\_files / run\_command），让模型自己决定写哪些文件
- **检查点机制**：每步产出后可暂停等待用户审核，支持打回重做与反馈注入
- **多层健康检查**：主产物大小 + 二级文件齐全 + 代码语法检查（Python `compile()` / JS 括号匹配 / HTML 标签闭合）
- **工作区隔离**：每个工作流一个独立目录，状态以 `state.json` 持久化，不依赖数据库锁
- **两种运行形态**：CLI 单进程 + FastAPI 服务（带 WebSocket 实时日志）

### 1.3 设计原则

| 原则          | 说明                                                                          |
| ----------- | --------------------------------------------------------------------------- |
| 纯 Python 实现 | 不依赖 Claude Code CLI，任意 OpenAI 兼容后端（DeepSeek/Qwen/Moonshot/OpenAI/本地 vLLM）均可 |
| 明文配置        | SKILL.md 不加密，YAML 模板可读可改，便于二次开发                                             |
| 结构化状态       | 用 `state.json` + `project.json` 替代从 markdown 解析元数据                          |
| 最小依赖        | 仅 5 个 PyPI 包：openai / pyyaml / rich / fastapi / uvicorn                     |
| 失败可恢复       | 工作流可在任意步骤暂停、重跑、恢复                                                           |

***

## 2. 架构设计

### 2.1 分层架构

```
┌────────────────────────────────────────────────────────────┐
│  接口层（CLI / REST API / WebSocket）                       │
│  agent/cli.py    agent/server.py                           │
├────────────────────────────────────────────────────────────┤
│  编排层                                                    │
│  agent/workflow_engine.py  模板加载 / 步骤调度 / 检查点     │
│  agent/agent_loop.py       LLM 工具循环（核心）             │
├────────────────────────────────────────────────────────────┤
│  能力层                                                    │
│  agent/llm_client.py       OpenAI 兼容 API 客户端           │
│  agent/skill_loader.py     SKILL.md 渲染                    │
│  agent/workspace.py        工作区 / 上下文摘要              │
│  agent/health_check.py     产出校验                         │
├────────────────────────────────────────────────────────────┤
│  资源层                                                    │
│  templates/*.yaml          工作流模板                       │
│  skills/*/SKILL.md         skill 指令书                     │
│  workspaces/{id}/          每个工作流的独立产出目录         │
└────────────────────────────────────────────────────────────┘
```

### 2.2 数据流

```
用户输入"做一个待办事项 Web 应用"
        │
        ▼
[CLI/HTTP] → WorkflowEngine.create_workflow()
        │      生成 workflow_id，创建 workspaces/{id}/
        │      写入 project.json + CONTEXT.md + state.json
        ▼
[WorkflowEngine.run_workflow()]
        │
        ├─► 步骤 1: dev-requirement
        │     │  render_skill_prompt() 渲染 SKILL.md
        │     │  run_agent_loop() 调 LLM，LLM 调 write_file 写 REQUIREMENT.md
        │     │  health_check: 主产物 ≥200B
        │     │  checkpoint: 暂停等用户 approve
        │     ▼
        ├─► 步骤 2: dev-design
        │     │  读取上一步产出 + 用户反馈
        │     │  LLM 写 DESIGN.md
        │     │  health_check: 主产物 ≥500B
        │     │  checkpoint: 暂停等用户 feedback
        │     ▼
        ├─► 步骤 3: dev-code
        │     │  LLM 写 code/ 下所有文件 + RUN.md
        │     │  health_check: 按 project_type 检查必需文件
        │     │              + 代码语法检查
        │     │  checkpoint: 暂停等用户 approve
        │     ▼
        ├─► 步骤 4: dev-selfcheck
        │     │  LLM 自检代码、修复问题、写 SELF_CHECK.md
        │     │  health_check: 主产物 ≥100B
        │     ▼
        └─► state.status = "completed"
```

### 2.3 关键设计决策

**为什么用 tool calling 而不是子进程？**

本智能体改用 OpenAI SDK 的 tool calling，让 LLM 通过 `write_file(path, content)` 工具直接产出文件。优势：

- 单进程，无子进程管理开销
- 协议透明（标准 OpenAI function calling）
- 任意 OpenAI 兼容后端可用
- 工具调用可观测、可重放

**为什么用 JSON 而不是 SQLite？**

本智能体用 `state.json` 文件存储，每个工作流独立一个文件，无锁冲突，且便于人工查看与版本控制。

***

## 3. 目录结构

```
ProjectGeneratorAgent/
├── agent/                          # 核心 Python 包
│   ├── __init__.py                 # 包初始化（__version__）
│   ├── config.py                   # 配置：路径、LLMConfig、WorkflowConfig
│   ├── llm_client.py               # OpenAI 兼容客户端（含流式 tool_call 累积）
│   ├── skill_loader.py             # SKILL.md 加载与渲染
│   ├── workspace.py                # 工作区管理 + 上下文摘要
│   ├── health_check.py             # 三层健康检查
│   ├── agent_loop.py               # LLM 工具循环核心
│   ├── workflow_engine.py          # 工作流引擎
│   ├── cli.py                      # CLI 入口（pga 命令）
│   └── server.py                   # FastAPI 服务
├── templates/                      # 工作流模板（YAML）
│   └── grad_project.yaml           # 「一句话生成项目」模板
├── skills/                         # Skill 指令书（明文 markdown）
│   ├── dev-requirement/
│   │   └── SKILL.md
│   ├── dev-design/
│   │   └── SKILL.md
│   ├── dev-code/
│   │   └── SKILL.md
│   └── dev-selfcheck/
│       └── SKILL.md
├── workspaces/                     # 工作流产出目录（运行时自动创建）
│   └── {workflow_id}/              # 每个工作流一个独立目录
│       ├── project.json            # 项目元数据
│       ├── CONTEXT.md              # 上下文摘要（替代 CLAUDE.md）
│       ├── state.json              # 工作流状态
│       ├── REQUIREMENT.md          # 步骤 1 产出
│       ├── DESIGN.md               # 步骤 2 产出
│       ├── code/                   # 步骤 3 产出的代码
│       └── SELF_CHECK.md           # 步骤 4 产出
├── docs/
│   ├── workflow_analysis.md        # Modex-MH-Agent 工作流学习文档
│   └── development_guide.md        # 本文档
├── requirements.txt                # Python 依赖
└── README.md                       # 项目说明
```

***

## 4. 核心模块详解

### 4.1 `agent/config.py` — 配置模块

**职责**：集中管理路径常量、LLM 配置、工作流配置、用户配置文件读写。

**关键类**：

- `LLMConfig`：LLM 客户端配置（base\_url / api\_key / model / timeout / temperature / max\_tokens）
  - `from_env()`：从环境变量或 `~/.project_generator/config.json` 加载
  - `validate()`：校验 api\_key 非空
  - `__post_init__`：自动补全 `/v1` 路径后缀
- `WorkflowConfig`：工作流运行时配置（agent\_max\_iter / inactivity\_timeout / checkpoint\_timeout / enable\_checkpoints / auto\_proceed / project\_type）

**配置优先级**（从高到低）：

1. 环境变量（`LLM_BASE_URL` / `OPENAI_BASE_URL` / `LLM_API_KEY` / `OPENAI_API_KEY` / `LLM_MODEL` 等）
2. `~/.project_generator/config.json`（通过 `pga config set` 写入）
3. 代码内默认值

**路径常量**：

| 常量               | 值                         | 说明          |
| ---------------- | ------------------------- | ----------- |
| `PROJECT_ROOT`   | `agent/` 的父目录             | 项目根         |
| `SKILLS_DIR`     | `PROJECT_ROOT/skills`     | skill 指令书目录 |
| `TEMPLATES_DIR`  | `PROJECT_ROOT/templates`  | 模板目录        |
| `WORKSPACES_DIR` | `PROJECT_ROOT/workspaces` | 工作区根        |

### 4.2 `agent/llm_client.py` — LLM 客户端

**职责**：封装 OpenAI 兼容 API 调用，支持流式 + 非流式 + tool calling。

**关键类**：

- `ToolCall`：工具调用的结构化表示（id / name / arguments）
- `LLMResponse`：LLM 响应的标准化表示（text / tool\_calls / finish\_reason / usage）
- `LLMClient`：异步客户端
  - `chat()`：非流式调用
  - `chat_stream()`：流式调用，文本 delta 通过 `on_delta` 回调实时输出，工具调用缓冲累积后一次性返回（避免流式 tool\_call 分片问题）
  - `close()`：关闭底层 httpx 连接

**工具定义辅助**：`make_tool(name, description, parameters)` 构造 OpenAI function 格式的工具定义。

**流式 tool\_call 处理**：OpenAI 流式响应中，tool\_call 的 arguments 是分片返回的（每个 chunk 包含一段 JSON 字符串）。`chat_stream` 用 `accumulated_tools: dict[int, dict]` 按 index 累积，流结束后一次性 `json.loads` 解析为完整 `ToolCall` 列表。

### 4.3 `agent/skill_loader.py` — Skill 加载器

**职责**：读取明文 SKILL.md，替换占位符，拼接上下文。

**关键函数**：

- `load_skill_md(skill_name)`：读取 `skills/{skill_name}/SKILL.md` 明文内容
- `render_skill_prompt(skill_name, arguments, extra_context, workspace_files)`：
  1. 读取 SKILL.md
  2. 替换 `$ARGUMENTS` → 用户输入
  3. 清理 slash command 引用（如 `/dev-code` → `dev-code`）
  4. 拼接工作区文件清单
  5. 拼接额外上下文（如上一步反馈）
- `list_skills()`：列出所有 skill 名称

本智能体直接读明文 markdown，便于二次开发与版本控制。

### 4.4 `agent/workspace.py` — 工作区管理

**职责**：单个工作流的隔离工作区，负责文件读写、扫描、上下文构建。

**关键类**：

- `ProjectMeta`：项目元数据（title / template / project\_type / auto\_proceed / extra）
  - `to_json()` / `from_json()`：序列化为 `project.json`
- `Workspace`：
  - `write_file(rel_path, content)`：写入文件（自动创建父目录，防路径穿越）
  - `read_file(rel_path)`：读取文件
  - `file_exists(rel_path)` / `file_size(rel_path)`
  - `scan()`：扫描工作区，返回非隐藏文件相对路径列表（排除 `.git` / `__pycache__` / `node_modules` 等）
  - `build_context_summary(files, max_chars=12000)`：构建上下文摘要，按字符预算截断，优先读取 `.md` / `.json` / `.yaml` 等关键文件
  - `write_context_md(title, template, meta)`：生成 `CONTEXT.md`（替代 Modex-MH-Agent 的 `CLAUDE.md`）
  - `inject_once(marker, content)`：幂等地把内容追加到 `CONTEXT.md`（用于注入用户反馈）
  - `write_project_meta(meta)` / `read_project_meta()`：读写 `project.json`
  - `detect_project_type()`：检测项目类型（优先读 `project.json`，回退到 `CONTEXT.md` 解析，默认 `fullstack`）

**路径穿越防护**：`_safe_rel(rel_path)` 检查路径不是绝对路径、不含 `..`，防止 LLM 写到工作区外。

### 4.5 `agent/health_check.py` — 健康检查

**职责**：对每步产出做三层校验。

**三层检查**：

1. **主产物大小**：`check_primary_output(workspace, rel_path, min_size)`
   - 检查文件存在 + 大小 ≥ `min_size` 字节（防空文件占位）
2. **二级文件齐全**：`check_step_companions(workspace, skill_name, extra_required, min_size)`
   - dev-code 按 `project_type` 动态决定必需文件（见下表）
   - 其他 skill 用模板里的 `required_companions`
3. **代码语法检查**：`check_all_code_files(workspace)`
   - Python：`compile(content, path, "exec")` 真 syntax 检查
   - JS/TS：括号匹配（处理字符串/注释中的括号）
   - HTML：标签闭合检查（识别 void\_tags 自闭合标签）

**dev-code 按 project\_type 的必需文件**：

| project\_type   | 必需文件                                                                     |
| --------------- | ------------------------------------------------------------------------ |
| `fullstack`     | `code/backend/main.py` + `code/frontend/package.json` + `code/RUN.md`    |
| `backend_only`  | `code/backend/main.py` + `code/backend/requirements.txt` + `code/RUN.md` |
| `frontend_only` | `code/package.json` + `code/RUN.md`                                      |
| `cli`           | `code/RUN.md`                                                            |
| `script`        | `code/RUN.md`                                                            |

**`CheckResult`** **dataclass**：`ok` / `missing` / `errors` / `warnings`，聚合检查结果。

### 4.6 `agent/agent_loop.py` — LLM Agent 循环

**职责**：tool calling 驱动的智能体执行核心。对应 Modex-MH-Agent 的 `ClaudeRunner.run_skill`。

**工具定义**（4 个）：

| 工具            | 用途              | 参数                                |
| ------------- | --------------- | --------------------------------- |
| `write_file`  | 写文件到工作区         | `path`（相对路径）, `content`（UTF-8 文本） |
| `read_file`   | 读工作区文件          | `path`（相对路径）                      |
| `list_files`  | 列出工作区文件         | `subdir`（可选子目录）                   |
| `run_command` | 在工作区执行 shell 命令 | `command`（完整命令，超时 60s）            |

**工具执行器**：`_exec_write_file` / `_exec_read_file` / `_exec_list_files` / `_exec_run_command`，每个都返回字符串结果（成功返回内容，失败返回 `ERROR: ...`）。

**主循环** **`run_agent_loop(llm, workspace, prompt, max_iter, on_output, on_tool_call, on_tool_result)`**：

```
1. 构造 messages = [system, user(prompt)]
2. for iter in 1..max_iter:
   a. 调 LLM (流式 + tools)
   b. 把 assistant 消息加入历史
   c. 如果没工具调用 → 返回（finish_reason=stop）
   d. 否则执行所有工具调用
   e. 把工具结果作为 tool 消息加入历史
3. 达到 max_iter → 标记 truncated
```

**`AgentRunResult`** **dataclass**：`iterations` / `files_written` / `files_read` / `commands_run` / `final_text` / `total_tokens` / `truncated` / `error`。

**回调机制**：三个可选 async 回调（`on_output` / `on_tool_call` / `on_tool_result`）用于实时输出到 CLI/WebSocket。

### 4.7 `agent/workflow_engine.py` — 工作流引擎

**职责**：模板加载、步骤调度、检查点、状态持久化、日志广播。

**模板定义**：

- `StepDef`：单步定义（来自 YAML）
  - `skill_name` / `display_name` / `has_checkpoint` / `checkpoint_type`
  - `primary_output` / `min_size`：主产物检查
  - `required_companions` / `required_companions_dynamic`：二级文件检查
- `TemplateDef`：工作流模板
  - `name` / `template_key` / `pipeline_skill` / `default_project_type`
  - `sub_steps: list[StepDef]`

**状态定义**：

- `StepState`：单步运行时状态（status: `pending|running|waiting_checkpoint|completed|failed|skipped`）
- `WorkflowState`：工作流完整状态（持久化到 `state.json`）
  - `to_json()` / `from_json()`
  - `add_log(step, level, message)`：添加日志（保留最近 500 条）

**检查点机制** **`CheckpointManager`**：

- 用 `asyncio.Event` 实现轻量级等待
- `submit_checkpoint(workflow_id, response)`：提交响应并唤醒等待方
- `wait_checkpoint(workflow_id, timeout)`：等待响应，超时自动返回 `{approved: True}`（避免流程卡死）

**日志广播** **`BroadcastManager`**：

- 订阅/退订回调列表
- `broadcast(event)`：异步广播事件到所有回调
- 兼容 CLI（直接 print）和 WebSocket（推送 JSON）

**`WorkflowEngine`** **类**：

| 方法                                             | 说明                     |
| ---------------------------------------------- | ---------------------- |
| `create_workflow(template_key, title, params)` | 创建工作流，返回 workflow\_id  |
| `run_workflow(workflow_id)`                    | 异步运行工作流（遍历 sub\_steps） |
| `rerun_step(workflow_id, skill_name)`          | 重跑某步骤                  |
| `get_state(workflow_id)`                       | 获取工作流状态                |
| `list_workflows()`                             | 列出所有工作流                |
| `delete_workflow(workflow_id)`                 | 删除工作流（含工作区目录）          |
| `close()`                                      | 关闭 LLM 客户端             |

**`run_workflow`** **核心流程**（见 [§5](#5-工作流执行流程)）。

### 4.8 `agent/cli.py` — CLI 入口

**职责**：命令行交互，使用 rich 美化输出。

**11 个子命令**：见 [§8](#8-cli-使用指南)。

**异步命令处理**：`run` / `resume` / `approve` / `reject` / `rerun` 是 async，通过 `asyncio.run()` 执行；其他是 sync。

**rich 降级**：rich 未安装时自动降级为普通 `print`，保证最小依赖可运行。

### 4.9 `agent/server.py` — FastAPI 服务

**职责**：提供 REST API + WebSocket 实时日志，便于嵌入 Web 应用。

**后台任务管理**：`_running_tasks: dict[str, asyncio.Task]` 跟踪每个 workflow\_id 的后台任务，避免重复启动。

**WebSocket 日志推送**：连接 `/ws/workflows/{id}` 后：

1. 发送当前状态快照（`snapshot` 事件）
2. 持续推送该 workflow\_id 的所有事件（`log` / `checkpoint`）
3. 工作流结束时发送 `finished` / `failed` 事件并关闭连接
4. 30 秒无事件发送 `heartbeat` 保活

***

## 5. 工作流执行流程

### 5.1 创建工作流

`WorkflowEngine.create_workflow(template_key, title, params)`：

1. 加载 YAML 模板：`load_template(template_key)`
2. 生成 `workflow_id`（UUID 前 16 位）
3. 创建工作区：`Workspace(workflow_id)` → `workspaces/{id}/`
4. 确定 `project_type`（来自 params 或模板默认值）
5. 写 `project.json`（结构化元数据）
6. 生成 `CONTEXT.md`（标题 + 模板 + 参数 + 工作区文件清单 + 上下文摘要）
7. 初始化 `WorkflowState`（status=pending，steps 列表）
8. 持久化 `state.json`

### 5.2 运行工作流

`WorkflowEngine.run_workflow(workflow_id)`：

```
state.status = "running"
for idx, step_def in enumerate(tmpl.sub_steps):
    1. 跳过 status=completed 的步骤
    2. 遇到 status=failed 的步骤则 break
    3. 标记当前步骤 status=running
    4. 渲染 prompt：
       - workspace.scan() 获取已有文件
       - _build_extra_context() 注入上一步反馈
       - render_skill_prompt() 渲染 SKILL.md
    5. 调用 run_agent_loop()，传入三个回调（on_output/on_tool_call/on_tool_result）
       回调内部调用 _broadcast_log() 实时推送
    6. 如果出错且无文件产出 → 标记 failed，返回
    7. 健康检查 _run_health_checks()：
       - 主产物大小
       - 二级文件齐全
       - 代码语法检查（仅 dev-code/dev-selfcheck）
       不通过 → 标记 failed，返回
    8. 检查点（如启用）：
       - 标记 status=waiting_checkpoint
       - 广播 checkpoint 事件
       - wait_checkpoint() 等待响应
       - 用户打回 → 标记 paused，返回
       - 用户反馈 → inject_once() 注入 CONTEXT.md
    9. 标记 status=completed
state.status = "completed"
```

### 5.3 检查点交互

| 用户操作    | CLI 命令                    | REST API                                              | 效果                   |
| ------- | ------------------------- | ----------------------------------------------------- | -------------------- |
| 通过      | `pga approve {id}`        | `POST /api/workflows/{id}/checkpoint {approved:true}` | 自动恢复工作流              |
| 通过 + 反馈 | `pga approve {id} "做得不错"` | `{approved:true, feedback:"..."}`                     | 反馈注入 CONTEXT.md，然后恢复 |
| 打回      | `pga reject {id} "需求要改"`  | `{approved:false, feedback:"..."}`                    | 标记 paused，等待 rerun   |

**超时自动确认**：`wait_checkpoint` 默认 600 秒超时，超时后自动返回 `{approved: True, auto: True}`，避免流程卡死。

### 5.4 重跑步骤

`WorkflowEngine.rerun_step(workflow_id, skill_name)`：

1. 加载状态，找到目标步骤
2. 重置该步骤：status=pending，清空 started\_at / completed\_at / error\_message / output\_files / checkpoint\_response
3. 标记 state.status=running
4. 调用 `run_workflow()` 从该步骤继续（已完成的步骤会被跳过）

***

## 6. Skill 开发指南

### 6.1 SKILL.md 结构

一个 skill 是 `skills/{skill_name}/SKILL.md` 文件，结构如下：

```markdown
# {skill 中文名} ({skill_name})

## 任务目标
{这个 skill 要做什么}

## 输入
- `$ARGUMENTS`：{用户输入的什么内容}
- 工作区已有文件：{应该读哪些文件}

## 执行步骤
1. {第一步做什么}
2. {第二步做什么}
...

## 产物要求
- 必须产出：{文件路径}（{位置}）
- 大小要求：≥ {N} 字节
- 文档结构必须包含：{章节列表}

## 关键约束
- {约束 1}
- {约束 2}
```

### 6.2 占位符

| 占位符          | 含义       | 来源                                                     |
| ------------ | -------- | ------------------------------------------------------ |
| `$ARGUMENTS` | 用户的一句话需求 | `WorkflowEngine.create_workflow(title=...)` 的 title 参数 |

渲染时还会自动拼接：

- **工作区文件清单**：`workspace.scan()` 的结果，作为「## 当前工作区文件」段
- **额外上下文**：上一步的用户反馈，作为「## 补充上下文」段

### 6.3 添加新 Skill

1. 创建目录 `skills/{skill_name}/`
2. 编写 `SKILL.md`（参考 `skills/dev-requirement/SKILL.md`）
3. 在模板 YAML 的 `sub_steps` 中引用：
   ```yaml
   sub_steps:
     - skill_name: my-new-skill
       display_name: 我的新 Skill
       has_checkpoint: true
       checkpoint_type: approve
       primary_output: OUTPUT.md
       min_size: 100
       required_companions: []
   ```
4. 运行 `pga skills` 确认新 skill 已被识别

### 6.4 Skill 编写规范

- **明确产物**：必须说明产出什么文件、放在哪个路径、最小字节数
- **明确输入**：说明应该读哪些已有文件（避免 LLM 重复读取）
- **明确步骤**：分步骤说明执行流程，让 LLM 按部就班
- **明确约束**：不要做什么（如「不要写代码，只写需求文档」）
- **使用工具**：明确要求用 `write_file` 工具产出文件，而不是把内容写在对话里

***

## 7. 模板开发指南

### 7.1 模板 YAML 结构

`templates/{template_key}.yaml`：

```yaml
name: {模板中文名}
template_key: {模板 key}
pipeline_skill: {流水线启动 skill}

default_project_type: {fullstack|frontend_only|backend_only|cli|script}

sub_steps:
  - skill_name: {skill 名称}
    display_name: {步骤中文名}
    has_checkpoint: {true|false}
    checkpoint_type: {approve|feedback|null}
    primary_output: {主产物相对路径}
    min_size: {最小字节数}
    required_companions: [{二级必需文件列表}]
    required_companions_dynamic: {true|false}  # 按 project_type 动态决定
```

### 7.2 字段说明

| 字段                                        | 类型         | 说明                                       |
| ----------------------------------------- | ---------- | ---------------------------------------- |
| `name`                                    | str        | 模板中文名                                    |
| `template_key`                            | str        | 模板 key（与文件名一致）                           |
| `pipeline_skill`                          | str        | 流水线启动 skill（仅用于标识）                       |
| `default_project_type`                    | str        | 默认项目类型                                   |
| `sub_steps[].skill_name`                  | str        | 对应 `skills/` 下的 skill 名称                 |
| `sub_steps[].display_name`                | str        | 步骤中文名（用于日志展示）                            |
| `sub_steps[].has_checkpoint`              | bool       | 是否启用检查点                                  |
| `sub_steps[].checkpoint_type`             | str        | 检查点类型：`approve`（审核通过）/ `feedback`（给反馈）   |
| `sub_steps[].primary_output`              | str        | 主产物相对路径（用于大小检查）                          |
| `sub_steps[].min_size`                    | int        | 主产物最小字节数                                 |
| `sub_steps[].required_companions`         | list\[str] | 二级必需文件列表                                 |
| `sub_steps[].required_companions_dynamic` | bool       | 为 true 时按 project\_type 动态决定（仅 dev-code） |

### 7.3 添加新模板

1. 创建 `templates/{template_key}.yaml`
2. 确保引用的 skill 都存在于 `skills/` 下
3. 运行 `pga templates` 确认新模板已被识别
4. 用 `pga run "需求" -t {template_key}` 启动

### 7.4 模板示例：grad\_project

见 [templates/grad\_project.yaml](../templates/grad_project.yaml)，定义了 4 步流水线：

```
dev-requirement (approve) → dev-design (feedback) → dev-code (approve) → dev-selfcheck (无)
```

***

## 8. CLI 使用指南

### 8.1 安装

```bash
# 进入项目目录
cd ProjectGeneratorAgent

# 安装依赖（建议用虚拟环境）
pip install -r requirements.txt

# 安装为可执行命令（可选，方便全局调用）
pip install -e .
# 之后可以用 `pga` 直接调用
```

如果不安装为可执行命令，用 `python -m agent.cli` 代替 `pga`。

### 8.2 首次配置

```bash
# 配置 LLM API Key（必填）
pga config set llm_api_key sk-xxxxxxxxxxxxxxxx

# 可选：配置 API 地址（默认 DeepSeek）
pga config set llm_base_url https://api.deepseek.com/v1

# 可选：配置模型名（默认 deepseek-chat）
pga config set llm_model deepseek-chat

# 查看配置
pga config get

# 查看配置文件路径
pga config path
```

也支持环境变量：`LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` 等（优先级高于配置文件）。

### 8.3 命令一览

| 命令                       | 说明        |
| ------------------------ | --------- |
| `pga run "需求"`           | 启动工作流     |
| `pga list`               | 列出所有工作流   |
| `pga show <id>`          | 查看工作流详情   |
| `pga resume <id>`        | 恢复暂停的工作流  |
| `pga approve <id> [反馈]`  | 检查点确认通过   |
| `pga reject <id> <反馈>`   | 检查点打回     |
| `pga rerun <id> <skill>` | 重跑某步骤     |
| `pga delete <id>`        | 删除工作流     |
| `pga templates`          | 列出模板      |
| `pga skills`             | 列出 skills |
| `pga config set <k> <v>` | 设置配置      |
| `pga config get [k]`     | 查看配置      |

### 8.4 典型用法

```bash
# 1. 启动一个全栈 Web 应用工作流
pga run "做一个带用户登录的待办事项 Web 应用，前后端分离"

# 2. 工作流在 dev-requirement 后暂停，查看产出
cat workspaces/{id}/REQUIREMENT.md

# 3. 确认通过，继续执行
pga approve {id}

# 4. 在 dev-design 后给反馈
pga approve {id} "设计可以，但要增加 Redis 缓存层"

# 5. 工作流完成后查看产出
pga show {id}
ls workspaces/{id}/code/

# 6. 如果某步失败，重跑
pga rerun {id} dev-code
```

### 8.5 高级选项

```bash
# 自动继续（不暂停检查点，全程自动）
pga run "需求" --auto

# 关闭检查点
pga run "需求" --no-checkpoint

# 指定项目类型
pga run "写一个 CLI 计算器" --project-type cli

# 指定模板
pga run "需求" -t grad_project

# 增大 agent 最大迭代次数（默认 30）
pga run "需求" --max-iter 50

# 详细日志
pga -v run "需求"
```

***

## 9. REST API 参考

启动服务：

```bash
python -m agent.server --host 127.0.0.1 --port 8000
```

### 9.1 端点一览

| 方法     | 路径                                  | 说明             |
| ------ | ----------------------------------- | -------------- |
| GET    | `/api/health`                       | 健康检查           |
| POST   | `/api/workflows`                    | 创建工作流          |
| POST   | `/api/workflows/{id}/start`         | 启动工作流          |
| GET    | `/api/workflows`                    | 列出工作流          |
| GET    | `/api/workflows/{id}`               | 查看工作流详情        |
| GET    | `/api/workflows/{id}/files`         | 列出工作区文件        |
| GET    | `/api/workflows/{id}/files/{path}`  | 读取工作区文件        |
| DELETE | `/api/workflows/{id}`               | 删除工作流          |
| POST   | `/api/workflows/{id}/checkpoint`    | 提交检查点响应        |
| POST   | `/api/workflows/{id}/rerun/{skill}` | 重跑某步骤          |
| GET    | `/api/templates`                    | 列出模板           |
| GET    | `/api/skills`                       | 列出 skills      |
| GET    | `/api/config`                       | 查看配置           |
| PUT    | `/api/config`                       | 更新配置           |
| WS     | `/ws/workflows/{id}`                | WebSocket 实时日志 |

### 9.2 创建并启动工作流

```bash
# 1. 创建
curl -X POST http://127.0.0.1:8000/api/workflows \
  -H "Content-Type: application/json" \
  -d '{
    "title": "做一个待办事项 Web 应用",
    "template": "grad_project",
    "project_type": "fullstack",
    "enable_checkpoints": true
  }'
# 返回: {"workflow_id": "abc123...", "status": "pending", ...}

# 2. 启动
curl -X POST http://127.0.0.1:8000/api/workflows/abc123/start
# 返回: {"workflow_id": "abc123", "status": "running"}
```

### 9.3 提交检查点

```bash
# 通过
curl -X POST http://127.0.0.1:8000/api/workflows/abc123/checkpoint \
  -H "Content-Type: application/json" \
  -d '{"approved": true, "feedback": "做得不错", "run": true}'

# 打回
curl -X POST http://127.0.0.1:8000/api/workflows/abc123/checkpoint \
  -H "Content-Type: application/json" \
  -d '{"approved": false, "feedback": "需求要改：增加登录"}'
```

### 9.4 查看产出

```bash
# 列出文件
curl http://127.0.0.1:8000/api/workflows/abc123/files

# 读取单个文件
curl http://127.0.0.1:8000/api/workflows/abc123/files/REQUIREMENT.md
```

***

## 10. WebSocket 协议

连接：`ws://127.0.0.1:8000/ws/workflows/{workflow_id}`

### 10.1 事件类型

| event        | 说明               | 字段                                                                       |
| ------------ | ---------------- | ------------------------------------------------------------------------ |
| `snapshot`   | 连接后立即发送的状态快照     | `workflow_id`, `state`                                                   |
| `log`        | 日志事件             | `workflow_id`, `step`, `level`, `message`, `timestamp`                   |
| `checkpoint` | 检查点事件            | `workflow_id`, `step`, `display_name`, `checkpoint_type`, `output_files` |
| `finished`   | 工作流完成            | `workflow_id`                                                            |
| `failed`     | 工作流失败            | `workflow_id`                                                            |
| `heartbeat`  | 心跳保活（30 秒无事件时发送） | 无                                                                        |
| `error`      | 错误               | `message`                                                                |

### 10.2 JavaScript 示例

```javascript
const ws = new WebSocket('ws://127.0.0.1:8000/ws/workflows/abc123');

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  switch (data.event) {
    case 'snapshot':
      console.log('当前状态:', data.state);
      break;
    case 'log':
      console.log(`[${data.timestamp}] [${data.step}] ${data.message}`);
      break;
    case 'checkpoint':
      console.log('等待检查点:', data.checkpoint_type);
      // 显示确认按钮...
      break;
    case 'finished':
      console.log('工作流完成');
      ws.close();
      break;
  }
};
```

***

## 11. 扩展与自定义

### 11.1 添加新的工作流模板

场景：除了「一句话生成项目」，还想做「一句话生成 API 文档」「一句话生成数据脚本」等。

步骤：

1. 编写对应的 skill（`skills/doc-gen/SKILL.md` 等）
2. 创建模板 `templates/doc_gen.yaml`：
   ```yaml
   name: 一句话生成 API 文档
   template_key: doc_gen
   pipeline_skill: doc-analyze
   default_project_type: script
   sub_steps:
     - skill_name: doc-analyze
       display_name: 文档分析
       has_checkpoint: true
       checkpoint_type: approve
       primary_output: DOC_PLAN.md
       min_size: 200
     - skill_name: doc-code
       display_name: 文档生成
       has_checkpoint: false
       primary_output: code/README.md
       min_size: 500
   ```
3. 运行：`pga run "生成用户手册" -t doc_gen`

### 11.2 添加新工具

场景：希望 LLM 能调用 `http_request` 工具发起 HTTP 请求。

步骤：

1. 在 `agent/agent_loop.py` 添加工具定义：
   ```python
   HTTP_REQUEST_TOOL = make_tool(
       name="http_request",
       description="发起 HTTP 请求",
       parameters={
           "type": "object",
           "properties": {
               "method": {"type": "string", "enum": ["GET", "POST", "PUT", "DELETE"]},
               "url": {"type": "string"},
               "body": {"type": "string"},
           },
           "required": ["method", "url"],
       },
   )
   ALL_TOOLS.append(HTTP_REQUEST_TOOL)
   ```
2. 添加执行器：
   ```python
   async def _exec_http_request(workspace: Workspace, args: dict) -> str:
       import aiohttp
       async with aiohttp.ClientSession() as session:
           async with session.request(args["method"], args["url"], ...) as resp:
               return f"status: {resp.status}\nbody: {await resp.text()}"
   _TOOL_EXECUTORS["http_request"] = _exec_http_request
   ```
3. 在 `AgentRunResult` 添加 `http_requests` 字段记录（可选）

### 11.3 替换 LLM 后端

本智能体支持任意 OpenAI 兼容后端。常见配置：

| 后端       | base\_url                                           | model             | 说明      |
| -------- | --------------------------------------------------- | ----------------- | ------- |
| DeepSeek | `https://api.deepseek.com/v1`                       | `deepseek-chat`   | 默认，性价比高 |
| Qwen     | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus`       | 阿里通义    |
| Moonshot | `https://api.moonshot.cn/v1`                        | `moonshot-v1-32k` | Kimi    |
| OpenAI   | `https://api.openai.com/v1`                         | `gpt-4o`          | 官方      |
| 本地 vLLM  | `http://localhost:8000/v1`                          | 自定义               | 本地部署    |

配置方式：

```bash
pga config set llm_base_url https://api.moonshot.cn/v1
pga config set llm_api_key sk-xxx
pga config set llm_model moonshot-v1-32k
```

或用环境变量：

```bash
export LLM_BASE_URL=https://api.moonshot.cn/v1
export LLM_API_KEY=sk-xxx
export LLM_MODEL=moonshot-v1-32k
```

### 11.4 嵌入到现有应用

作为 Python 库嵌入：

```python
import asyncio
from agent.config import LLMConfig, WorkflowConfig
from agent.workflow_engine import WorkflowEngine

async def main():
    engine = WorkflowEngine(
        llm_config=LLMConfig.from_env(),
        workflow_config=WorkflowConfig(auto_proceed=True),
    )
    workflow_id = engine.create_workflow(
        template_key="grad_project",
        title="做一个待办事项应用",
        params={"project_type": "fullstack"},
    )
    state = await engine.run_workflow(workflow_id)
    print(f"状态: {state.status}")
    await engine.close()

asyncio.run(main())
```

作为 Web 服务嵌入：

```python
from agent.server import create_app
app = create_app()
# 用 uvicorn 或 gunicorn 启动
```

***

## 12. 部署

### 12.1 本地开发

```bash
cd ProjectGeneratorAgent
pip install -r requirements.txt
pga config set llm_api_key sk-xxx
pga run "做一个待办事项 Web 应用"
```

### 12.2 Docker 部署

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -r requirements.txt
ENV PYTHONUTF8=1
ENV PYTHONIOENCODING=utf-8
EXPOSE 8000
CMD ["python", "-m", "agent.server", "--host", "0.0.0.0", "--port", "8000"]
```

```bash
docker build -t project-generator-agent .
docker run -d -p 8000:8000 \
  -e LLM_API_KEY=sk-xxx \
  -v $(pwd)/workspaces:/app/workspaces \
  project-generator-agent
```

### 12.3 生产环境注意事项

- **API Key 安全**：用环境变量传入，不要写入配置文件
- **工作区持久化**：`workspaces/` 目录要挂载到持久卷
- **并发限制**：单进程同时运行的工作流建议 ≤ 5（受 LLM API 速率限制）
- **超时配置**：长任务建议调大 `LLM_TIMEOUT`（默认 600 秒）
- **日志**：用 `--log-level info` 启动服务，排查问题用 `--log-level debug`

***

***

## 附录：快速开始

```bash
# 1. 安装
cd ProjectGeneratorAgent
pip install -r requirements.txt

# 2. 配置 API Key
pga config set llm_api_key sk-xxxxxxxxxxxxxxxx

# 3. 一句话生成项目
pga run "做一个带用户登录的待办事项 Web 应用，前后端分离"

# 4. 按提示在检查点确认
pga approve {workflow_id}

# 5. 查看产出
ls workspaces/{workflow_id}/code/
```

***

*文档版本：1.0.0  |  最后更新：2026-07-13*
