---
name: dev-design
version: 1.4.0
description: Use when REQUIREMENT.md exists and a buildable design blueprint is needed before coding — produces DESIGN.md (architecture, file-level tree, data model, interfaces, task list) plus DESIGN_SYSTEM.md (semantic color/typography/spacing/motion tokens) that dev-code consumes directly
inputs: [$ARGUMENTS]
outputs: [DESIGN.md, DESIGN_SYSTEM.md]
depends_on: [REQUIREMENT.md]
est_tokens: 6000
est_iters: 12
---

# System Design (dev-design)

## Overview

**Core principle:** Produce a buildable, file-level design blueprint that dev-code can follow directly. Design only — no implementation-level code.

## Objective

Based on `REQUIREMENT.md`, produce `DESIGN.md` as the second step of the "one-sentence-to-project" workflow. The design document must specify project type, tech stack, architecture diagram, directory structure (file-level), module breakdown, data model, interface design, page routes, key flows, and a structured task list — providing a directly buildable construction blueprint for the subsequent `dev-code` step. This step does system design only and writes no implementation-level code.

> **v1.1 change**: upgraded "development sequence" prose into a **mandatory structured task list (Task list)**. Adapted from superpowers plan-driven development: each Task has Files / Interfaces / checkable Steps (write failing test → verify fail → write impl → verify pass → commit). dev-code executes the Task list strictly, running verification between Tasks — a failure does not advance to the next Task.

## Inputs

- `$ARGUMENTS`: the user's original request (reference only, not the sole basis)
- Existing workspace files (MUST read `REQUIREMENT.md`, which should declare `project_type`, tech stack, feature list)
- If an existing `DESIGN.md` is present, use `list_files` / `read_file` to detect it and update incrementally

## Pre-checks

Before formal design, complete the following checks. If any fails, terminate with a reason and do not produce an empty document:

1. **REQUIREMENT.md existence**: use `read_file` to read `REQUIREMENT.md` at the workspace root. If missing or empty, terminate immediately with "REQUIREMENT.md missing, run dev-requirement first" and do NOT call `write_file`.
2. **project_type parsing**: parse the `project_type` field from `REQUIREMENT.md`. The value MUST be one of `fullstack` / `frontend_only` / `cli` / `script`. If missing or invalid, terminate with the specific problem.
3. **Tech stack parsing**: parse the tech stack selection from `REQUIREMENT.md` (frontend framework / backend framework / database / language) and record each item to align subsequent design. If the tech stack field is missing, terminate with the specific problem.
4. **Feature list parsing**: confirm `REQUIREMENT.md` contains P0 / P1 / P2 functional requirements and P0 is non-empty. If P0 is empty, terminate with the specific problem.
5. **Tech-stack vs project-type consistency**: quickly check whether the tech stack is self-consistent with the project type (e.g. `cli` should not have a web frontend framework; `frontend_only` should not have a database). If inconsistent, treat REQUIREMENT.md as authoritative and explicitly note the assumption in the design document. Do NOT fall back to asking.

## Execution Steps

Execute the following 10 steps in order. Each step's output feeds into the final `DESIGN.md`:

1. **Confirm project type & tech stack**: restate the `project_type` and tech stack from REQUIREMENT.md as the baseline for the entire design document. No subsequent design may deviate from this baseline.
2. **Draw architecture diagram**: based on project type, draw a system architecture diagram. Prefer Mermaid (`graph TD` / `flowchart`), fall back to ASCII. The diagram must show main modules, data flow, and external dependencies.
3. **Design file-level directory structure**: provide a tree diagram precise down to specific file names (with extensions). Using `...` or "omitted" placeholders is FORBIDDEN. dev-code will create the file skeleton from this.
4. **Module breakdown & responsibilities**: list core modules. One paragraph each: responsibility, input, output, dependencies.
5. **Design data model**: list entities, field names, types, constraints (primary key / foreign key / not null / unique / default), and entity relationships. Provide an ER diagram (Mermaid `erDiagram`) or a table-structure table. For non-persistent project types, explicitly declare "no persistence".
6. **Tech stack detail**: per matched tech stack, expand the design elements (see "Engineering Conventions - Tech Stack Adaptation") and explain how framework features map to this project's modules and flows.
7. **Design interfaces / routes / commands / IO per project type**:
   - `fullstack`: API table (path / method / request body / response body / status codes / auth)
   - `frontend_only`: page route table (URL / component / data source / auth)
   - `cli`: command arg table + subcommand structure + output format example
   - `script`: input format + processing flow diagram + output format + error handling strategy
8. **Describe key flows**: use Mermaid sequence diagrams (`sequenceDiagram`) or flowcharts (`flowchart`) to describe 1+ core main flows (e.g. user login, data creation, command execution).
9. **Produce structured task list (Task list, red line)**: lay out an **executable task list** for the dev-code step. Each Task has Files / Interfaces / checkable Steps. Tasks have dependency order (entry file → core modules → utilities → config → tests → integration); a failure does not advance. Format strictly per "Engineering Conventions - Structured Task List Format". Replacing the task list with prose is FORBIDDEN.
10. **Produce DESIGN_SYSTEM.md (frontend projects — red line)**: For `fullstack` / `frontend_only` projects, use `write_file` to write `DESIGN_SYSTEM.md` to the root, following the template in `references/design-system-template.md`. Select the industry color baseline from `references/industry-design-reasoning.md` based on the product type parsed in step 1. The design system MUST include:
    - **Semantic color tokens** using the `--primary` / `--on-primary` / `--secondary` / `--on-secondary` / `--accent` / `--on-accent` / `--background` / `--foreground` / `--card` / `--card-foreground` / `--muted` / `--muted-foreground` / `--border` / `--destructive` / `--on-destructive` / `--ring` naming convention (NOT `--color-primary` or other ad-hoc names)
    - **Light and dark mode** CSS variable blocks (`:root` and `[data-theme="dark"]`)
    - **Typography pairing** selected from `_shared/typography-pairing.md` with Google Fonts `@import` URL and Tailwind config snippet
    - **4/8dp spacing scale** (`--space-1` through `--space-20`)
    - **Radius, shadow, and motion tokens**
    - **WCAG contrast notes** for the chosen primary/foreground pairs

    For `cli` / `script` projects with no UI, skip this step and explicitly declare "DESIGN_SYSTEM.md not applicable (no UI)" in DESIGN.md.
11. **Write documents**: use `write_file` to write `DESIGN.md` to the root, strictly following the "DESIGN.md Fixed Template". Then, if step 10 applies, use `write_file` to write `DESIGN_SYSTEM.md` to the root.

## Post-checks

Run a self-check before and after calling `write_file`. Missing items must be filled before delivery:

- Pre-write check (draft completeness):
  - [ ] Architecture diagram exists (Mermaid or ASCII) and is consistent with the prose
  - [ ] Directory structure is precise down to file names, no `...` placeholder, directly `mkdir` / `touch`-able
  - [ ] Data model has all four elements: field name, type, constraint, relationship (except non-persistent projects)
  - [ ] Tech stack detail covers every selection declared in REQUIREMENT.md, no deviation
  - [ ] Interface / route / command / IO table fields are complete per project type
  - [ ] At least 1 sequence diagram or flowchart for a key flow
  - [ ] **Structured task list exists; each Task has Files / Interfaces / checkable Steps (write failing test + verify fail + write impl + verify pass + commit)**
  - [ ] No implementation-level code anywhere (only schema / pseudocode / DDL allowed)
  - [ ] **For frontend projects (fullstack / frontend_only): DESIGN_SYSTEM.md exists, containing semantic color tokens with the `--primary` / `--on-primary` naming convention, `:root` + `[data-theme="dark"]` blocks, typography `@import`, and spacing scale**
- Post-write check (on-disk consistency):
  - [ ] Re-read `DESIGN.md` with `read_file`, confirm section order matches the fixed template
  - [ ] **Re-read `DESIGN_SYSTEM.md` (if applicable), confirm it contains `:root` and `[data-theme="dark"]` blocks with `--primary` token**
  - [ ] Confirm no "Hard Constraints" violations (see below)
  - [ ] Confirm the document is self-contained — a reader needs no access to REQUIREMENT.md to understand the design
  - On any miss: go back to the relevant step, fill the gap, and `write_file` (overwrite) again.

## Hard Constraints (Red Lines — violation requires rewrite)

- The directory structure MUST be precise down to file names (with extensions). Using `...` or any placeholder is FORBIDDEN. dev-code must be able to create the file skeleton directly from this.
- An architecture diagram (Mermaid or ASCII) MUST be included. Replacing it with prose only is not allowed.
- The data model MUST include field name, type, and constraint (at least a constraint category: primary key / foreign key / not null / unique / default). Non-persistent projects must explicitly declare so.
- **A structured task list (Task list) MUST be produced. Replacing it with prose "development sequence" is FORBIDDEN. Each Task MUST have Files / Interfaces / checkable Steps.**
- Implementation-level code is FORBIDDEN: no complete function bodies, no business logic. Only schema definitions, DDL `CREATE TABLE` statements, pseudocode, and interface signatures are allowed.
- Deviating from the tech stack fixed in REQUIREMENT.md is FORBIDDEN: do not add/remove frameworks, swap databases, or introduce main frameworks not declared in REQUIREMENT.md.
- **For `fullstack` / `frontend_only` projects, `DESIGN_SYSTEM.md` MUST be produced** with the semantic token naming convention (`--primary` / `--on-primary` / `--background` / `--foreground` / `--card` / `--border` / `--muted` / `--destructive` etc.). Ad-hoc naming like `--color-primary` is FORBIDDEN. For `cli` / `script` projects, explicitly declare "no UI" in DESIGN.md instead.

## Recommendations (encouraged, not mandatory)

- Prefer Mermaid for diagrams (architecture, ER, sequence, flowchart); ASCII only as fallback.
- API interfaces should include request / response examples (JSON snippets or schema) so dev-code can code directly.
- Page routes should mark permission requirements (auth required, required roles), aligned with REQUIREMENT.md user roles.
- Module design should mark the "exposed" vs "internal" boundary to reduce dev-code coupling risk.
- Key flows should cover at least 1 exception path (e.g. login failure, validation failure).

## Engineering Conventions

### Design Focus by Project Type

Match `project_type` to the corresponding structured design:

| Project type | Design focus | Required design items |
| --- | --- | --- |
| `fullstack` | frontend-backend boundary, API contracts, data model, auth | frontend architecture + backend architecture + DB ER diagram + API table (path / method / request / response) |
| `frontend_only` | page interaction, visual structure, state management, storage | page route table + component tree + state management scheme + data storage scheme |
| `cli` | subcommand design, arg parsing, IO conventions, exit codes | command arg table + subcommand structure + output format example |
| `script` | input source, output form, error handling, trigger mode | input format + processing flow diagram + output format + error handling strategy |

> Note: if `backend_only` is encountered, refer to the backend portion of `fullstack` and trim the frontend architecture section.

Field requirements for each design item:

- **Frontend architecture** (fullstack / frontend_only): component layering (container / presentational or page / business / base), state management scheme, routing scheme.
- **Backend architecture** (fullstack / backend_only): layering (Controller / Service / Repository / Model), middleware chain, exception handling.
- **DB ER diagram** (fullstack): Mermaid `erDiagram` + table-structure table (table / fields / types / constraints / indexes).
- **API table** (fullstack / backend_only): Method / Path / description / request body / response body / status codes / auth.
- **Page route table** (fullstack / frontend_only): URL / component / data source / auth.
- **Component tree** (frontend_only): Mermaid `graph` or ASCII tree, marking reuse relations.
- **State management scheme** (frontend_only): store module breakdown + key state fields.
- **Data storage scheme** (frontend_only): localStorage / IndexedDB / sessionStorage / none + storage key design.
- **Command arg table** (cli): arg name / type / required / default / description.
- **Subcommand structure** (cli): main command + subcommand tree + usage string.
- **Output format example** (cli): stdout / stderr, JSON / table, exit code table.
- **Input format** (script): file type / path convention / CLI args / env vars.
- **Processing flow diagram** (script): Mermaid `flowchart` or step list.
- **Output format** (script): output file / console format / field meanings.
- **Error handling strategy** (script): exception types, retry strategy, log persistence strategy.

### Tech Stack Adaptation

For common tech stacks, the design document must additionally cover the following elements (apply per actual selection):

#### Frontend

- **React**: component design (container / presentational layering), core hooks usage (`useState` / `useEffect` / `useMemo` / `useReducer` etc., state purpose), state management scheme (Context / Zustand / Redux Toolkit — pick one, state rationale and store module breakdown).
- **Vue**: Composition API composable design (`setup` / custom composables), reactivity strategy (boundaries of `ref` / `reactive` / `computed`), Pinia state module design (store breakdown + key state).
- **Pure HTML + JS**: modularization scheme (ES Module / IIFE / native — state rationale), DOM manipulation strategy (event delegation / template rendering / data-driven), state-view sync approach.

#### Backend

- **FastAPI**: routing design (group by `APIRouter`, list groups and their endpoints), Pydantic models (`BaseModel` request / response schema), dependency injection (`Depends` use cases, e.g. auth / DB session), middleware & exception handlers (CORS / logging / global exception).
- **Flask**: blueprint design (`Blueprint` module split, list blueprints and their routes), SQLAlchemy models (model class definitions + relationship mapping), config management (env vars / config class), template rendering strategy (Jinja2 template split, if applicable).
- **Node + Express**: middleware chain design (logging / auth / error handling — note order and responsibility), routing design (split `Router` by resource, list route files and their endpoints), error handling (unified error middleware + error code convention).

#### Database

- **SQLite**: table structure design (fields / types / primary & foreign keys / defaults), provide DDL (`CREATE TABLE`).
- **MySQL**: table structure design + index design (primary index, unique index, composite index and hit scenarios) + charset & storage engine (e.g. `utf8mb4` / `InnoDB`), provide DDL.

### Structured Task List Format

The dev-code step will **execute strictly in this Task list order**, running verification commands between Tasks — a failure does not advance. Each Task MUST have Files / Interfaces / checkable Steps. Format:

```markdown
### Task 1: [component name, e.g. app entry & /health endpoint]
**Files:** Create code/backend/main.py / Test code/tests/test_main.py
**Interfaces:** Produces app factory `create_app() -> FastAPI`, exposes `GET /health`
- [ ] Step 1: write failing test [provide real test code snippet for test_main.py]
- [ ] Step 2: run test, confirm fail [command `pytest code/tests/test_main.py -v` + expected failure reason]
- [ ] Step 3: write minimal implementation [provide real impl code snippet for main.py]
- [ ] Step 4: run test, confirm pass [command + expected exit_code 0]
- [ ] Step 5: commit [git commit -m "task1: app entry + /health"]

### Task 2: [next component depending on Task 1]
**Files:** ...
**Interfaces:** ...
- [ ] Step 1: ...
...
```

Task granularity requirements:
- Each Task corresponds to one independently verifiable functional unit (one component / a group of endpoints / one page). Do not cram the whole project into one Task.
- Recommended Task count: 3-8. Too few = too coarse (cannot locate failures); too many = too fine (commit noise).
- The Files field MUST list the files created/modified by this Task (including test files), using `code/`-relative paths.
- The Interfaces field describes the Task's exposed interfaces (function signature / route / command) for downstream Tasks to reference.
- Steps MUST include the five steps "write failing test → verify fail → write impl → verify pass → commit". Flexible TDD allows non-strict red-green order, but the test artifact and verification command are NOT optional.
- The first Task MUST be the entry file + smoke test (so the project can run); subsequent Tasks stack features on top.

### DESIGN.md Fixed Template

The document MUST strictly follow this section order. Section titles must not be swapped or omitted:

1. **Project Overview**: one-sentence goal + project type + tech stack summary (restate the REQUIREMENT.md baseline).
2. **Architecture Diagram**: system architecture diagram (Mermaid preferred, ASCII fallback), marking main modules and data flow.
3. **Directory Structure**: file-level tree diagram, precise to file names, no `...` placeholder.
4. **Data Model**: entities + field names + types + constraints + relationships, with ER diagram or table-structure table (declare "no persistence" if none).
5. **Tech Stack Detail**: expand design elements per matched tech stack (see "Tech Stack Adaptation").
6. **Interface / Route / Command Design** (by project type):
   - `fullstack`: API table + frontend-backend integration contract (unified response format, error codes, CORS)
   - `frontend_only`: page route table + component tree + state management scheme + data storage scheme
   - `cli`: command arg table + subcommand structure + output format example + exit code convention
   - `script`: input format + processing flow diagram + output format + error handling strategy
7. **Key Flows**: 1+ Mermaid sequence diagram or flowchart covering core main flows.
8. **Structured Task List**: an executable Task list for dev-code, each Task with Files / Interfaces / checkable Steps. Format per "Engineering Conventions - Structured Task List Format".

## Tools & Error Handling

- `list_files`: inspect existing workspace files, determine first-run vs incremental, check for an existing DESIGN.md.
- `read_file`: read `REQUIREMENT.md` (required); read existing DESIGN.md (incremental case); re-read the on-disk file during post-check.
- `write_file`: write the final `DESIGN.md` to the root; on post-check misses, fill gaps and `write_file` (overwrite).
- This step does NOT use `run_command` — no code execution or compilation.
- Error handling:
  - If `REQUIREMENT.md` is missing or empty: terminate, write no file, return a prompt.
  - If `project_type` is missing or invalid: terminate with the specific problem. Do NOT fall back to asking.
  - If the tech stack is inconsistent with the project type: treat REQUIREMENT.md as authoritative and explicitly note the assumption in the design document.
  - If a post-check finds a red-line violation: go back to the relevant step, fix, and re-`write_file`. Never ship a defective document.

## Key Constraints

- Design document only — no implementation-level code (no complete function bodies, no business logic).
- The document MUST be self-contained — a reader needs no access to REQUIREMENT.md to understand the design.
- The directory structure must be directly buildable (dev-code creates the file skeleton from it). `...` placeholders are FORBIDDEN.
- Interface / route / command design must give concrete path, method, params — no vague generalities.
- The tech stack may only follow what is fixed in REQUIREMENT.md — do not add/remove or swap main frameworks.
- Design granularity must reach "file level" — dev-code should generate the file skeleton directly from this.
- **Output language: Chinese (中文).** Although this skill instruction is in English, ALL generated project artifacts — DESIGN.md content, code comments, UI text, error messages, RUN.md, and any other deliverable — MUST be written in Chinese. Do not use emoji.
- If REQUIREMENT.md has ambiguous points, apply "minimal viable assumption" and explicitly note it in the design document. Do NOT fall back to asking.
