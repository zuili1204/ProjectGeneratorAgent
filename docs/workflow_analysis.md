# Modex-MH-Agent「一句话生成项目」工作流学习文档

> 本文档基于对 `Modex-MH-Agent/resources/app/backend` 的源码与 Cython 编译模块（`workflow_engine.cp311-win_amd64.pyd`、`claude_runner.cp311-win_amd64.pyd`）的实际反编译与运行时反射分析整理而成，描述其「一句话生成项目」工作流的执行全过程与 skill 调用机制。

---

## 一、项目整体架构

Modex-MH-Agent 是一个 Electron + Python FastAPI 桌面应用，整体分为四层：

| 层 | 位置 | 职责 |
|---|---|---|
| Electron 主进程 | `resources/app/main.js` | 启动 Python 后端子进程、创建窗口、托盘、自动更新 |
| 前端 SPA | `resources/app/dist/` | React 构建产物，与后端通过 HTTP/WebSocket 通信 |
| Python 后端 | `resources/app/backend/` | FastAPI + uvicorn，提供 REST API、WebSocket、工作流引擎 |
| Skill 资源 | `resources/app/skills/` | 100+ 个 SKILL.md.enc 加密文件，每个对应一个可执行 skill |

后端关键模块（位于 `backend/services/`）：

- `workflow_engine.cp311-win_amd64.pyd` — 工作流 DAG 编排引擎，定义 `TEMPLATES` 模板表、`run_workflow`、`run_single_step`、检查点机制等
- `claude_runner.cp311-win_amd64.pyd` — 调用 Claude Code CLI 子进程执行 skill，`ClaudeRunner.run_skill` 是核心入口
- `llm_client.cp311-win_amd64.pyd` — LLM 客户端封装（被 `main.py` monkey-patch 后改用 OpenAI 兼容协议）
- `state_store.cp311-win_amd64.pyd` — SQLite 异步状态存储
- `skill_crypto.cp311-win_amd64.pyd` — SKILL.md.enc 解密模块

---

## 二、「一句话生成项目」工作流定义

### 2.1 模板注册

`workflow_engine.TEMPLATES` 是一个 dict，注册了所有工作流模板。其中「一句话生成项目」对应的 key 为 `grad_project`，定义如下：

```python
# 通过反射获取的真实定义
{
    "grad_project": {
        "name": "一句话生成项目",
        "pipeline_skill": "dev-requirement",   # 流水线由 dev-requirement 启动
        "sub_steps": [
            {
                "skill_name": "dev-requirement",
                "display_name": "需求分析",
                "has_checkpoint": True,
                "checkpoint_type": "approve"   # 用户审核通过后才继续
            },
            {
                "skill_name": "dev-design",
                "display_name": "系统设计",
                "has_checkpoint": True,
                "checkpoint_type": "feedback"  # 用户给反馈后继续
            },
            {
                "skill_name": "dev-code",
                "display_name": "编码实现",
                "has_checkpoint": True,
                "checkpoint_type": "approve"
            },
            {
                "skill_name": "dev-selfcheck",
                "display_name": "自测验证",
                "has_checkpoint": False,
                "checkpoint_type": None
            }
        ]
    }
}
```

### 2.2 四步流水线

| 顺序 | skill_name | 中文名 | 检查点类型 | 说明 |
|---|---|---|---|---|
| 1 | `dev-requirement` | 需求分析 | `approve` | 解析用户的一句话需求，产出 `REQUIREMENT.md` |
| 2 | `dev-design` | 系统设计 | `feedback` | 基于需求产出 `DESIGN.md`，含架构、目录、技术栈 |
| 3 | `dev-code` | 编码实现 | `approve` | 在 `code/` 目录生成完整代码 + `RUN.md` 启动说明 |
| 4 | `dev-selfcheck` | 自测验证 | 无 | 自检代码可运行性，修正问题 |

### 2.3 检查点类型语义

| 类型 | 含义 | 用户操作 |
|---|---|---|
| `approve` | 产出需用户审核通过 | 选择「通过」或「打回重做」 |
| `feedback` | 产出需用户给反馈 | 提交文本反馈，引擎把反馈注入下一步 prompt |
| `assets_resolve` | 资产清点确认 | 选择保留/排除哪些资产（仅 paper_from_assets 用） |

`wait_checkpoint(workflow_id, timeout=600)` 等待用户响应，超时 10 分钟后自动确认继续，避免流程卡死。

---

## 三、工作流执行全过程

### 3.1 创建工作流

调用链：`POST /api/workflows` → `workflows.create(body)` → `workflow_engine.create_new_workflow(template, title, params, enable_checkpoints)`

`create_new_workflow` 完成：

1. 生成 `workflow_id`（UUID）
2. 在 `WORKSPACES_DIR/{workflow_id}/` 创建独立工作区目录
3. 调用 `_resolve_template(template, params, workspace)` 动态重写 `sub_steps`（处理中文替换、docx 模式、format-profile 插入）
4. 在工作区生成 `CLAUDE.md`（`_generate_claude_md`），内容包含：
   - 项目标题
   - 模板名（grad_project）
   - params 段（YAML 风格，含 `- project_type: xxx`）
   - 已注入的工作区上下文摘要
5. 在 SQLite `workflows` 表插入记录，在 `workflow_steps` 表批量插入 4 条步骤记录（状态 `pending`）

### 3.2 启动工作流

调用链：`POST /api/workflows/{wf_id}/start` → `workflows.start(wf_id)` → `asyncio.create_task(workflow_engine.run_workflow(wf_id))`

返回 immediately，工作流在后台异步执行，前端通过 WebSocket 实时接收日志和事件。

### 3.3 run_workflow 主循环

`run_workflow(workflow_id)` 是核心调度函数，伪代码（基于 docstring 与路由层调用关系还原）：

```python
async def run_workflow(workflow_id):
    wf = await get_workflow(workflow_id)
    tmpl = _resolve_template(wf.template, wf.params, wf.workspace_dir)
    
    # 从暂停处恢复：跳过已完成步骤
    for step in tmpl.sub_steps:
        if step.status == 'completed':
            continue  # 跳过已完成
        if step.status == 'failed':
            break     # 失败步骤不自动跳过
        
        # 标记当前步骤为 running
        await update_step(step.id, status='running')
        await _notify(workflow_id, {'event': 'step_start', 'skill': step.skill_name})
        
        # 调用 claude_runner 执行 skill
        result = await claude_runner.run_skill(
            skill_name=step.skill_name,
            arguments=wf.title,           # 用户输入的一句话作为 $ARGUMENTS
            cwd=wf.workspace_dir,          # 工作区作为 CWD
            workflow_id=workflow_id,
            on_output=_broadcast_output,  # 实时日志广播
            workspace_files=_scan_workspace(wf.workspace_dir),
            context_summary=_build_context_summary(wf.workspace_dir, files),
        )
        
        # 健康检查：二级文件是否齐全
        ok, missing = _check_step_companions(wf.workspace_dir, step.skill_name)
        if not ok:
            # 触发 AUTO-RECOVER 或标记失败
            await update_step(step.id, status='failed', error_message=f'缺失文件: {missing}')
            break
        
        # 检查点暂停
        if step.has_checkpoint:
            await update_step(step.id, status='waiting_checkpoint')
            checkpoint_data = {'skill': step.skill_name, 'output_files': result.files}
            await _notify(workflow_id, {'event': 'checkpoint', **checkpoint_data})
            response = await wait_checkpoint(workflow_id, timeout=600)
            await resolve_checkpoint(workflow_id, response)
            # 把用户反馈注入 CLAUDE.md（_inject_once 幂等追加）
        
        await update_step(step.id, status='completed', output_files=result.files)
    
    await update_workflow(workflow_id, status='completed')
```

### 3.4 ClaudeRunner.run_skill — skill 执行核心

签名：

```python
def run_skill(
    self,
    skill_name: str,                          # 如 'dev-requirement'
    arguments: str,                           # 用户输入的一句话需求
    cwd: Union[str, Path],                    # 工作区目录
    workflow_id: str,
    on_output: Optional[Callable[[str], Awaitable[None]]] = None,  # 实时输出回调
    extra_params: Optional[Dict] = None,
    workspace_files: Optional[List[str]] = None,    # 工作区已有文件列表
    context_summary: Optional[str] = None,          # 上下文摘要
    inactivity_timeout: int = 2400,                 # 无输出超时 40 分钟
    resume_session_id: Optional[str] = None,        # 恢复会话
) -> Dict
```

执行过程：

1. `_load_skill_prompt(skill_name, arguments, extra_params)`：
   - 从 `SKILLS_DIR/{skill_name}/SKILL.md.enc` 解密读取 SKILL.md 内容
   - 把 `$ARGUMENTS` 占位符替换成用户输入
   - 清理 slash command 引用（如 `/dev-code` → 标准描述）
   - 拼接 `workspace_files` 和 `context_summary` 到 prompt 末尾
2. 构造子进程环境变量（`get_env_for_subprocess`）：
   - `ANTHROPIC_BASE_URL=http://127.0.0.1:{port}/anthropic_proxy` — 指向本地格式转换代理
   - `ANTHROPIC_API_KEY=sk-ant-proxy-dummy`
   - 移除 `ANTHROPIC_AUTH_TOKEN`（避免绕过代理）
   - 注入 Git Bash 路径（`CLAUDE_CODE_GIT_BASH_PATH`）
3. 调用 `asyncio.create_subprocess_exec` 启动 `claude.exe -p "{prompt}"`：
   - `claude.exe` 位于 `runtime/node/node_modules/@anthropic-ai/claude-code/bin/`
   - 工作目录 = `cwd` 参数（工作区目录）
   - Claude Code 以 Agent 模式运行，可以读写工作区文件、执行命令、调用工具
4. 流式读取 stdout，每行通过 `on_output` 回调广播到 WebSocket
5. 子进程退出后，扫描工作区文件增量，返回 `{'files_created': [...], 'files_modified': [...], 'session_id': '...'}`
6. 无输出超时 2400 秒（40 分钟）后强制取消

### 3.5 Anthropic → OpenAI 格式转换代理

由于后端通过 monkey-patch 把 `llm_client._call_llm_sync` 改为调用 OpenAI 兼容 API（DeepSeek），但 Claude Code CLI 只认 Anthropic 协议，因此在 FastAPI 中实现了 `/anthropic_proxy/v1/messages` 端点做格式转换：

```
Claude Code  →  POST /anthropic_proxy/v1/messages  →  转换为 OpenAI Chat Completions  →  调用 DeepSeek API
                                       ↑
                            _convert_anthropic_to_openai()
                            - system 字段 → role:system 消息
                            - tool_use 块 → tool_calls
                            - tool_result 块 → role:tool 消息
                            - tools 数组 → OpenAI function 格式
```

响应方向同样转换：`_convert_openai_to_anthropic` 把 OpenAI 响应包装成 Anthropic Messages 响应，包含：
- 流式 SSE 事件（`message_start` / `content_block_start` / `content_block_delta` / `content_block_stop` / `message_delta` / `message_stop`）
- DSML 文本工具调用回退解析（`_parse_dsml_tool_calls`，处理 DeepSeek 特有的 `<｜｜DSML｜｜tool_calls>` 格式）

---

## 四、Skill 调用机制详解

### 4.1 SKILL.md 文件结构

每个 skill 是 `skills/{skill_name}/` 目录，包含 `SKILL.md.enc`（加密）和可选的 `references/`、`templates/`、`tools/`、`scripts/` 子目录。

`.skill_meta.json` 标记 `{"version": 2, "encrypted": false}`，但实际文件名带 `.enc` 后缀，由 `skill_crypto.decrypt_skill_md` 在运行时解密。

SKILL.md 的典型结构（从 `paper-figure-drawio` 的 placeholder 推断）：

```markdown
# 任务标题

## 任务目标
简短描述本 skill 要完成什么。

## 执行步骤
1. 读取 XXX.md
2. 检查 YYY
3. 生成 ZZZ 文件
4. 运行自检脚本
5. 更新索引

## 产物要求
- 必须产出：figures/xxx.pdf
- 二级文件：figures/latex_includes.tex
```

### 4.2 $ARGUMENTS 占位符

`_load_skill_prompt(skill_name, arguments, extra_params)` 把 SKILL.md 中的 `$ARGUMENTS` 替换为用户输入。例如「一句话生成项目」中，用户输入「做一个待办事项 Web 应用」，则 dev-requirement 的 prompt 中 `$ARGUMENTS` 会被替换为这句话。

### 4.3 工作区上下文传递

每个工作流有独立工作区 `WORKSPACES_DIR/{workflow_id}/`，所有 skill 共享这个目录。上下文通过两种机制传递：

**机制 1：CLAUDE.md 文件**

`_generate_claude_md(workspace, title, template, params)` 在工作区根目录生成 `CLAUDE.md`，Claude Code CLI 自动读取作为项目上下文。内容包含：

```markdown
# {title}

## 模板
grad_project

## 参数
- project_type: fullstack   # 项目类型，影响 dev-code 的必需文件检查
- AUTO_PROCEED: true         # 是否自动继续
- HUMAN_CHECKPOINT: true     # 是否启用人工检查点

## 工作区文件
- REQUIREMENT.md (3.2KB)
- DESIGN.md (5.1KB)
- code/backend/main.py (2.8KB)
...

## 上下文摘要
（_build_context_summary 生成，最多 12000 字符）
```

`_inject_once(claude_md, marker, content)` 幂等地把新内容追加到 CLAUDE.md，避免重复注入。

**机制 2：context_summary 参数**

`_build_context_summary(workspace, files, max_chars=12000)` 读取关键文件（md/tex/bib）的内容摘要，作为 `context_summary` 参数传给 `run_skill`，拼接在 prompt 末尾。

### 4.4 项目类型检测

`_detect_grad_project_type(workspace)` 从 CLAUDE.md 的 params 段读 `project_type`：

- 默认值：`fullstack`
- 可选值：`fullstack` / `frontend_only` / `backend_only` / `cli` / `script`

这影响 dev-code 步骤的必需文件检查（`_required_companions_for`）：
- fullstack：需要 `code/backend/main.py` + `code/frontend/` + `RUN.md`
- frontend_only：只需要 `code/` 下有主入口 + `RUN.md`
- 纯 CLI/脚本：只需要 `code/` 下有主入口 + `RUN.md`

### 4.5 健康检查与自动恢复

每个步骤完成后做两层健康检查：

**层 1：主产物大小**

`_min_size_for(skill_name, primary_output)` 返回该 skill 主产物的最低字节阈值（默认 100 字节，docx 模式下 markdown 产物用更合理的下限）。主产物小于阈值则判定失败。

**层 2：二级文件齐全**

`_check_step_companions(workspace, skill_name)` 检查 `_required_companions_for` 返回的文件列表是否都存在且大于 50 字节（防空文件占位）。

**自动恢复：CLAUDE.md 压缩**

`_compress_claude_md(workspace)` 在检测到 Claude 输出被截断（空工具调用）时触发：
1. 图片描述截断为摘要（每张图最多 100 字）
2. 文档原文截断（每个文档最多 500 字）
3. 删除重复的规则段落

典型场景：paper-figure 步骤上下文累积到 110K tokens，压缩后恢复正常。

### 4.6 检查点机制

```python
async def wait_checkpoint(workflow_id, timeout=600) -> dict:
    """等待用户确认检查点，超时 10 分钟自动确认继续。"""
```

实现要点：
- 用 `_checkpoint_events[workflow_id] = asyncio.Event()` 实现同步等待
- 用户通过 `POST /api/workflows/{wf_id}/checkpoint` 提交响应，写入 `_checkpoint_responses[workflow_id]` 并 `event.set()`
- 超时后自动确认继续，避免流程卡死
- `resolve_checkpoint(workflow_id, response)` 把用户反馈通过 `_inject_once` 注入到 CLAUDE.md

---

## 五、关键路径与文件

### 5.1 目录布局

```
Modex-MH-Agent/
├── resources/app/
│   ├── backend/
│   │   ├── main.py                  # FastAPI 入口，含 monkey-patch 与 anthropic_proxy
│   │   ├── config.pyc               # 配置（端口、路径）
│   │   ├── db/schema.sql            # SQLite 表结构
│   │   ├── services/
│   │   │   ├── workflow_engine.cp311-win_amd64.pyd   # 工作流引擎
│   │   │   ├── claude_runner.cp311-win_amd64.pyd     # Claude CLI 调用
│   │   │   ├── llm_client.cp311-win_amd64.pyd        # LLM 客户端
│   │   │   ├── state_store.cp311-win_amd64.pyd       # 状态存储
│   │   │   ├── skill_crypto.cp311-win_amd64.pyd      # SKILL.md 解密
│   │   │   ├── project_server.pyc                    # 预览服务管理
│   │   │   └── prompts/                              # 非加密 prompt 模板
│   │   ├── routers/
│   │   │   ├── workflows.cp311-win_amd64.pyd         # 工作流 REST API
│   │   │   ├── checkpoints.cp311-win_amd64.pyd       # 检查点 API
│   │   │   ├── ws.cp311-win_amd64.pyd                # WebSocket
│   │   │   └── project_preview.pyc                   # 预览服务 API
│   │   └── models/schemas.pyc                        # Pydantic 模型
│   ├── skills/                                       # 100+ skill 目录
│   │   ├── dev-requirement/SKILL.md.enc
│   │   ├── dev-design/SKILL.md.enc
│   │   ├── dev-code/SKILL.md.enc
│   │   ├── dev-code-backend/SKILL.md.enc
│   │   ├── dev-code-frontend/SKILL.md.enc
│   │   ├── dev-report/SKILL.md.enc
│   │   ├── dev-selfcheck/SKILL.md.enc
│   │   └── ...
│   └── tools/
│       ├── reviewer_client.py
│       ├── scholar_fetch.py
│       └── humanities_review.py
├── runtime/
│   ├── python/python.exe             # 内嵌 Python 3.11.9
│   ├── node/.../claude.exe           # Claude Code CLI 二进制
│   └── git/bin/bash.exe              # Git Bash（Claude Code 必需）
└── Data/workspaces/{workflow_id}/    # 工作区（运行时创建）
    ├── CLAUDE.md
    ├── REQUIREMENT.md                # dev-requirement 产出
    ├── DESIGN.md                     # dev-design 产出
    ├── RUN.md                        # dev-code 产出
    └── code/
        ├── backend/main.py
        └── frontend/
```

### 5.2 关键常量（运行时反射获取）

```python
SKILLS_DIR     = resources/app/skills
WORKSPACES_DIR = Data/workspaces
TOOLS_DIR      = resources/app/tools
CLAUDE_BIN     = runtime/node/node_modules/@anthropic-ai/claude-code/bin/claude.exe
RUNTIME_PYTHON = runtime/python/python.exe
REVIEWER_SCRIPT = resources/app/tools/reviewer_client.py
```

---

## 六、REST API 接口

`routers/workflows.pyd` 提供的端点（前缀 `/api/workflows`）：

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/` | 创建工作流（body: `{template, title, params, enable_checkpoints}`） |
| GET | `/` | 列出所有工作流 |
| GET | `/{wf_id}` | 获取工作流详情 |
| POST | `/{wf_id}/start` | 启动工作流 |
| POST | `/{wf_id}/pause` | 暂停 |
| POST | `/{wf_id}/resume` | 恢复 |
| POST | `/{wf_id}/restart` | 完全重置，重新执行所有步骤 |
| POST | `/{wf_id}/step/{skill_name}/rerun` | 重新执行单个步骤 |
| DELETE | `/{wf_id}` | 删除 |
| GET | `/{wf_id}/logs?limit=500` | 获取历史日志 |
| POST | `/{wf_id}/checkpoint` | 提交检查点响应 |
| GET | `/{wf_id}/export` | 导出为 zip |
| POST | `/import` | 从 zip 导入 |

WebSocket 端点 `/ws` 用于实时推送日志和事件。

---

## 七、可借鉴的设计模式

### 7.1 工作区隔离

每个工作流独立目录，skill 之间通过文件系统共享状态。优点：
- skill 之间解耦，只需约定文件名
- 支持断点续跑（重启后扫描工作区文件即可恢复上下文）
- 易于导出/导入（打包整个目录）

### 7.2 CLAUDE.md 作为上下文载体

把项目元数据、参数、工作区文件清单、上下文摘要写进一个 markdown 文件，LLM 自动读取。优点：
- LLM 友好（markdown 格式自然）
- 人类可读可编辑
- 支持幂等追加（`_inject_once`）

### 7.3 检查点暂停/恢复

用 `asyncio.Event` 实现轻量级同步等待，超时自动继续。适合「需要人工审核但又不能无限卡死」的场景。

### 7.4 健康检查分层

- 主产物大小检查（防 LLM 摸鱼输出空文件）
- 二级文件齐全检查（防 LLM 漏掉关键文件）
- 上下文压缩恢复（防 prompt 超限导致输出截断）

### 7.5 格式转换代理

通过本地 HTTP 代理把 Anthropic API 转换为 OpenAI 兼容协议，使 Claude Code CLI 能调用任意 OpenAI 兼容后端（DeepSeek、Qwen、Moonshot 等）。这种解耦让前端 agent 框架与后端 LLM 解耦。

---

## 八、局限性与改进方向

| 局限 | 改进方向 |
|---|---|
| 依赖 Claude Code CLI 子进程，启动慢、调试难 | 直接用 LLM API + tool calling 实现 agent 循环 |
| SKILL.md 加密，无法自定义 | 改用明文 markdown，支持用户自定义 |
| 工作流模板硬编码在 Cython 模块中 | 改用 YAML/JSON 配置文件 |
| 项目类型检测依赖 CLAUDE.md 文本解析 | 改用结构化配置文件（如 project.json） |
| 健康检查只看文件大小，不看内容 | 增加语法检查、import 检查、运行测试 |
| 上下文压缩是粗粒度截断 | 改用 LLM 摘要 + 向量检索 |
| 单 LLM 角色，无多 agent 协作 | 引入 reviewer/architect/coder 多角色 |

这些改进方向将在独立智能体应用中落地实现。
