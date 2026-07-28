# ProjectGeneratorAgent 测试套件

## 目录结构

```
tests/
├── __init__.py          测试套件入口说明
├── test_smoke.py        非依赖 LLM 的冒烟测试（模板/Skill/when/安全沙箱/golden 自洽）
├── regress_skill.py     SKILL 回归脚本（按 golden 用例跑单步并断言产物）
└── golden/              黄金用例集
    ├── todo_app/        fullstack 全栈典型场景
    ├── calculator/      frontend_only 纯前端（验证 fetch 禁令）
    ├── file_rename/     cli 命令行工具
    └── crawler/         script Python 脚本
```

## 运行

### 1. 冒烟测试（不调 LLM，CI 友好）

```bash
# 不依赖 pytest
python -m tests.test_smoke

# 或用 pytest
python -m pytest tests/test_smoke.py -v
```

覆盖：
- 模板可加载、含合法 sub_steps、`when` 字段被解析
- Skill 可加载、front matter 元数据可解析
- `_eval_when` 条件分支求值（`==` / `!=` / `in` / `not in` / `and` / `or`）
- 安全沙箱 `validate_command` 拦截危险命令（`rm -rf` / `format` / `curl | sh` 等）
- golden 用例 fixture 自洽（`case.yaml` 可解析、引用的 template/skill 存在）

### 2. SKILL 回归（调 LLM 实跑）

```bash
# 列出所有 golden 用例
python -m tests.regress_skill --list

# dry-run：只校验 fixture 引用合法，不调 LLM
python -m tests.regress_skill dev-requirement --case todo_app --dry-run
python -m tests.regress_skill dev-requirement --all --dry-run

# 实跑：调用 LLM 真实执行单步，对产物做断言
python -m tests.regress_skill dev-requirement --case todo_app
```

断言规则见各 `case.yaml` 的 `steps[].assertions`，包含：
- 主产物存在与最小体积
- 必需文件清单（如 fullstack 必须有 `code/backend/main.py` + `code/frontend/package.json`）
- 必需 markdown 章节（如 REQUIREMENT.md 必含「项目类型」「技术栈」节）
- `project_type` 字段值匹配
- 目录结构 tree 图无 `...` 占位
- RUN.md 含可执行启动命令（非「直接打开 index.html」）
- 纯前端项目无 `fetch` 加载本地 JSON

## 黄金用例说明

每个用例目录下有一份 `case.yaml`，字段：

| 字段 | 说明 |
| --- | --- |
| `name` | 用例名 |
| `description` | 用途说明 |
| `requirement` | 一句话需求 |
| `project_type` | 期望项目类型 |
| `template` | 使用的模板 key |
| `steps` | 各 skill 的回归步骤定义 |

`steps[]` 单步字段：

| 字段 | 说明 |
| --- | --- |
| `skill` | 要回归的 skill 名 |
| `expected_outputs` | 期望产出的文件列表 |
| `min_size` | 主产物最小字节数 |
| `required_sections` | 文件 → 必需章节清单 |
| `required_files` | 必须存在的文件清单 |
| `assertions` | 特殊断言（`project_type_field` / `no_placeholder_in_tree` / `run_md_has_executable_cmd` / `no_fetch_local_json` 等） |

## 添加新用例

1. 在 `tests/golden/` 下新建目录（如 `blog_system/`）。
2. 写一份 `case.yaml`，参照现有用例。
3. 先跑 `python -m tests.regress_skill <skill> --case blog_system --dry-run` 确认 fixture 自洽。
4. 再跑实跑验证断言规则有效。

## 关于 LLM 非确定性

LLM 输出非确定，同一用例多次跑结果可能不同。回归脚本断言的是「结构性约束」（文件存在、章节齐全、字段匹配），而非「逐字匹配」。若需更严的语义评估，建议另起 LLM-as-judge 评分脚本（记录分数变化趋势，而非 pass/fail）。
