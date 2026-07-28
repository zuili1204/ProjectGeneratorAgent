---
name: dev-code
version: 1.5.0
description: Use when REQUIREMENT.md and DESIGN.md exist and the project code needs to be generated — produces a complete runnable code/ tree with tests and RUN.md, executing the structured task list from DESIGN.md step by step with verification between tasks; for frontend projects also consumes DESIGN_SYSTEM.md tokens and emits tokens.css so components never hardcode raw hex/px values
inputs: [$ARGUMENTS]
outputs: [code/RUN.md, code/tests/]
depends_on: [REQUIREMENT.md, DESIGN.md]
optional_inputs: [DESIGN_SYSTEM.md]
est_tokens: 10000
est_iters: 25
---

# Code Implementation (dev-code)

## Overview

**Core principle:** Generate complete, runnable, tested project code by following the structured task list from DESIGN.md — one Task at a time, with verification between Tasks. No placeholders, no pseudocode.

## Objective

Based on `REQUIREMENT.md` and `DESIGN.md`, generate **complete runnable project code with tests** under the workspace `code/` directory, and write a `RUN.md` startup guide.

> **v1.1 change**: introduced flexible TDD — test artifacts MUST exist and tests MUST pass, but the strict "red before green" order is not enforced. Adapted from superpowers `NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST`, but given the high rewrite cost of generative projects, a **flexible version** is adopted: there MUST be a `code/tests/` directory + at least one test file + tests passing (exit_code 0). dev-selfcheck runs a verification gate to enforce this.

> **v1.2 change**: upgraded to task-driven development. dev-design already produces a structured task list (Task N: Files/Interfaces/Steps) in DESIGN.md. This step **executes strictly in Task list order**: each Task creates files → runs verification → only advances on pass. Between Tasks, run a placeholder scan (TBD/TODO/"similar to Task N"/"// omitted here" are all FORBIDDEN). Adapted from superpowers plan-driven development.

> **v1.4 change**: added design-token consumption. For projects with a frontend (fullstack / frontend_only), dev-code MUST read `DESIGN_SYSTEM.md` (produced by dev-design v1.3.0) and land its tokens as `code/frontend/src/styles/tokens.css` (+ `tailwind.config.js` extension). Frontend components MUST consume tokens via `var(--*)` / Tailwind token classes — bare hex and arbitrary px in components are FORBIDDEN. See `references/token-implementation.md` for the full hard-constraint table, per-tech-stack wiring (React / Vue / pure HTML+JS / server templates), and the multi-page override mechanism.

> **v1.5 change**: (1) no silent fallback — when `DESIGN_SYSTEM.md` is missing, dev-code MUST produce a `DESIGN_SYSTEM_DEGRADATION.md` note and add a prominent warning at the top of `RUN.md`, rather than silently using ad-hoc tokens. (2) Emoji as structural icons is FORBIDDEN — use inline SVG or Unicode geometric symbols instead.

## Inputs

- `$ARGUMENTS`: the user's original request
- Existing workspace files (MUST read `REQUIREMENT.md` and `DESIGN.md`)

## Pre-checks

1. Use `read_file` to check that `REQUIREMENT.md` exists; if missing, record an error and terminate.
2. Use `read_file` to check that `DESIGN.md` exists; if missing, record an error and terminate.
3. Parse `project_type` from `REQUIREMENT.md` (fullstack / frontend_only / cli / script) to confirm the directory convention.
4. Confirm the tech stack from `DESIGN.md` (frontend framework / backend framework / database / language) as the coding basis.
5. **Parse the structured task list from `DESIGN.md`**: locate the "Structured Task List" section and extract each Task's Files / Interfaces / Steps. If DESIGN.md has no Task list (legacy design document), split into 3-8 Tasks by directory structure and note "self-split" in the execution log.
6. **Design-system token check (v1.5, frontend projects only)**: if `project_type` is `fullstack` or `frontend_only`, use `read_file` to check that `DESIGN_SYSTEM.md` exists. If it exists, treat it as the single source of truth for color/typography/spacing/motion tokens and land it as `tokens.css` (see `references/token-implementation.md`). If it is **missing**, this is a **degradation** — you MUST: (a) write `DESIGN_SYSTEM_DEGRADATION.md` to the workspace root explaining the missing design system and the ad-hoc tokens being used; (b) create a minimal `tokens.css` using the `_shared/color-theory.md` and `_shared/typography-pairing.md` fallback baselines with the `--primary` / `--on-primary` naming convention; (c) add a prominent warning at the top of `RUN.md`: "⚠ DESIGN_SYSTEM.md 未由 dev-design 产出，token 为临时回退方案，UI 一致性无法保证。". Do NOT silently fall back without documenting the degradation.

## Execution Steps

**Core principle: execute in Task list order. Within each Task, complete "create files → run verification → only advance on pass".**

1. Read `DESIGN.md`, confirm the directory structure (file-level), tech stack, module breakdown, and **parse the Task list**.
2. **Execute Tasks one by one in order** (do NOT write all files at once):
   - For each Task, use `write_file` to create the files in its Files field (implementation + tests)
   - Within a Task, creation order: write the test file skeleton first (flexible TDD allows impl-then-test, but the test MUST exist), then the implementation
   - **Inter-Task verification**: after completing each Task, use `run_command` to run that Task's verification command (`pytest code/tests/test_<task>.py -v` or `npm test`). **Only advance to the next Task on pass (exit_code 0)**; on failure, fix within that Task until it passes.
   - The first Task MUST be the entry file + smoke test + `RUN.md` (so the project can run); subsequent Tasks stack features on top.
3. **Write `RUN.md` immediately after the first Task (entry file)** — do not leave it to the end.
4. Do NOT omit code (no "// omitted here"). Every file must be complete and runnable.
5. Add `pytest>=7.0` to `requirements.txt` (Python) or `jest` to `package.json` (Node).
6. After all `.py` files are written, use `run_command` to run `python -m py_compile` for syntax checks.
7. After all `.js`/`.ts` files are written, do a bracket-matching self-check (manual or via `node --check`).
8. After all `.html` files are written, do a tag-closing self-check.
9. **Placeholder scan (red line)**: after all files are written, use `list_files` + `read_file` to scan all files under `code/`. The following placeholders are FORBIDDEN (their presence means incomplete and MUST be filled):
   - `TBD` / `TODO` / `FIXME` / `XXX` (todo markers in comments — unless the user explicitly requested a deferred P2 feature, and this MUST be noted in SELF_CHECK)
   - `// omitted here` / `# omitted` / `... omitted ...` (code omission markers)
   - `similar to Task N` / `same as above` / `same as Task N` (lazy copy references — the full code MUST be written out)
   - `pass  # TODO` (empty implementation placeholder)
10. **Run the full test suite**: use `run_command` to run `python -m pytest code/tests/ -v 2>&1` (or `npm test 2>&1`). **Tests MUST pass (exit_code: 0) before this step can end.** On failure, fix the code or tests until passing.
11. Checklist: entry file exists, `RUN.md` has startup commands, `code/tests/` has at least one test file, tests pass, all paths are `code/`-relative, **no placeholders**.
12. On check failure, auto-locate the problem file and fix it — do not leave problems for the user.

## Post-checks

After writing, confirm each item before ending:
- `RUN.md` is written and contains executable startup commands
- Entry file exists and is larger than 100 bytes
- All `.py` files pass `compile()` syntax check
- All `.js`/`.ts` files have matched brackets
- All `.html` files have closed tags
- All resource paths are relative (not starting with `/`)
- **All Tasks in the Task list are executed (no missing Task)**
- **Placeholder scan passes: no TBD/TODO/omitted/similar to Task N under `code/`**
- **Full test suite passes (exit_code 0)**
On any miss, fix immediately — do not leave problems for downstream.

## Directory Structure Requirements

Organize code by project type (read from `REQUIREMENT.md`):

### fullstack

```
code/
├── backend/
│   ├── main.py           # FastAPI/Flask entry
│   ├── requirements.txt
│   └── ...                # business modules
├── frontend/
│   ├── package.json
│   ├── index.html
│   ├── tailwind.config.js # token extension (when Tailwind is used)
│   └── src/
│       ├── styles/
│       │   └── tokens.css # design tokens landed from DESIGN_SYSTEM.md (v1.4)
│       └── ...
├── tests/
│   ├── __init__.py
│   ├── test_main.py       # smoke test: import main
│   └── test_api.py        # /health 200 check
└── RUN.md
```

### frontend_only

```
code/
├── package.json
├── index.html
├── tailwind.config.js     # token extension (when Tailwind is used)
├── src/
│   ├── styles/
│   │   └── tokens.css     # design tokens landed from DESIGN_SYSTEM.md (v1.4)
│   └── ...
├── tests/
│   └── main.test.js       # jest style
└── RUN.md
```

### cli

```
code/
├── main.py               # or main.js / main.ts
├── requirements.txt      # or package.json
├── tests/
│   ├── __init__.py
│   └── test_cli.py        # --help exit 0 check
└── RUN.md
```

### script

```
code/
├── main.py
├── tests/
│   ├── __init__.py
│   └── test_main.py       # smoke test
└── RUN.md
```

## Output Requirements

- MUST produce: `RUN.md` (under `code/`, describing startup steps)
- **MUST produce: a `code/tests/` directory** with at least one `test_*.py` (Python) or `*.test.js` (Node) test file
- **MUST produce: executable tests** — `python -m pytest code/tests/` or `npm test` exits 0
- The main entry file MUST exist and be larger than 100 bytes
- fullstack MUST have `code/backend/main.py` and `code/frontend/package.json`
- frontend_only MUST have `code/frontend/package.json` or `code/package.json`
- All `.py` files MUST pass `compile()` syntax check
- All `.js`/`.ts`/`.jsx`/`.tsx` files MUST have matched brackets
- All `.html` files MUST have closed tags
- `requirements.txt` MUST contain `pytest>=7.0` (Python projects) or `package.json` MUST contain `jest` (Node projects)

## Hard Constraints (Red Lines — violation requires rewrite)

- Pseudocode or TODO is FORBIDDEN. Every file MUST be complete and runnable.
- **MUST execute in the Task list order from DESIGN.md.** After each Task, run verification; only advance on pass. Skipping Tasks or going out of order is FORBIDDEN.
- **Zero tolerance for placeholders**: all files under `code/` MUST NOT contain `TBD` / `TODO` / `FIXME` / `// omitted here` / `similar to Task N` / `same as above` / `pass  # TODO`. Their presence means incomplete and the full implementation MUST be filled in.
- **MUST produce a `code/tests/` directory + at least one test file + evidence of tests passing (exit_code 0).** A dev-code with no test artifacts is considered incomplete.
- The dependency list MUST be complete (`requirements.txt` / `package.json`); omissions are FORBIDDEN. Python projects MUST contain `pytest>=7.0`.
- File paths MUST use `code/`-prefixed relative paths (e.g. `code/backend/main.py`).
- Pure frontend projects MUST NOT use `fetch`/XMLHttpRequest to load local JSON files (fails under `file://` due to CORS).
- `RUN.md` MUST contain executable startup commands (not just "start the project").
- Fabricating non-existent APIs or library functions is FORBIDDEN.
- Hardcoding keys, tokens, passwords, or other sensitive info is FORBIDDEN.
- Generating code with system-command execution risks (e.g. `os.system(untrusted_input)`) is FORBIDDEN.
- **Tests MUST be real and runnable**: `def test_x(): assert True` empty-test placeholders are NOT allowed. Tests MUST actually verify that the entry is importable / an API is callable / the CLI is executable.
- **Design-token consumption (v1.4, frontend projects)**: for `fullstack` / `frontend_only`, frontend components MUST consume tokens via `var(--*)` or Tailwind token classes — bare hex / rgb / hsl values and arbitrary px in padding/margin/gap/radius/shadow/motion are FORBIDDEN inside component files (`.jsx`/`.tsx`/`.vue`/`.css`/`.html` style blocks). Fonts MUST be loaded via the `@import` from `DESIGN_SYSTEM.md` §3, not system defaults. The first frontend Task MUST land `code/frontend/src/styles/tokens.css` (transcribed from `DESIGN_SYSTEM.md`) before any component is written, so all downstream components reference a single source of truth. See `references/token-implementation.md` for the acceptable-exception rule and per-tech-stack wiring.
- **Emoji as structural icons is FORBIDDEN (v1.5)**: do NOT use emoji codepoints (e.g. `🔍` `&#128269;` `⚙` `📝` `🏠`) for navigation, search, settings, or any system-control button. Emoji render inconsistently across OS/browser and violate the UI quality gate. Use inline SVG icons (Lucide / Heroicons style, 24×24 viewBox, `stroke="currentColor"`) or Unicode geometric symbols (☰ ☾ ✓ ✕ →) that render consistently. This applies to ALL generated HTML/JSX/Vue files.

## Recommendations (default unless otherwise noted)

- Prefer SQLite for the database (no extra install needed)
- Prefer Vite + React for the frontend (fast startup, minimal config)
- Tech stack selection may be overridden by `DESIGN.md`
- **Code comments in Chinese (中文)**
- **Error messages in Chinese (中文)**

## Engineering Conventions

### Default Conventions by Project Type

- **fullstack**:
  - FastAPI enables CORS by default (`CORSMiddleware`)
  - Ships a `/health` health-check endpoint
  - Unified exception handling (FastAPI `exception_handler` / Flask `@app.errorhandler`)
  - Frontend-backend separation; the frontend calls the backend via HTTP API

- **frontend_only**:
  - Vite project default port (5173), relative-path bundling (`base: './'`)
  - Absolute resource paths are FORBIDDEN (`/assets/` → `./assets/`)
  - Data files use JS module exports (`export const data = {...}`), not fetch-loaded JSON
  - SPA routing uses HashRouter (compatible with `file://`)

- **cli**:
  - Use argparse / click (Python) or commander (Node) for arg parsing
  - Provide `--help`
  - Exit codes: 0 success, 1 generic error, 2 arg error

- **script**:
  - `if __name__ == '__main__':` entry
  - Use the `logging` module
  - Use `argparse` for params

### Dependency Version Rules

- Python deps pin a stable major version: `fastapi>=0.100.0,<0.110.0`, `pydantic>=2.0,<3.0`
- Node deps compatible with LTS: `"react": "^18.2.0"`, `"vite": "^5.0.0"`
- alpha/beta versions are FORBIDDEN
- Deprecated libraries (e.g. `distutils`) are FORBIDDEN

### RUN.md Fixed Template

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

## Special Constraints for Pure-Frontend Projects (frontend_only / pure HTML+JS)

- **FORBIDDEN to use fetch/XMLHttpRequest to load local JSON files** (fails under `file://` due to CORS)
- Data file handling (by priority):
  1. Write data directly into a JS file (e.g. `data.js` with `window.BlogData = {...}`), loaded via `<script>` tag
  2. Inline data into the HTML `<script>` tag
- RUN.md MUST NOT say "just open index.html" — only recommend an HTTP server approach (`python -m http.server`)
- All resource paths MUST be relative (`./assets/...`), not absolute (`/assets/...`)

## Tools & Error Handling

### Available Tools

- `read_file`: read `REQUIREMENT.md`, `DESIGN.md`, existing code files
- `write_file`: write code files and `RUN.md`
- `list_files`: inspect existing workspace files
- `run_command`: run syntax checks (`python -m py_compile`, `node --check`); single timeout 60s

### Error Handling

- `REQUIREMENT.md` or `DESIGN.md` missing: record an error and terminate; do not generate code
- `run_command` timeout: skip that check; do not block the flow
- `write_file` failure: retry once; if still failing, record an error
- Directory creation failure: check permissions and retry

## Common Mistakes (actively avoid)

These are high-frequency LLM mistakes in this step:

1. **fetch loading local JSON**: pure frontend project uses `fetch('./data.json')` → CORS failure under `file://`. Correct: write data into `data.js` as `export const data = {...}` or `window.XxxData = {...}`, load via `<script src="./data.js">`.
2. **RUN.md says "just open index.html"**: not executable. MUST write `python -m http.server 8000` or `npm run dev`.
3. **Absolute resource paths**: `<img src="/assets/logo.png">` → 404 when deployed to a sub-path. MUST use relative `./assets/logo.png`.
4. **Missing dependencies**: code does `import xxx` but `requirements.txt`/`package.json` doesn't declare it → ModuleNotFoundError at runtime. After writing code, cross-check the dependency list.
5. **Pseudocode/TODO**: `# TODO: implement login` or `pass  # omitted here` → not runnable. Every function MUST have a complete implementation.
6. **Non-standard entry filename**: backend entry written as `app.py` instead of `main.py` → health check fails. MUST use `main.py` (or `__main__.py`) and reference it consistently in RUN.md.
7. **Hardcoded keys**: `API_KEY = "sk-xxxx"` in source → leak risk. Use env vars `os.environ.get("API_KEY")`.
8. **Tech stack inconsistent with REQUIREMENT.md**: REQUIREMENT.md picks Flask but dev-code writes FastAPI → downstream chaos. Strictly follow the REQUIREMENT.md/DESIGN.md selection.
9. **Unclosed HTML tags**: `<div>` without matching `</div>` → browser rendering chaos. Do a tag-closing self-check after each HTML file.
10. **Python indentation / Chinese punctuation**: mixing tabs and spaces, accidentally using Chinese parens `（）` → SyntaxError. Use 4 spaces consistently; use half-width punctuation.
11. **Bare hex / arbitrary px in components (v1.4)**: writing `style={{ color: '#2563eb' }}` or `padding: 13px` directly in a component → tokens drift, no theming, dev-selfcheck fails the UI gate. Correct: land `tokens.css` first, then use `var(--primary)` / Tailwind `text-primary` / `var(--space-4)`. See `references/token-implementation.md`.
12. **System-default fonts**: `font-family: serif` or relying on the browser default → violates DESIGN_SYSTEM.md typography. Correct: load fonts via the `@import` from DESIGN_SYSTEM.md §3 and reference `var(--font-heading)` / `var(--font-body)`.
13. **Two divergent token files**: fullstack project where the Jinja2 templates and the SPA each define their own `tokens.css` → inconsistent UI. Correct: a single `tokens.css` is the source of truth; the server templates and the SPA both import it.

## Key Constraints

- Code MUST run directly — no pseudocode or TODO
- Dependency list MUST be complete (`requirements.txt` / `package.json`)
- `RUN.md` MUST contain concrete startup commands (e.g. `pip install -r requirements.txt && python main.py`)
- File paths use `code/`-prefixed relative paths (e.g. `code/backend/main.py`)
- Prefer SQLite for the database (no extra install needed)
- Prefer Vite + React for the frontend (fast startup, minimal config)
- **Output language: Chinese (中文).** Although this skill instruction is in English, ALL generated project artifacts — code comments, UI text, error messages, RUN.md content, and any other deliverable — MUST be written in Chinese. Do not use emoji.
