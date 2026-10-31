---
name: dev-requirement
version: 1.1.1
description: Use when starting a new project from a one-line user request — decomposes a single-sentence requirement into a structured REQUIREMENT.md that downstream design and coding steps consume
inputs: [$ARGUMENTS]
outputs: [REQUIREMENT.md]
depends_on: []
shared: []
est_tokens: 4000
est_iters: 8
---

# Requirement Analysis (dev-requirement)

## Overview

**Core principle:** Turn a one-line user request into a self-contained, structured requirement document. This step does analysis only — no implementation code.

## Objective

Decompose the user's one-line request into a structured `REQUIREMENT.md`, the first artifact of the "one-sentence-to-project" workflow. Downstream steps (dev-design, dev-code) consume it directly. This step performs requirement analysis only and writes no implementation code.

## Inputs

- `$ARGUMENTS`: the user's one-line request (e.g. "build a todo web app with user login")
- Existing workspace context files (empty on first run; on re-runs use `list_files` to inspect and `read_file` to read an existing REQUIREMENT.md for incremental updates)

## Pre-checks

Before formal analysis, complete the following checks. If any fails, terminate with a reason and do not produce an empty document:

1. **Empty-argument check**: if `$ARGUMENTS` is empty, blank, or punctuation-only, terminate immediately with "requirement description is empty, cannot analyze" and do NOT call `write_file`.
2. **Intent keyword parsing**: identify intent signals from `$ARGUMENTS` to determine project type:
   - Frontend signals: page, website, landing page, H5, form, dashboard
   - Fullstack signals: login, register, user, permission, backend, API, database, CRUD, blog, shop
   - CLI signals: command-line, CLI, scaffold, batch tool, terminal tool
   - Script signals: script, automation, scrape, clean, scheduled task, data processing, export
3. **Ambiguity handling**: if the one-line request cannot unambiguously determine project type (multiple signal categories matched or key signals missing), pick one via "minimal viable assumption" and record it under "Assumptions & Open Items". Do NOT fall back to asking the user.

## Supported Project Types

The `project_type` field must be one of the following four values. This field drives the directory structure and generation strategy of dev-design / dev-code:

- `fullstack`: full-stack web app — frontend pages + backend service + database (e.g. todo app with login, blog system)
- `frontend_only`: pure frontend pages, no standalone backend, includes static sites / interactive pages (e.g. landing page, calculator, showcase page)
- `cli`: command-line tool that completes tasks via terminal interaction (e.g. file batch tool, scaffold)
- `script`: Python script for automation / small tools, no complex interactive UI (e.g. data cleaning script, scheduled scraper)

## Supported Tech Stacks

Select ONLY from the following combinations — do not improvise:

- Frontend framework: `React` / `Vue` / `pure HTML+JS` (for fullstack or frontend_only)
- Backend framework: `FastAPI` / `Flask` / `Node-Express` (for fullstack)
- Database: `SQLite` (lightweight, zero-config, fits prototypes and small-to-medium projects) / `MySQL` (for production-grade, multi-user scenarios)
- Language: `Python` (for cli / script / FastAPI / Flask) / `Node` (for Node-Express backend or pure frontend build chain)

## Execution Steps

Execute the following 10 steps in order. Each step's output feeds into the final `REQUIREMENT.md`:

1. **Parse request & determine project type**: combine the intent keywords from pre-checks, pick a single `project_type` from "Supported Project Types", and state the rationale (which signals were matched).
2. **Tech stack selection**: based on project type and request scope, pick a tech stack combination and give a per-item rationale (consider user need, data volume, multi-user needs, persistence needs).
3. **User roles & scenarios**: list primary user roles (e.g. anonymous visitor, registered user, admin) and describe each role's typical scenarios and main flows.
4. **P0 functional requirements**: list core features that MUST be implemented (indispensable main flows), each as a verb-object phrase (e.g. "user registers an account via email").
5. **P1 functional requirements**: list important features that enhance experience and completeness, to be implemented this iteration.
6. **P2 functional requirements**: list deferrable extension features, mark as non-goals or backlog.
7. **Project-type checklist**: provide the structured checklist matching `project_type` (see "Engineering Conventions").
8. **Data model overview**: list main entities, key fields (name + type), and entity relationships; for non-persistent project types, declare "no persistence".
9. **Non-functional requirements & acceptance criteria**: cover performance / security / maintainability (recommended), with verifiable acceptance criteria.
10. **Write document**: use `write_file` to write `REQUIREMENT.md` to the workspace root, strictly following the "REQUIREMENT.md Fixed Template".

## Post-checks

Run a self-check before and after calling `write_file`. Missing items must be filled before delivery:

- Pre-write check (draft completeness):
  - [ ] `project_type` field exists and is one of the four valid values
  - [ ] Functional requirements are split into P0 / P1 / P2, and P0 is non-empty
  - [ ] Tech stack selection exists with a per-item rationale
  - [ ] Project-type checklist is provided per `project_type`
- Post-write check (on-disk consistency):
  - [ ] Re-read `REQUIREMENT.md` with `read_file`, confirm section order matches the template
  - [ ] Confirm no "Hard Constraints" violations (see below)
  - [ ] Confirm the document is self-contained — a reader needs no access to `$ARGUMENTS` to understand the requirements
  - On any miss: go back to the relevant step, fill the gap, and `write_file` (overwrite) again.

## Hard Constraints (Red Lines — violation requires rewrite)

- `REQUIREMENT.md` MUST contain a `project_type` field limited to `fullstack` / `frontend_only` / `cli` / `script`.
- Functional requirements MUST be split into P0 (must) / P1 (important) / P2 (optional). Do not merge or omit the tiers; P0 must not be empty.
- Tech stack selection MUST be present, and each choice MUST have a rationale (not just a name list).
- Do NOT fabricate features not present in the user's request. Reasonable assumptions are allowed but MUST be explicitly recorded under "Assumptions & Open Items" — never disguised as confirmed requirements.
- Do NOT use vague descriptions without concrete metrics. Terms like "high performance", "user-friendly", "high availability", "fast response" MUST come with verifiable metrics (e.g. "first paint < 1.5s", "support 100 concurrent", "error rate < 0.1%"). Otherwise delete the description or add a metric.

## Recommendations (encouraged, not mandatory)

- Non-functional requirements should cover performance, security, and maintainability.
- Data model should include field names and types (e.g. `id: int`, `email: string`, `created_at: datetime`) so dev-design can lay out tables directly.
- User roles should come with a permission matrix (which role can operate which P0 features).
- Acceptance criteria should give executable cases (given input / expected output).

## Engineering Conventions

### Requirement Focus by Project Type

Match `project_type` to the corresponding structured checklist:

| Project type | Requirement focus | Required checklist |
| --- | --- | --- |
| `fullstack` | frontend-backend boundary, API contracts, data model, auth | page list + API list + DB table design |
| `frontend_only` | page interaction, visual structure, state management, storage | page routes + component list + data storage scheme |
| `cli` | subcommand design, arg parsing, IO conventions, exit codes | command args + subcommand tree + IO format |
| `script` | input source, output form, error handling, trigger mode | IO + processing flow + trigger mode |

Field requirements for each checklist item:

- **Page list / page routes** (fullstack / frontend_only): route path, page name, main interactions, auth required.
- **API list** (fullstack): HTTP method, path, request body, response, status codes, auth required.
- **DB table design** (fullstack): table name, field name, type, primary/foreign keys, key indexes (no need for full DDL).
- **Component list** (frontend_only): component name, layer (page / business / base), responsibility, reuse relations.
- **Data storage scheme** (frontend_only): localStorage / IndexedDB / sessionStorage / none, plus storage key design.
- **Command args** (cli): arg name, type, required, default, description.
- **Subcommand structure** (cli): main command + subcommand tree + usage string.
- **IO format** (cli): stdout / stderr, JSON / table, exit code table.
- **IO** (script): input source (file / stdin / env var), output form (file / terminal / DB).
- **Processing flow** (script): step list or Mermaid flowchart.
- **Trigger mode** (script): manual / scheduled (cron expr) / event-driven.

### REQUIREMENT.md Fixed Template

The document MUST strictly follow this section order. Section titles must not be swapped or omitted:

1. **Project Overview**: one-sentence goal + background + what problem it solves.
2. **Project Type**: `project_type` value + rationale.
3. **Tech Stack**: selection list + per-item rationale.
4. **User Roles**: role list + typical scenarios (permission matrix recommended).
5. **Functional Requirements**: three subsections listing P0 / P1 / P2, each as a verb-object phrase.
6. **Project-type Checklist**: the required checklist from the table above per `project_type`.
7. **Data Model Overview**: entities + field names + types + relationships (declare "no persistence" if none).
8. **Non-functional Requirements**: performance / security / maintainability (recommended to cover all three, each with a verifiable metric).
9. **Acceptance Criteria**: verifiable acceptance cases or checklists (given input / expected result).
10. **Assumptions & Open Items**: reasonable assumptions and open items for ambiguous points (mandatory closing section — do not let ambiguity leak downstream).

## Tools & Error Handling

- `list_files`: inspect existing workspace files, determine first-run vs incremental, check for an existing REQUIREMENT.md.
- `read_file`: read existing REQUIREMENT.md (incremental case) or context files.
- `write_file`: write the final `REQUIREMENT.md` to the root; on post-check misses, fill gaps and `write_file` (overwrite).
- This step does NOT use `run_command` — no code execution or compilation.
- Error handling:
  - If `$ARGUMENTS` is empty: terminate, write no file, return a prompt.
  - If intent keywords conflict and project type cannot be uniquely determined: pick via "minimal viable assumption" and record under assumptions. Do NOT fall back to asking.
  - If a post-check finds a red-line violation: go back to the relevant step, fix, and re-`write_file`. Never ship a defective document.

## Key Constraints

- Write requirement document only — no implementation code, no DDL, no pseudocode.
- The document MUST be self-contained — a reader needs no access to `$ARGUMENTS` to understand the requirements.
- The project type field affects downstream dev-design / dev-code directory structure and must be accurate.
- Tech stack must be selected only from "Supported Tech Stacks" — no improvisation.
- Assumptions must be reasonable and explicit — do not push ambiguity downstream.
- **Output language: Chinese (中文).** Although this skill instruction is in English, ALL generated project artifacts — REQUIREMENT.md content, code comments, UI text, error messages, RUN.md, and any other deliverable — MUST be written in Chinese. Do not use emoji.
