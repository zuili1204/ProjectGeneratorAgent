# ProjectGeneratorAgent

> 一句话生成项目的独立智能体：用户输入自然语言需求，自动产出「需求文档 + 设计文档 + 完整代码 + 自检报告」。
>
> <br />

## 快速开始

```bash
# 1. 安装依赖
cd ProjectGeneratorAgent
pip install -r requirements.txt

# 2. 配置 LLM API Key
python -m agent.cli config set llm_api_key sk-xxxxxxxxxxxxxxxx

# 3. 一句话生成项目
python -m agent.cli run "做一个带用户登录的待办事项 Web 应用，前后端分离"

# 4. 按提示在检查点确认
python -m agent.cli approve {workflow_id}

# 5. 查看产出
ls workspaces/{workflow_id}/code/
```

## 主要特性

- **一句话到项目**：自然语言需求 → 4 步流水线（需求分析 → 系统设计 → 编码实现 → 自测验证）
- **工具调用驱动**：基于 LLM function calling（write\_file / read\_file / list\_files / run\_command），让模型自己决定写哪些文件
- **检查点机制**：每步产出后可暂停等待用户审核，支持打回重做与反馈注入
- **多层健康检查**：主产物大小 + 二级文件齐全 + 代码语法检查（Python `compile()` / JS 括号匹配 / HTML 标签闭合）
- **工作区隔离**：每个工作流一个独立目录，状态以 `state.json` 持久化，无 DB 锁问题
- **两种运行形态**：CLI 单进程 + FastAPI 服务（带 WebSocket 实时日志）
- **任意 LLM 后端**：支持 DeepSeek / Qwen / Moonshot / OpenAI / 本地 vLLM 等所有 OpenAI 兼容后端

## 项目结构

```
ProjectGeneratorAgent/
├── agent/                  # 核心 Python 包
│   ├── config.py           # 配置：路径、LLMConfig、WorkflowConfig
│   ├── llm_client.py       # OpenAI 兼容客户端
│   ├── skill_loader.py     # SKILL.md 加载与渲染
│   ├── workspace.py        # 工作区管理 + 上下文摘要
│   ├── health_check.py     # 三层健康检查
│   ├── agent_loop.py       # LLM 工具循环核心
│   ├── workflow_engine.py  # 工作流引擎
│   ├── cli.py              # CLI 入口（pga 命令）
│   └── server.py           # FastAPI 服务
├── templates/              # 工作流模板（YAML）
│   └── grad_project.yaml   # 「一句话生成项目」模板
├── skills/                 # Skill 指令书（明文 markdown）
│   ├── dev-requirement/    # 需求分析
│   ├── dev-design/         # 系统设计
│   ├── dev-code/           # 编码实现
│   └── dev-selfcheck/      # 自测验证
├── workspaces/             # 工作流产出目录（运行时自动创建）
├── docs/                   # 文档
│   ├── workflow_analysis.md       # Modex-MH-Agent 工作流学习文档
│   └── development_guide.md       # 开发文档（详细）
├── requirements.txt        # Python 依赖
└── README.md               # 本文件
```

## 工作流

「一句话生成项目」模板定义 4 步流水线：

| 顺序 | skill             | 中文名  | 检查点      | 产出                    |
| -- | ----------------- | ---- | -------- | --------------------- |
| 1  | `dev-requirement` | 需求分析 | approve  | `REQUIREMENT.md`      |
| 2  | `dev-design`      | 系统设计 | feedback | `DESIGN.md`           |
| 3  | `dev-code`        | 编码实现 | approve  | `code/` 目录 + `RUN.md` |
| 4  | `dev-selfcheck`   | 自测验证 | 无        | `SELF_CHECK.md`       |

每步完成后可暂停等待用户确认，支持：

- **通过**：继续下一步
- **通过 + 反馈**：反馈注入上下文后继续
- **打回**：暂停工作流，等待重跑

## CLI 命令

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

## 配置

配置优先级（从高到低）：

1. 环境变量：`LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` 等
2. 用户配置文件：`~/.project_generator/config.json`（通过 `pga config set` 写入）
3. 代码内默认值

常见 LLM 后端配置：

| 后端           | base\_url                                           | model             |
| ------------ | --------------------------------------------------- | ----------------- |
| DeepSeek（默认） | `https://api.deepseek.com/v1`                       | `deepseek-chat`   |
| Qwen         | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus`       |
| Moonshot     | `https://api.moonshot.cn/v1`                        | `moonshot-v1-32k` |
| OpenAI       | `https://api.openai.com/v1`                         | `gpt-4o`          |
| 本地 vLLM      | `http://localhost:8000/v1`                          | 自定义               |

## REST API

启动服务：

```bash
python -m agent.server --host 127.0.0.1 --port 8000
```

主要端点：

| 方法   | 路径                               | 说明      |
| ---- | -------------------------------- | ------- |
| POST | `/api/workflows`                 | 创建工作流   |
| POST | `/api/workflows/{id}/start`      | 启动工作流   |
| GET  | `/api/workflows`                 | 列出工作流   |
| GET  | `/api/workflows/{id}`            | 查看详情    |
| POST | `/api/workflows/{id}/checkpoint` | 提交检查点响应 |
| WS   | `/ws/workflows/{id}`             | 实时日志    |

完整 API 文档见 [docs/development\_guide.md](docs/development_guide.md#9-rest-api-参考)。

## 文档

- [开发文档](docs/development_guide.md) — 架构设计、模块详解、扩展方法、部署指南
- [工作流学习文档](docs/workflow_analysis.md) — Modex-MH-Agent 工作流分析与设计思路来源

## 依赖

| 包         | 用途                                    |
| --------- | ------------------------------------- |
| `openai`  | LLM 客户端（OpenAI 兼容 API + tool calling） |
| `pyyaml`  | 模板 YAML 解析                            |
| `rich`    | CLI 美化输出（可选，未装时自动降级）                  |
| `fastapi` | REST API 服务（可选）                       |
| `uvicorn` | ASGI 服务器（可选）                          |

## 许可证

仅供学习与研究使用。
