---
name: dev-code
version: 1.0.0
inputs: [$ARGUMENTS]
outputs: [code/RUN.md]
depends_on: [REQUIREMENT.md, DESIGN.md]
est_tokens: 8000
est_iters: 20
---

# 编码实现 (dev-code)

## 任务目标

基于 `REQUIREMENT.md` 与 `DESIGN.md`，在工作区 `code/` 目录下生成完整可运行的项目代码，并写出 `RUN.md` 启动说明。

## 输入

- `$ARGUMENTS`：用户原始需求
- 工作区已有文件（必读 `REQUIREMENT.md` 和 `DESIGN.md`）

## 前置校验

1. 用 `read_file` 检查 `REQUIREMENT.md` 是否存在，缺失则记录错误并终止
2. 用 `read_file` 检查 `DESIGN.md` 是否存在，缺失则记录错误并终止
3. 从 `REQUIREMENT.md` 解析 `project_type`（fullstack / frontend_only / cli / script），确认目录规范
4. 从 `DESIGN.md` 确认技术栈（前端框架 / 后端框架 / 数据库 / 编程语言），作为编码依据

## 执行步骤

1. 读取 `DESIGN.md`，确认目录结构（精确到文件级）、技术栈、模块划分
2. 按设计创建文件，每个文件用一次 `write_file` 工具调用
3. 优先级：入口文件 → 核心模块 → 工具类 → 配置文件 → RUN.md
4. **在写完入口文件后就写** **`RUN.md`**，不要留到最后
5. 不要省略代码（不要写「// 此处省略」），每个文件要完整可运行
6. 所有 `.py` 文件写完后，用 `run_command` 执行 `python -m py_compile` 做语法校验
7. 所有 `.js`/`.ts` 文件写完后，做括号匹配自检（人工核对或用 `node --check`）
8. 所有 `.html` 文件写完后，做标签闭合自检
9. 核对清单：入口文件存在、`RUN.md` 含启动命令、路径均为 `code/` 相对路径
10. 校验不通过时，自动定位问题文件并修正，不把问题留给用户

## 后置自检

写入完成后，在结束前逐项确认：
- `RUN.md` 已写出且包含可执行启动命令
- 入口文件存在且大于 100 字节
- 所有 `.py` 文件通过 `compile()` 语法检查
- 所有 `.js`/`.ts` 文件括号匹配
- 所有 `.html` 文件标签闭合
- 所有资源路径为相对路径（不以 `/` 开头）
不通过则立即修复，不把问题留给下游。

## 目录结构要求

按项目类型（从 `REQUIREMENT.md` 读取）组织代码：

### fullstack

```
code/
├── backend/
│   ├── main.py           # FastAPI/Flask 入口
│   ├── requirements.txt
│   └── ...                # 业务模块
├── frontend/
│   ├── package.json
│   ├── index.html
│   └── src/
└── RUN.md
```

### frontend\_only

```
code/
├── package.json
├── index.html
├── src/
└── RUN.md
```

### cli

```
code/
├── main.py               # 或 main.js / main.ts
├── requirements.txt      # 或 package.json
└── RUN.md
```

### script

```
code/
├── main.py
└── RUN.md
```

## 产物要求

- 必须产出：`RUN.md`（在 `code/` 下，描述启动步骤）
- 主入口文件必须存在且大于 100 字节
- fullstack 必须有 `code/backend/main.py` 和 `code/frontend/package.json`
- frontend\_only 必须有 `code/frontend/package.json` 或 `code/package.json`
- 所有 `.py` 文件必须通过 `compile()` 语法检查
- 所有 `.js`/`.ts`/`.jsx`/`.tsx` 文件括号必须匹配
- 所有 `.html` 文件标签必须闭合

## 指令约束

### 强红线（违反必须重写）

- 禁止伪代码或 TODO，每个文件必须完整可运行
- 依赖列表必须完整（`requirements.txt` / `package.json`），禁止遗漏
- 文件路径必须用 `code/` 开头的相对路径（如 `code/backend/main.py`）
- 纯前端项目禁止用 `fetch`/XMLHttpRequest 加载本地 JSON 文件（`file://` 协议下会 CORS 失败）
- `RUN.md` 必须包含可执行的启动命令（不能只写「启动项目」）
- 禁止杜撰不存在的 API 或库函数
- 禁止硬编码密钥、token、密码等敏感信息
- 禁止生成有系统命令执行风险的代码（如 `os.system(untrusted_input)`）

### 建议项（无特殊说明时默认遵循）

- 数据库优先用 SQLite（无需额外安装）
- 前端优先用 Vite + React（启动快、配置少）
- 技术栈选型可由 `DESIGN.md` 覆盖
- 代码注释用中文
- 错误信息用中文

## 工程规范

### 各项目类型默认规范

- **fullstack**：
  - FastAPI 默认开启 CORS（`CORSMiddleware`）
  - 自带 `/health` 健康检查接口
  - 异常统一处理（FastAPI `exception_handler` / Flask `@app.errorhandler`）
  - 前后端分离，前端通过 HTTP API 调用后端

- **frontend\_only**：
  - Vite 项目默认配置端口（5173）、相对路径打包（`base: './'`）
  - 禁止绝对路径资源引用（`/assets/` → `./assets/`）
  - 数据文件用 JS 模块导出（`export const data = {...}`），不用 fetch 加载 JSON
  - SPA 路由用 HashRouter（兼容 `file://` 协议）

- **cli**：
  - 用 argparse / click（Python）或 commander（Node）解析命令行参数
  - 提供 `--help` 帮助信息
  - 退出码：0 成功，1 通用错误，2 参数错误

- **script**：
  - `if __name__ == '__main__':` 入口
  - 用 `logging` 模块记录日志
  - 用 `argparse` 接收参数

### 依赖版本规则

- Python 依赖指定稳定大版本：`fastapi>=0.100.0,<0.110.0`、`pydantic>=2.0,<3.0`
- Node 依赖兼容 LTS 版本：`"react": "^18.2.0"`、`"vite": "^5.0.0"`
- 禁止使用 alpha/beta 版本
- 禁止使用已废弃的库（如 `distutils`）

### RUN.md 固定模板

```markdown
# 启动说明

## 环境要求
- Python >= 3.10 / Node >= 18
- 操作系统：Windows / macOS / Linux

## 依赖安装
\`\`\`bash
cd code
pip install -r requirements.txt   # Python
# 或
npm install                        # Node
\`\`\`

## 启动命令
\`\`\`bash
python main.py
# 或
npm run dev
\`\`\`

## 验证方式
- 访问 http://localhost:8000/health 返回 {"status": "ok"}
- 或执行 `python main.py --help` 显示帮助信息

## 常见问题
- 端口被占用：修改 main.py 中的 PORT 常量
- 依赖安装失败：升级 pip / npm 后重试
```

## 纯前端项目特殊约束（frontend\_only / 纯 HTML+JS）

- **禁止使用 fetch/XMLHttpRequest 加载本地 JSON 文件**（`file://` 协议下会 CORS 失败）
- 数据文件处理方案（按优先级）：
  1. 将数据直接写入 JS 文件（如 `data.js` 中 `window.BlogData = {...}`），用 `<script>` 标签加载
  2. 将数据内联到 HTML 的 `<script>` 标签中
- RUN.md 中**不要写"直接打开 index.html"**，只推荐 HTTP 服务器方式（`python -m http.server`）
- 所有资源路径用相对路径（`./assets/...`），不要用绝对路径（`/assets/...`）

## 工具与异常

### 可用工具

- `read_file`：读取 `REQUIREMENT.md`、`DESIGN.md`、已有代码文件
- `write_file`：写入代码文件和 `RUN.md`
- `list_files`：查看工作区已有文件
- `run_command`：执行语法检查（`python -m py_compile`、`node --check`），单次超时 60 秒

### 异常处理

- `REQUIREMENT.md` 或 `DESIGN.md` 缺失：记录错误并终止，不生成代码
- `run_command` 超时：跳过该项检查，不阻塞流程
- `write_file` 失败：重试一次，仍失败则记录错误
- 目录创建失败：检查权限后重试

## 常见错误（务必避免）

以下是 LLM 在本步骤高频犯的错误，执行时主动规避：

1. **fetch 加载本地 JSON**：纯前端项目用 `fetch('./data.json')` → `file://` 协议 CORS 失败。正确做法：数据写入 `data.js` 用 `export const data = {...}` 或 `window.XxxData = {...}`，`<script src="./data.js">` 加载。
2. **RUN.md 写「直接打开 index.html」**：不可执行。必须写 `python -m http.server 8000` 或 `npm run dev` 这类命令。
3. **绝对资源路径**：`<img src="/assets/logo.png">` → 部署到子路径会 404。必须用相对路径 `./assets/logo.png`。
4. **依赖遗漏**：代码 `import xxx` 但 `requirements.txt`/`package.json` 没声明 → 运行报 ModuleNotFoundError。写完代码后回头核对依赖清单。
5. **伪代码/TODO**：`# TODO: 实现登录` 或 `pass  # 此处省略` → 不可运行。每个函数必须有完整实现。
6. **入口文件命名不规范**：后端入口写成 `app.py` 而非 `main.py` → 健康检查会判失败。必须用 `main.py`（或 `__main__.py`），并在 RUN.md 中引用一致。
7. **硬编码密钥**：`API_KEY = "sk-xxxx"` 直接写源码 → 泄露风险。用环境变量 `os.environ.get("API_KEY")`。
8. **技术栈与 REQUIREMENT.md 不一致**：REQUIREMENT.md 选了 Flask，dev-code 却写了 FastAPI → 下游混乱。严格沿用 REQUIREMENT.md/DESIGN.md 的选型。
9. **HTML 标签未闭合**：`<div>` 没有对应 `</div>` → 浏览器渲染错乱。写完每个 HTML 文件做标签闭合自检。
10. **Python 缩进/中文标点**：混用 tab 和空格、误用中文括号 `（）` → SyntaxError。统一用 4 空格缩进，标点用半角。

## 关键约束

- 代码要能直接运行，不要写伪代码或 TODO
- 依赖列表要完整（`requirements.txt` / `package.json`）
- `RUN.md` 要包含具体的启动命令（如 `pip install -r requirements.txt && python main.py`）
- 文件路径用 `code/` 开头的相对路径（如 `code/backend/main.py`）
- 数据库优先用 SQLite（无需额外安装）
- 前端优先用 Vite + React（启动快、配置少）
