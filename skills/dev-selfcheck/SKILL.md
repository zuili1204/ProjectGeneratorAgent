---
name: dev-selfcheck
version: 1.4.0
description: Use when code/ and RUN.md exist and the generated project must be verified runnable before delivery — runs syntax checks, executes the test suite, validates runtime behavior, adds a UI quality gate (token discipline, contrast, accessibility, responsive) for frontend projects, fixes found issues, and produces SELF_CHECK.md with fresh verification evidence
inputs: [$ARGUMENTS]
outputs: [SELF_CHECK.md]
depends_on: [code/RUN.md, REQUIREMENT.md, DESIGN.md]
est_tokens: 5000
est_iters: 17
---

# Self-Check & Verification (dev-selfcheck)

## Overview

**Core principle:** Evidence before claims, always. The project is not "done" until tests pass with fresh output — not "files exist and syntax is OK".

## Objective

Run **syntax checks, test execution, consistency checks, and runtime verification** on all code under `code/`, fix found issues, and produce a `SELF_CHECK.md` report. As the fourth step of the "one-sentence-to-project" workflow, it takes over the `dev-code` output and ensures the delivered project is **verified runnable**. This step only checks and fixes — it does not add features or rewrite the project.

> **v1.1 change**: introduced the verification-before-completion gate. "File exists + syntax passes" is no longer accepted as proof of completion — the test suite MUST be executed and the passing evidence pasted. Adapted from superpowers `NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE`.

> **v1.3 change**: added a UI quality gate. For frontend projects (fullstack / frontend_only / pure HTML+JS), an additional check dimension is now enforced — token discipline (no bare hex / arbitrary px, fonts via @import), icon discipline (no emoji as structural icons), color contrast (≥ 4.5:1), touch targets (≥ 44px), accessibility (alt / aria-label / focus ring / reduced-motion), and responsive (viewport meta + breakpoints). See `references/ui-pre-delivery-checklist.md` for the full gate. This gate is additive to the existing seven check categories and reuses the same evidence-before-claims principle (grep outputs MUST be pasted, not "looks fine").

> **v1.4 change**: enforced SELF_CHECK.md completeness. The health check now rejects SELF_CHECK.md files that contain more than 3 residual markers (`pending` / `待填充` / `待完成` / `待检查`). Writing the skeleton in Step 1 and then ending without filling it in is NO LONGER accepted — every check item MUST have a concrete PASS / FAIL + evidence result.

## Inputs

- `$ARGUMENTS`: the user's original request (reference only)
- Existing workspace files (MUST read `REQUIREMENT.md`, `DESIGN.md`, `code/RUN.md`; scan the entire `code/` directory)

## Pre-checks

Before formal self-check, complete the following checks. If any fails, terminate with a reason and do not produce an empty report:

1. **code/ directory existence**: use `list_files` to scan the workspace root and confirm `code/` exists. If missing, terminate immediately with "code/ missing, run dev-code first" and do NOT call `write_file`.
2. **Code file existence**: use `list_files` to recursively scan `code/` and confirm it contains code files (`.py` / `.js` / `.ts` / `.jsx` / `.tsx` / `.html` / `.css` etc.). If the directory is empty or contains only docs, terminate with "code/ has no code files, run dev-code first".
3. **RUN.md existence**: use `read_file` to read `code/RUN.md`. If missing, terminate with "RUN.md missing, run dev-code first to complete the startup guide".
4. **project_type parsing**: parse `project_type` from `REQUIREMENT.md` (`fullstack` / `frontend_only` / `cli` / `script` / `backend_only`) as the basis for selecting the per-type checklist. If missing, infer from the `code/` directory structure and explicitly note the assumption in the report.

## Execution Steps

Execute the following 10 steps in order. Fix issues as found and record them:

1. **Step 1: immediately write the `SELF_CHECK.md` skeleton with `write_file`**. Write to the root, containing the complete checklist template (syntax / **test execution** / tags / paths / deps / startup command / runtime verification), each item marked "pending check". This step MUST NOT be skipped or deferred.
2. **Scan file list**: use `list_files` to recursively scan all files under `code/`, building a to-check file list (classified by extension: `.py` / `.js` / `.ts` / `.jsx` / `.tsx` / `.html` / `.css` / config).
3. **Python syntax check**: for each `.py` file, use `run_command` to run `python -m py_compile <file>` for a `compile()` syntax check; record pass / fail.
4. **Frontend syntax & tag check**: for each `.js` / `.ts` / `.jsx` / `.tsx` file, do a bracket-matching check (use `run_command` to run `node --check` or manually verify `()` / `[]` / `{}` pairing); for each `.html` file, do a tag-closing check (including self-closing tags).
5. **Test directory check (red line)**: use `list_files` to confirm that `code/tests/` or `code/backend/tests/` etc. exists. **If not, immediately use `write_file` to create `code/tests/__init__.py` + `code/tests/test_main.py` skeleton** (at least one smoke test: `def test_imports(): import main` or `def test_health(): ...`), and add `pytest>=7.0` to `requirements.txt`. A missing test directory is a FAIL.
6. **Test execution (red line, verification gate)**: use `run_command` to run `python -m pytest code/tests/ -v --tb=short 2>&1` (or `npm test --prefix code/frontend 2>&1`). **MUST paste the exit_code and an output summary.** On test failure, fix until `exit_code: 0` before advancing. A self-check report with no test-passing evidence is considered incomplete.
7. **Runtime verification** (per project type — see "Engineering Conventions - Runtime Verification Items"):
   - `fullstack` / `backend_only`: start the backend in the background `python -m uvicorn code.backend.main:app --port 8765`, sleep 3s, call `/health` and verify 200
   - `cli` / `script`: run `python code/main.py --help` and verify exit_code 0
   - `frontend_only`: skip (needs a browser)
8. **UI quality gate (v1.3, frontend projects only)**: if `project_type` is `fullstack` or `frontend_only` (or pure HTML+JS), run the UI checks defined in `references/ui-pre-delivery-checklist.md`. This includes:
   - **Token discipline**: use `run_command` to grep for bare hex (`#[0-9a-fA-F]{3,8}`) and arbitrary px in spacing across component files (exclude `tokens.css`); confirm `tokens.css` exists and is imported; confirm fonts are loaded via `@import` (not system defaults).
   - **Icon discipline**: scan for emoji used as structural UI icons (navigation / settings / system-control buttons).
   - **Color contrast**: LLM-judge the key foreground/background token pairs from `tokens.css` against WCAG AA (≥ 4.5:1 body, ≥ 3:1 large text), citing actual token values.
   - **Touch targets**: scan interactive elements for min 44×44px on mobile.
   - **Accessibility**: grep `img` for `alt`, icon-only `<button>` for `aria-label`, forms for label association, CSS for a visible `:focus`/`:focus-visible` ring and `@media (prefers-reduced-motion)`.
   - **Responsive**: confirm viewport meta tag and mobile-first breakpoints (375/768/1024/1440).
   - Each grep-based check MUST paste the actual command + output (hit count / sample lines); LLM-judged checks MUST cite the inspected token values / snippets. Mark N/A for `cli` / `script` / `backend_only` projects with no UI.
9. **RUN.md startup command check**: verify that the startup commands in `RUN.md` are executable, that the referenced entry files actually exist, and that the commands match the file structure.
10. **Fix issues**: for FAIL items found in previous steps, use `write_file` to fix the corresponding code files (only fix problem files; do not rewrite the whole project) and record the fix actions. **After fixing, you MUST re-run the relevant tests** (e.g. if you changed main.py, re-run `pytest code/tests/test_main.py`; if you fixed a token violation, re-run the grep to confirm the bare hex is gone).
11. **Update SELF_CHECK.md**: use `write_file` to overwrite the final `SELF_CHECK.md`, filling in each check result (PASS / FAIL + reason + **verification evidence**), fixed issues, unfixed issues, then run the post-check.

## Post-checks

Run a self-check before and after the final `write_file` of `SELF_CHECK.md`. Missing items must be filled before delivery:

- Pre-write check (content completeness):
  - [ ] SELF_CHECK.md has the checklist (all seven categories: syntax / **test execution** / tags / paths / deps / startup command / runtime verification)
  - [ ] **For frontend projects, the UI quality gate section is present** (token discipline / icon discipline / contrast / touch targets / accessibility / responsive), each with PASS / FAIL / N/A + evidence
  - [ ] Each check has a clear result (PASS or FAIL + reason + **verification evidence**); no "pending check" left over
  - [ ] **The test-execution item MUST include the actual `run_command` output (exit_code + summary); "should pass" is NOT allowed**
  - [ ] **UI grep checks MUST paste the actual grep command + output (hit count / sample lines); "looks fine" is NOT allowed**
  - [ ] Fixed issues are recorded one by one (file path + problem + fix method + **re-run test evidence after fix**)
  - [ ] Unfixed issues (if any) explain the reason and impact
  - [ ] Includes a summary section (overall conclusion / residual risks)
- Post-write check (on-disk consistency):
  - [ ] Re-read `SELF_CHECK.md` with `read_file`, confirm section order matches the fixed template
  - [ ] **Scan for residual markers: `pending` / `待填充` / `待完成` / `待检查` — if more than 3 found, the health check will REJECT the report; fill them in before ending**
  - [ ] Confirm all FAIL items are fixed or accounted for under "Unfixed Issues"
  - [ ] Confirm no "Hard Constraints" violations (see below)
  - On any miss: go back to the relevant step, fill the gap, and `write_file` (overwrite) again.

## Hard Constraints (Red Lines — violation requires rewrite)

- Step 1 MUST use `write_file` to write the `SELF_CHECK.md` skeleton. It MUST NOT be skipped or deferred to the end of the flow.
- **The `code/tests/` directory MUST exist and contain at least one `test_*.py` file** (or `*.test.js`). If not, create a skeleton test in this step.
- **The test suite MUST be executed and evidence of exit_code 0 pasted** (`pytest` or `npm test`). Skipping test execution or only saying "tests pass" without output is NOT allowed.
- All `.py` files MUST pass the `compile()` syntax check (`python -m py_compile`); syntax errors MUST be fixed until passing.
- All `.js` / `.ts` / `.jsx` / `.tsx` files MUST have matched brackets (`()` / `[]` / `{}` closed).
- All `.html` files MUST have closed tags (including self-closing); unclosed `<div>` / `<script>` / `<body>` etc. are FORBIDDEN.
- Pure frontend projects (`frontend_only` / pure HTML+JS) MUST NOT use `fetch` / `XMLHttpRequest` to load local JSON files; if found, MUST fix to load JS data files via `<script>` tags, or inline data into HTML / JS.
- `RUN.md` MUST contain executable startup commands (e.g. `pip install -r requirements.txt && python main.py`, `python -m http.server`); "just open index.html" alone is NOT allowed.
- All resource paths MUST be relative (`./` prefix or not starting with `/`); absolute paths like `/assets/` are FORBIDDEN.
- Found issues MUST be fixed, not only reported; after fixing, record in `SELF_CHECK.md` and **re-run relevant tests to verify the fix introduced no regression**.
- **UI quality gate (v1.3, frontend projects)**: for `fullstack` / `frontend_only` / pure HTML+JS, the UI checks in `references/ui-pre-delivery-checklist.md` MUST be run. A CRITICAL FAIL (bare hex in components, missing `tokens.css`, emoji as structural icons, system-default fonts) blocks delivery until fixed. grep-based checks MUST paste actual command output — "no issues found" without a grep is NOT allowed.
- **SELF_CHECK.md completeness (v1.4, red line)**: the final `SELF_CHECK.md` MUST NOT contain more than 3 residual markers (`pending` / `待填充` / `待完成` / `待检查`). Writing the Step 1 skeleton and ending without filling in each check item is FORBIDDEN — the health check will reject the report and trigger a retry. Every check item MUST have a concrete result: PASS (+ evidence) or FAIL (+ reason + fix or "unfixed" note).

### Verification Before Completion

Adapted from superpowers:

```
NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE
```

- Before claiming "self-check complete", you MUST paste in SELF_CHECK.md the actual output (including exit_code) of the test command run via `run_command` in this step.
- Hypothetical statements like "should be fine", "probably passes", "ran before" count as unverified.
- After a fix, you MUST re-run the tests and paste new evidence; old output MUST NOT be referenced.
- Runtime verification (backend /health 200 / CLI --help 0) also requires pasted evidence.

## Recommendations (encouraged, not mandatory)

- Check whether code comments are sufficient (key functions / complex logic explained).
- Check whether error handling is sound (exception catching, boundary conditions, null handling).
- Check whether dependency versions are compatible (version numbers in `requirements.txt` / `package.json` — conflicts or missing).

## Engineering Conventions

### Checklist by Project Type

Match `project_type` and run the corresponding checks:

| Project type | Checklist |
| --- | --- |
| `fullstack` | backend module import check (`cd code/backend && python -c "import main"`), frontend `package.json` completeness (deps / scripts), API routes aligned with REQUIREMENT.md feature list |
| `frontend_only` | HTML resource path check (`src` / `href` are relative), JS `fetch` check (local JSON loading forbidden), CSS reference check (`<link>`-ed files actually exist) |
| `cli` | `--help` is executable (`python main.py --help` or `node main.js --help`), arg parsing correct (required / optional / default) |
| `script` | `python main.py` runs, IO format correct (input source / output form per `DESIGN.md`) |

> Note: `backend_only` refers to the backend portion of `fullstack`, trimmed; frontend checks are omitted.

### Runtime Verification Items

- **fetch check**: scan all `.js` / `.ts` / `.jsx` / `.tsx` files; if `fetch(` loading a local `.json` file is found, mark FAIL and fix (change to load a JS data file via `<script>` tag, or inline data into HTML / JS).
- **Path check**: all `src` and `href` in HTML MUST be relative (`./` prefix or not starting with `/`); absolute paths are marked FAIL and fixed.
- **Module import check**: Python backend `import` statements must reference modules in the same directory or installed packages (verifiable via `python -c "import <module>"`); referencing non-existent modules is marked FAIL and fixed.
- **Entry file check**: the entry file referenced in `RUN.md` (e.g. `main.py` / `index.html` / `main.js`) MUST actually exist under `code/`; if missing, mark FAIL and fill it or correct the reference.

### SELF_CHECK.md Fixed Template

The report MUST strictly follow this section order. Section titles must not be swapped or omitted:

1. **Check Summary**: project type, check scope (file count / types), check tools, overall conclusion (pass / conditional pass / fail).
2. **Checklist**: list the seven check categories (syntax / **test execution** / tags / paths / deps / startup command / runtime verification), each describing the scope and method. For frontend projects, also list the UI quality gate categories (token discipline / icon discipline / contrast / touch targets / accessibility / responsive).
3. **Per-item Results**: give PASS / FAIL + reason + **verification evidence** for each item (FAIL must specify the file and problem; the test-execution item MUST paste run_command output).
4. **Test Execution Evidence**: a standalone section pasting the full command + exit_code + output summary (last 10-20 lines) of `pytest` / `npm test`.
5. **UI Quality Gate (frontend projects only)**: paste the grep commands + outputs for token/icon/accessibility checks; cite the token values judged for contrast; mark N/A for non-frontend projects. See `references/ui-pre-delivery-checklist.md` for the compact checklist to embed here.
6. **Fixed Issues**: record fixes one by one (file path + problem + fix method + **re-run test evidence after fix**).
7. **Unfixed Issues**: list unfixed items (if any), explaining the reason, impact, and follow-up recommendation.
8. **Summary**: overall runnability conclusion, residual risks, whether delivery is recommended.

## Tools & Error Handling

- `list_files`: scan `code/` to build the to-check file list; confirm the directory and code files exist during pre-checks.
- `read_file`: read code files under `code/`, `RUN.md`, `REQUIREMENT.md`, `DESIGN.md`; re-read the on-disk `SELF_CHECK.md` during post-check.
- `write_file`: step 1 writes the `SELF_CHECK.md` skeleton; fix problem code files; finally overwrite the complete `SELF_CHECK.md`.
- `run_command`: run syntax checks (`python -m py_compile <file>`, `node --check <file>`) and runtime verification (`python -c "import main"`, `python main.py --help`); single-call timeout 60s. A timeout or failure does not block the overall flow — it only marks that check FAIL and records the reason.
- Error handling:
  - If `code/` is missing or has no code files: terminate, write no report, return a prompt.
  - If `RUN.md` is missing: terminate, prompt to run dev-code to complete it first.
  - If `run_command` times out or fails: mark the corresponding check FAIL and record the reason; do not block subsequent checks.
  - If a post-check finds a red-line violation: go back to the relevant step, fix, and re-`write_file`. Never ship a defective report.

## Key Constraints

- `SELF_CHECK.md` MUST be produced — even if the code has no problems at all, a report must be written (a full-PASS also requires a complete record).
- Step 1 MUST write the `SELF_CHECK.md` skeleton first; it MUST NOT be skipped.
- Found issues MUST be fixed, not only reported; after fixing, update the report synchronously.
- Do NOT rewrite the whole project — only fix problem files; do not add features.
- All resource paths are relative; absolute paths are FORBIDDEN.
- Pure frontend projects MUST NOT use `fetch` to load local JSON; MUST change to `<script>` loading.
- `RUN.md` MUST contain executable startup commands; "just open index.html" alone is NOT allowed.
- Keep the number of tool calls for checks within a reasonable range; prioritize ensuring `SELF_CHECK.md` is written and complete.
- **Output language: Chinese (中文).** Although this skill instruction is in English, ALL generated project artifacts — SELF_CHECK.md content, code comments, error messages, and any other deliverable — MUST be written in Chinese. Do not use emoji.
