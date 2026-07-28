---
name: dev-review
version: 1.4.0
description: Use when code/ has been generated and an independent review against REQUIREMENT.md and DESIGN.md is needed before self-check — produces REVIEW.md via diff-based review (git diff base..head) dispatched to an isolated subagent to avoid self-review blind spots; for frontend projects also reviews UI design-system compliance (token consistency, typography pairing, icon family, visual hierarchy, anti-patterns)
inputs: [$ARGUMENTS]
outputs: [REVIEW.md]
depends_on: [REQUIREMENT.md, DESIGN.md, code/RUN.md]
optional_inputs: [DESIGN_SYSTEM.md]
est_tokens: 4000
est_iters: 12
---

# Code Review (dev-review)

## Overview

**Core principle:** Review, don't fix. Act as an independent reviewer comparing generated code against requirements and design. Every finding must be locatable (file + line). Diff-based review preferred over full scan.

## Objective

As an optional step of the "one-sentence-to-project" workflow (typically inserted between `dev-code` and `dev-selfcheck`), review the code under `code/` from an **independent reviewer perspective** against `REQUIREMENT.md` and `DESIGN.md`, and produce `REVIEW.md`. This step only reviews — it does not fix code or rewrite the project. Findings are handed to downstream `dev-selfcheck` for targeted fixes.

> **v1.1 change**: upgraded to an isolated subagent dispatch model. Adapted from superpowers SDD two-stage review (Stage1 spec compliance + Stage2 code quality). The controller (the dev-review main loop) should dispatch an independent subagent via the `dispatch_subagent` tool to perform the review. The subagent only reads `code/` + `REQUIREMENT.md` + `DESIGN.md` and does NOT inherit dev-code's session history — avoiding the "reviewing your own work" cognitive blind spot.

> **v1.2 change**: upgraded to diff-based review. Prefer reviewing `git diff <base>..<head>` (the change from the baseline commit at this step's start to the current HEAD) over a full scan of `code/`. Supports incremental re-review: after a rerun, only review the fix_base..head incremental change. Falls back to a full scan when git is unavailable (mark "non-diff review" in REVIEW.md). Adapted from superpowers git integration and branch lifecycle.

> **v1.4 change**: added a UI design-system compliance dimension. For frontend projects (fullstack / frontend_only / pure HTML+JS), the reviewer now also checks whether the code consumes `DESIGN_SYSTEM.md` tokens consistently — color tokens (no hardcoded hex drift), typography pairing (heading/body not mixed), spacing rhythm (4/8dp tokens), icon family unity (one set, consistent stroke-width), visual hierarchy (size/spacing/contrast, not color alone), and anti-pattern hits from `DESIGN_SYSTEM.md` §6. This dimension catches design drift at review time before dev-selfcheck enforces it as a gate.

## Role

- You are an **independent reviewer**, not the author. Do not rewrite code, do not fill missing files — only review.
- **Prefer dispatching a subagent via `dispatch_subagent` to perform the review**: the subagent sees only task_brief + context_files (`REQUIREMENT.md`, `DESIGN.md`, files under `code/`), not dev-code's session history, ensuring an independent perspective.
- If `dispatch_subagent` is unavailable (no LLM injected), degrade to a same-LLM different-prompt weakened review (mark "non-isolated-subagent review" in REVIEW.md).
- Reviewer and author use the same LLM but **different perspectives**: the author pursues "it runs", the reviewer pursues "consistent with requirements/design and free of obvious defects".
- Findings must be specific to file path and line number (or code snippet) — no vague generalities.

## Inputs

- `$ARGUMENTS`: the user's original request (reference only)
- Existing workspace files (MUST read `REQUIREMENT.md`, `DESIGN.md`; scan the entire `code/` directory)

## Pre-checks

Before formal review, complete the following checks. If any fails, terminate with a reason and do not produce an empty report:

1. **REQUIREMENT.md existence**: use `read_file` to read `REQUIREMENT.md`. If missing or empty, terminate immediately with "REQUIREMENT.md missing, run dev-requirement first" and do NOT call `write_file`.
2. **DESIGN.md existence**: use `read_file` to read `DESIGN.md`. If missing or empty, terminate with "DESIGN.md missing, run dev-design first".
3. **code/ directory existence**: use `list_files` to scan the workspace root and confirm `code/` exists and contains code files. If missing or empty, terminate with "code/ missing or has no code, run dev-code first".
4. **project_type parsing**: parse `project_type` from `REQUIREMENT.md` as the basis for selecting the review checklist. If missing, infer from the `code/` directory structure and explicitly note the assumption in the report.
5. **Diff baseline detection (v1.2)**: use `run_command` to run `git rev-parse HEAD` and `git log --oneline -5` to confirm the workspace has git history. If it does, record the current HEAD as the diff head; the baseline is the commit at the start of the dev-code step (read from `_ledger.md`'s `base_commit` field, or take the commit before dev-code from `HEAD~N`). If no git (`git rev-parse` fails), mark "full-scan mode" and explicitly note "non-diff review: git unavailable" in REVIEW.md. Rerun case (incremental re-review): base is the fix commit from the previous review round.

## Review Dimensions

Review proceeds along four dimensions (the fourth applies to frontend projects only). Each is scored independently (pass / warning / fail), then aggregated into an overall conclusion:

### Dimension 1: Requirement Coverage

Against the **P0 / P1 functional requirements** in `REQUIREMENT.md`, check one by one whether `code/` has a corresponding implementation:

- Every P0 item MUST be locatable to specific code (file + function/route/command). Missing one P0 item = "fail".
- Every P1 item should be locatable; missing items are recorded as "warning" and listed in the report.
- P2 coverage is not mandatory, but if implemented, note it.
- Identify "in the code but not in the requirements" features (over-implementation) and record as "warning".

### Dimension 2: Design Consistency

Against `DESIGN.md`'s **directory structure, module breakdown, interface/route/command design, data model**, check whether the code is consistent with the design:

- Is the directory structure consistent with DESIGN.md's tree (minor differences allowed, but entry filename and config file location MUST align)?
- Are API paths / methods / params consistent with DESIGN.md's interface table?
- Are data model fields consistent with DESIGN.md's ER diagram / table structure (field name, type, constraint)?
- Are command params / subcommand structure (cli) or IO format (script) consistent with DESIGN.md?
- Deviations from the design MUST be listed one by one, marked as "intentional improvement" or "suspected deviation".

### Dimension 3: Potential Defects

From the reviewer's experience, scan the code for the following categories (not required to be exhaustive, but record what you find):

- **Security defects**: hardcoded keys, SQL injection, unescaped user input, dangerous command execution (`os.system(untrusted)`), overly permissive CORS.
- **Resource path issues**: pure frontend projects using `fetch` to load local JSON, absolute resource paths (`/assets/`).
- **Dependency issues**: `import`ed packages not declared in `requirements.txt` / `package.json`; declared but unused deps; version conflicts or alpha/beta versions.
- **Entry issues**: non-standard entry filename (should be `main.py` but written as `app.py`); the entry file referenced by `RUN.md` startup command doesn't exist; startup command not executable (only "just open index.html").
- **Runtime risks**: uncaught exceptions, unhandled nulls, circular references, deadlock risks, infinite-loop risks.
- **Maintainability**: overlong functions (> 80 lines), duplicated code, magic numbers, complex logic without comments.

### Dimension 4: UI Design-System Compliance (v1.4, frontend projects only)

> Skipped (mark N/A) for `cli` / `script` / `backend_only` projects with no UI.
> Cross-references `DESIGN_SYSTEM.md` (the token source of truth from dev-design v1.3.0) and `skills/dev-code/references/token-implementation.md` for the consumption rules.

Against `DESIGN_SYSTEM.md`'s tokens and anti-patterns, check whether the frontend code consumes them consistently:

- **Color token consistency**: are colors routed through `var(--*)` / Tailwind token classes, with no hardcoded hex drift in components? (A bare hex in a component that should use `var(--primary)` is a "warning"; a widespread pattern of ignoring tokens is a "fail".)
- **Typography pairing**: is the heading/body font pairing from DESIGN_SYSTEM.md §3 actually used? Heading font used for headings, body font for body — not mixed arbitrarily. Fonts loaded via the `@import`, not system defaults.
- **Spacing rhythm**: does padding/margin/gap follow the 4/8dp token scale from DESIGN_SYSTEM.md §4? Arbitrary px values (e.g. `padding: 13px`) are flagged as "warning".
- **Icon family unity**: are all icons from one family (Lucide / Heroicons) with consistent stroke-width? Mixed icon families or emoji-as-structural-icons is a "warning" (dev-selfcheck will fail it as CRITICAL).
- **Visual hierarchy**: is hierarchy established via size / spacing / contrast — not color alone? Status indicators relying solely on color (a red dot with no text/icon) are flagged.
- **Anti-pattern hits**: does the code hit any anti-pattern listed in DESIGN_SYSTEM.md §6 (e.g. a finance project using AI purple-pink gradients, a healthcare project using high-saturation red)? A hit is a "warning" or "fail" depending on severity.
- **Token file integrity**: does `tokens.css` exist and match DESIGN_SYSTEM.md §2–§5? A missing or divergent `tokens.css` is a "fail".

Findings here are design-time drift signals — they point dev-selfcheck at where the UI gate will likely fail.

## Execution Steps

Execute the following 10 steps in order:

1. **Step 1: immediately write the `REVIEW.md` skeleton with `write_file`**. Write to the root, containing the four-dimension checklist template (Dimension 4 marked N/A for non-frontend projects), each item marked "pending review". This step MUST NOT be skipped or deferred.
2. **Read requirements & design**: use `read_file` to read `REQUIREMENT.md` and `DESIGN.md`, extracting the P0/P1 feature list, directory structure, interface table, data model. **For frontend projects (v1.4)**: also use `read_file` to read `DESIGN_SYSTEM.md` if it exists, extracting the color/typography/spacing tokens and the anti-pattern list (§6) as the UI compliance baseline.
3. **Get the change scope (diff review, v1.2)**:
   - Prefer `run_command` to run `git diff <base>..HEAD -- code/` to get the change patch produced by dev-code (base inferred from `_ledger.md`'s base_commit field or git log).
   - Also run `git diff --stat <base>..HEAD` to get the changed file list as the review scope.
   - If dev-code ran for the first time (no base), base is the init commit; the diff is the full code (equivalent to a full scan but via the git channel).
   - **Git-unavailable fallback**: use `list_files` to recursively scan `code/` and build a full file list; mark "non-diff review: git unavailable" in REVIEW.md.
   - Use `read_file` to read the full content of key files touched by the diff (the diff alone is not enough — context is needed to judge design consistency).
4. **Requirement coverage review**: check P0/P1 one by one, recording coverage (implemented / partial / missing / over-implemented). Coverage checking still requires the full code (the diff only shows additions, but coverage requires checking whether something is implemented).
5. **Design consistency review**: against DESIGN.md's structured design, record deviations. Focus on whether the directories / interfaces / data models newly added in the diff align with the design.
6. **Potential defects review**: **focus on the newly added/modified code in the diff**, scan by defect category, record findings (file + line/fragment + category + severity). The advantage of diff review: only review what actually changed in this step, not re-review unchanged parts.
7. **UI design-system compliance review (v1.4, frontend projects only)**: against `DESIGN_SYSTEM.md`'s tokens and §6 anti-patterns, review the frontend code in the diff for Dimension 4 — color token consistency (no hardcoded hex drift), typography pairing usage, spacing rhythm (4/8dp), icon family unity, visual hierarchy (not color alone), and anti-pattern hits. Use `run_command` to grep the diff for bare hex / arbitrary px as evidence. Mark N/A and skip for non-frontend projects.
8. **Incremental re-review (rerun case)**: if this step is a rerun (the previous round produced REVIEW.md), only review the fix_base..HEAD incremental change. Do not re-record issues that passed in the previous round; only mark "whether the previous blocker is fixed".
9. **Aggregate scoring**: give each dimension a "pass / warning / fail" with a one-sentence rationale; give an overall conclusion (recommend proceeding to dev-selfcheck / recommend reworking dev-code first).
10. **Update REVIEW.md**: use `write_file` to overwrite the complete `REVIEW.md`, then run the post-check.

## Post-checks

Run a self-check before and after the final `write_file` of `REVIEW.md`. Missing items must be filled before delivery:

- Pre-write check (content completeness):
  - [ ] REVIEW.md has the four-dimension sections (requirement coverage / design consistency / potential defects / UI design-system compliance — Dimension 4 marked N/A for non-frontend projects)
  - [ ] Every P0 feature has a clear conclusion (implemented / partial / missing + location)
  - [ ] Design deviations are listed one by one (file + deviation point + intentional or not)
  - [ ] Potential defects are grouped by category, each with file path and severity
  - [ ] **For frontend projects, Dimension 4 findings are listed** (token consistency / typography / spacing / icons / hierarchy / anti-patterns), each locatable to a file
  - [ ] Includes an overall conclusion and next-step recommendation
- Post-write check (on-disk consistency):
  - [ ] Re-read `REVIEW.md` with `read_file`, confirm section order matches the fixed template
  - [ ] Confirm no "Hard Constraints" violations (see below)
  - On any miss: go back to the relevant step, fill the gap, and `write_file` (overwrite) again.

## Hard Constraints (Red Lines — violation requires rewrite)

- Step 1 MUST use `write_file` to write the `REVIEW.md` skeleton. It MUST NOT be skipped or deferred to the end of the flow.
- **This step is FORBIDDEN from using `write_file` to modify any code file under `code/`.** The reviewer only reviews, never fixes; fixes are left to dev-selfcheck. Violating this is an overreach of authority.
- Every finding MUST be locatable (file path + line number or code snippet). Vague statements like "code quality is mediocre" / "suggest optimizing" are FORBIDDEN.
- A missing P0 feature implementation MUST be marked "fail" — it MUST NOT be downgraded to "warning" or ignored.
- Do NOT fabricate requirements or design items not present in REQUIREMENT.md / DESIGN.md to "pad" coverage.

## Recommendations (encouraged, not mandatory)

- Sort findings by severity: blocker → major → minor → nit.
- Give a "suggested fix direction" for each blocker (one sentence is enough; do not write full fix code).
- If the overall conclusion is "recommend reworking dev-code first", explicitly list the P0 gaps that must be reworked.
- The review may quote original snippets from REQUIREMENT.md / DESIGN.md as a comparison basis.

## Engineering Conventions

### Review Checklist by Project Type

| Project type | Coverage focus | Consistency focus | UI compliance focus (v1.4) |
| --- | --- | --- | --- |
| `fullstack` | Are P0 endpoints all routed? Are DB tables all created? Is auth implemented? | API path/method/params match DESIGN.md table; table structure matches ER diagram | Frontend consumes DESIGN_SYSTEM.md tokens; no bare hex; typography/spacing/icon family consistent |
| `frontend_only` | Are P0 pages all componentized? Are interactions implemented? Does state management cover them? | Page routes match route table; component tree matches design; storage scheme matches design | Same as fullstack frontend checks; anti-patterns from DESIGN_SYSTEM.md §6 not hit |
| `backend_only` | Are P0 endpoints all implemented? Is the data model landed? | API table matches design; layering matches design | N/A (no UI) |
| `cli` | Are P0 subcommands all implemented? Does arg parsing cover them? | Subcommand structure matches DESIGN.md; arg table matches design; exit code convention matches | N/A (no UI) |
| `script` | Is the P0 processing flow implemented? Does the IO format match? | Processing flow matches DESIGN.md flowchart; IO format matches design | N/A (no UI) |

### Severity Definitions

- **blocker**: P0 feature unimplemented / security hole / startup command not executable → MUST be fixed before delivery.
- **major**: P1 feature unimplemented / significant design deviation / missing dependency → recommended fix.
- **minor**: P2 unimplemented / code style issues / missing comments → deferrable.
- **nit**: naming suggestions / micro-optimizations → ignorable.

### REVIEW.md Fixed Template

The report MUST strictly follow this section order. Section titles must not be swapped or omitted:

1. **Review Summary**: project type, review scope (file count / types), review time, **review mode (diff review / full scan) + diff base..head**, overall conclusion (pass / conditional pass / fail).
2. **Requirement Coverage**: P0/P1 item-by-item check table (feature / status / location file / notes), over-implementation list.
3. **Design Consistency**: directory structure comparison, interface/route/command comparison, data model comparison, deviation list (each with file + deviation point + intentional or not).
4. **Potential Defects**: grouped by blocker / major / minor / nit, each with file path + line/fragment + problem description + suggested fix direction.
5. **UI Design-System Compliance (frontend projects only, v1.4)**: token consistency / typography pairing / spacing rhythm / icon family / visual hierarchy / anti-pattern hits, each locatable to a file; paste grep evidence for bare-hex / arbitrary-px scans. Mark N/A for non-frontend projects.
6. **Dimension Scoring**: each of the four dimensions scored (pass / warning / fail) + a one-sentence rationale.
7. **Overall Conclusion & Recommendation**: whether to proceed to dev-selfcheck; if reworking dev-code is recommended, list the blocker checklist that must be fixed.

## Tools & Error Handling

- `list_files`: scan `code/` to build a code file list (fallback when git unavailable); confirm the directory and code files exist during pre-checks.
- `read_file`: read `REQUIREMENT.md`, `DESIGN.md`, `_ledger.md` (for base_commit), code files under `code/`, `code/RUN.md`; re-read the on-disk `REVIEW.md` during post-check.
- `write_file`: **only** used to write `REVIEW.md` (initial skeleton + final overwrite). Modifying any file under `code/` is FORBIDDEN.
- `run_command`: **v1.2 addition**, run `git diff <base>..HEAD -- code/` and `git diff --stat <base>..HEAD` to get the change scope; run `git rev-parse HEAD` / `git log --oneline` to detect the baseline. On git failure, fall back to full scan; do not block.
- `dispatch_subagent`: dispatch an independent subagent to perform the review (v1.1); the subagent uses the non-recursive tool set.
- This step does NOT do syntax checks or runtime verification (that is dev-selfcheck's job), but running `git diff` via `run_command` is allowed.
- Error handling:
  - If `REQUIREMENT.md` / `DESIGN.md` / `code/` is missing: terminate, write no report, return a prompt.
  - If `code/` has no code files: terminate, prompt to run dev-code first.
  - If git is unavailable (`git rev-parse` fails): fall back to full-scan mode; mark "non-diff review" in REVIEW.md.
  - If a post-check finds a red-line violation: go back to the relevant step, fix, and re-`write_file`. Never ship a defective report.

## Key Constraints

- The reviewer only reviews, never fixes code; fixes are left to dev-selfcheck.
- Every finding MUST be locatable (file + line/fragment); vague statements are FORBIDDEN.
- A missing P0 implementation MUST be marked "fail"; no downgrading.
- REVIEW.md MUST be produced — even if the code has no problems at all, a report must be written (a full-pass also requires a complete record).
- Step 1 MUST write the REVIEW.md skeleton first; it MUST NOT be skipped.
- The review focuses on four dimensions (requirement coverage / design consistency / potential defects / UI design-system compliance — Dimension 4 is N/A for non-frontend projects) and does NOT do syntax checks (syntax is left to dev-selfcheck).
- **Output language: Chinese (中文).** Although this skill instruction is in English, ALL generated project artifacts — REVIEW.md content and any other deliverable — MUST be written in Chinese. Do not use emoji.
