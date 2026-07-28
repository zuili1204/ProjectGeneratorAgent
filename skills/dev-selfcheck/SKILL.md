---
name: dev-selfcheck
version: 1.0.0
inputs: [$ARGUMENTS]
outputs: [SELF_CHECK.md]
depends_on: [code/RUN.md, REQUIREMENT.md, DESIGN.md]
est_tokens: 4000
est_iters: 12
---

# 自测验证 (dev-selfcheck)

## 任务目标

对 `code/` 目录下的全部代码做语法检查、一致性检查与运行时验证，修复发现的问题，并产出 `SELF_CHECK.md` 报告。作为「一句话生成项目」工作流的第四步，承接 `dev-code` 产物，确保交付的项目可直接运行。本步骤只做检查与修复，不新增功能、不重写项目。

## 输入

- `$ARGUMENTS`：用户原始需求（仅作参考）
- 工作区已有文件（必读 `REQUIREMENT.md`、`DESIGN.md`、`code/RUN.md`，扫描整个 `code/` 目录）

## 前置校验

进入正式自测前必须完成以下校验，任一不通过则终止并给出原因，不产出空报告：

1. **code/ 目录存在性检查**：用 `list_files` 扫描工作区根目录，确认 `code/` 目录存在。若不存在，立即终止，提示「code/ 目录缺失，请先执行 dev-code 步骤」，不调用 `write_file`。
2. **代码文件存在性检查**：用 `list_files` 递归扫描 `code/` 目录，确认其中存在代码文件（`.py` / `.js` / `.ts` / `.jsx` / `.tsx` / `.html` / `.css` 等）。若目录为空或仅含文档，终止并提示「code/ 目录无代码文件，请先执行 dev-code 步骤」。
3. **RUN.md 存在性检查**：用 `read_file` 读取 `code/RUN.md`。若文件不存在，终止并提示「RUN.md 缺失，请先执行 dev-code 步骤补全启动说明」。
4. **项目类型解析**：从 `REQUIREMENT.md` 中解析 `project_type`（`fullstack` / `frontend_only` / `cli` / `script` / `backend_only`），作为后续按类型选择检查清单的依据。若缺失，按 `code/` 目录结构推断并在报告中显式标注假设。

## 执行步骤

按顺序执行以下 8 步，发现问题即时修复并记录：

1. **第一步：立即用 `write_file` 写出 `SELF_CHECK.md` 初版**（框架）。写入根目录，包含完整检查项清单模板（语法 / 标签 / 路径 / 依赖 / 启动命令 / 运行时验证），每项标记为「待检查」。此步不可跳过、不可后置。
2. **扫描文件清单**：用 `list_files` 递归扫描 `code/` 目录下所有文件，建立待检查文件清单（按扩展名分类：`.py` / `.js` / `.ts` / `.jsx` / `.tsx` / `.html` / `.css` / 配置文件）。
3. **Python 语法检查**：对每个 `.py` 文件用 `run_command` 执行 `python -m py_compile <file>` 做 `compile()` 语法检查，记录通过 / 失败结果。
4. **前端语法与标签检查**：对每个 `.js` / `.ts` / `.jsx` / `.tsx` 文件做括号匹配检查（可用 `run_command` 执行 `node --check` 或人工核对 `()` / `[]` / `{}` 配对）；对每个 `.html` 文件做标签闭合检查（含自闭合标签）。
5. **运行时验证**（按项目类型对号入座，参见「工程规范 - 运行时验证检查项」）：fetch 检查、资源路径检查、模块导入检查、入口文件检查。
6. **RUN.md 启动命令检查**：核对 `RUN.md` 中的启动命令是否可执行、引用的入口文件是否实际存在、命令与文件结构是否匹配。
7. **修复问题**：对前序步骤发现的 FAIL 项，用 `write_file` 修复对应代码文件（只修有问题的文件，不重写整个项目），同步记录修复动作。
8. **更新 SELF_CHECK.md**：用 `write_file` 覆盖写入最终的 `SELF_CHECK.md`，填入每项检查结果（PASS / FAIL + 原因）、已修复问题、未修复问题，完成后置自检。

## 后置自检

在最后一次 `write_file` 写入 `SELF_CHECK.md` 前后各做一次自检，缺失项必须补全后再交付：

- 写入前自检（内容完整性）：
  - [ ] SELF_CHECK.md 包含检查项清单（语法 / 标签 / 路径 / 依赖 / 启动命令 / 运行时验证六类齐全）
  - [ ] 每项检查有明确结果（PASS 或 FAIL + 原因），无「待检查」遗留
  - [ ] 已修复问题逐条记录（文件路径 + 问题描述 + 修复方式）
  - [ ] 未修复问题（如有）说明原因与影响
  - [ ] 包含总结段（整体结论 / 残留风险点）
- 写入后自检（落盘一致性）：
  - [ ] 用 `read_file` 重新读取 `SELF_CHECK.md`，确认章节顺序与固定模板一致
  - [ ] 确认所有 FAIL 项均已修复或在「未修复问题」中有交代
  - [ ] 确认无「强红线」违例（见下一节）
  - 任一缺失：回到对应步骤补全后再次 `write_file` 覆盖写入。

## 指令约束

### 强红线（违反必须重写）

- 第一步必须用 `write_file` 写出 `SELF_CHECK.md` 初版（框架），不可跳过、不可后置到流程末尾。
- 所有 `.py` 文件必须通过 `compile()` 语法检查（`python -m py_compile`）；存在语法错误必须修复至通过。
- 所有 `.js` / `.ts` / `.jsx` / `.tsx` 文件括号必须匹配（`()` / `[]` / `{}` 配对闭合）。
- 所有 `.html` 文件标签必须闭合（含自闭合标签），不得有未闭合的 `<div>` / `<script>` / `<body>` 等。
- 纯前端项目（`frontend_only` / 纯 HTML+JS）禁止使用 `fetch` / `XMLHttpRequest` 加载本地 JSON 文件；发现必须修复为 `<script>` 标签加载 JS 数据文件，或将数据内联到 HTML / JS。
- `RUN.md` 必须包含可执行的启动命令（如 `pip install -r requirements.txt && python main.py`、`python -m http.server`），不得仅写「直接打开 index.html」。
- 所有资源路径必须为相对路径（`./` 开头或不以 `/` 开头），不得出现 `/assets/` 这类绝对路径。
- 发现问题必须修复，不能只报告不修复；修复后需在 `SELF_CHECK.md` 中记录。

### 建议项（鼓励但不强制）

- 检查代码注释是否充分（关键函数 / 复杂逻辑有说明）。
- 检查错误处理是否完善（异常捕获、边界条件、空值处理）。
- 检查依赖版本是否兼容（`requirements.txt` / `package.json` 版本号是否冲突或缺失）。

## 工程规范

### 各项目类型的检查清单

按 `project_type` 对号入座，执行对应检查项：

| 项目类型 | 检查清单 |
| --- | --- |
| `fullstack` | 后端模块导入检查（`cd code/backend && python -c "import main"`）、前端 `package.json` 完整性（依赖 / scripts 齐全）、API 路由与 `REQUIREMENT.md` 功能列表对齐 |
| `frontend_only` | HTML 资源路径检查（`src` / `href` 为相对路径）、JS `fetch` 检查（禁止加载本地 JSON）、CSS 引用检查（`<link>` 引用的文件实际存在） |
| `cli` | `--help` 命令可执行（`python main.py --help` 或 `node main.js --help`）、参数解析正确（必填 / 可选 / 默认值） |
| `script` | `python main.py` 可运行、输入输出格式正确（输入来源 / 输出形式符合 `DESIGN.md`） |

> 备注：`backend_only` 参照 `fullstack` 的后端部分裁剪，前端检查项省略。

### 运行时验证检查项

- **fetch 检查**：扫描所有 `.js` / `.ts` / `.jsx` / `.tsx` 文件，若发现 `fetch(` 加载本地 `.json` 文件，标记为 FAIL 并修复（改为 `<script>` 标签加载 JS 数据文件，或将数据内联到 HTML / JS）。
- **路径检查**：HTML 中所有 `src` 和 `href` 必须为相对路径（`./` 开头或不以 `/` 开头）；出现绝对路径标记为 FAIL 并修复。
- **模块导入检查**：Python 后端的 `import` 语句引用的模块必须在同级目录或已安装的包中（可用 `python -c "import <module>"` 验证）；引用不存在的模块标记为 FAIL 并修复。
- **入口文件检查**：`RUN.md` 中引用的入口文件（如 `main.py` / `index.html` / `main.js`）必须实际存在于 `code/` 目录；缺失标记为 FAIL 并补全或修正引用。

### SELF_CHECK.md 固定模板

报告必须严格按以下章节顺序组织，章节标题不得调换或省略：

1. **检查概要**：项目类型、检查范围（文件数 / 类型）、检查工具、整体结论（通过 / 有条件通过 / 不通过）。
2. **检查项清单**：列出六类检查项（语法 / 标签 / 路径 / 依赖 / 启动命令 / 运行时验证），每类说明检查范围与方法。
3. **每项结果**：逐项给出 PASS / FAIL + 原因（FAIL 需说明具体文件与问题）。
4. **已修复问题**：逐条记录修复（文件路径 + 问题描述 + 修复方式）。
5. **未修复问题**：列出未修复项（如有），说明原因与影响、后续建议。
6. **总结**：整体可运行性结论、残留风险点、是否建议进入交付。

## 工具与异常

- `list_files`：扫描 `code/` 目录，建立待检查文件清单；前置校验时确认目录与代码文件存在。
- `read_file`：读取 `code/` 下的代码文件、`RUN.md`、`REQUIREMENT.md`、`DESIGN.md`；后置自检时重新读取落盘的 `SELF_CHECK.md`。
- `write_file`：第一步写出 `SELF_CHECK.md` 初版（框架）；修复有问题的代码文件；最终覆盖写入完整的 `SELF_CHECK.md`。
- `run_command`：执行语法检查（`python -m py_compile <file>`、`node --check <file>`）与运行时验证（`python -c "import main"`、`python main.py --help`）；单次调用超时 60 秒，超时或失败不影响整体流程，仅将该次检查标记为 FAIL 并记录原因。
- 异常处理：
  - 若 `code/` 目录缺失或无代码文件：终止，不写报告，返回提示。
  - 若 `RUN.md` 缺失：终止，提示先执行 dev-code 补全。
  - 若 `run_command` 超时或失败：标记对应检查项为 FAIL 并记录原因，不阻塞后续检查。
  - 若后置自检发现强红线违例：回到对应步骤修复后重新 `write_file`，禁止带病交付。

## 关键约束

- `SELF_CHECK.md` 必须产出，即使代码完全没问题也要写报告（全 PASS 亦需完整记录）。
- 第一步必须先写 `SELF_CHECK.md` 框架，不可跳过。
- 发现问题必须修复，不能只报告不修复；修复后同步更新报告。
- 不要重写整个项目，只修有问题的文件；不新增功能。
- 所有资源路径用相对路径，不得出现绝对路径。
- 纯前端项目禁止 `fetch` 加载本地 JSON，必须改为 `<script>` 加载。
- `RUN.md` 必须包含可执行的启动命令，不得仅写「直接打开 index.html」。
- 检查代码的工具调用控制在合理次数内，优先保证 `SELF_CHECK.md` 已写出且完整。
- 全文使用中文，不使用 emoji。
