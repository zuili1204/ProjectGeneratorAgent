---
name: dev-debug
version: 1.1.1
description: Use when dev-code or dev-selfcheck hits a repeatedly failing error and "try again" patching no longer works — runs hypothesis-driven systematic debugging (root-cause investigation, pattern analysis, hypothesis testing, implementation) and produces DEBUG_REPORT.md
inputs: [$ARGUMENTS]
outputs: [DEBUG_REPORT.md]
depends_on: [code/]
shared: []
est_tokens: 6000
est_iters: 20
---

# Systematic Debugging (dev-debug)

## Overview

**Core principle:** No blind trial-and-error. Every fix must be backed by a falsifiable hypothesis, and every verification must paste evidence. After 3 failed fixes, stop and question the architecture — do not attempt a 4th blind change.

## Objective

When `dev-code` / `dev-selfcheck` encounter a repeatedly failing error (failing tests, runtime crash, API error) and "try again" patching fails, manually invoke this step to perform **hypothesis-driven systematic debugging**. Produce `DEBUG_REPORT.md` recording the root-cause investigation, hypothesis verification, fix process, and conclusion.

This step is **NOT part of the default workflow** — it is an on-demand standalone skill. Adapted from the superpowers systematic-debugging methodology: no relying on luck, rely on the scientific method.

## When to Invoke

- dev-selfcheck's test suite fails after 3 consecutive fix attempts
- Runtime errors (500 / ImportError / ModuleNotFoundError / TypeError) recur repeatedly
- "Changed A but got error B" — suspected shared state or coupling
- The LLM is stuck in a "change → run → fail → change again" loop

## Inputs

- `$ARGUMENTS`: error symptom description (error message / repro steps / expected behavior)
- Existing workspace files (MUST read relevant code under `code/`, `REQUIREMENT.md`, `DESIGN.md`, `SELF_CHECK.md` if present)
- `_ledger.md`: review recent changes (git commit / base_commit) to locate the regression point

## Four-Phase Debugging Process

### Phase 1: Root-Cause Investigation (understand before acting)

**Goal**: turn the "symptom" into a "locatable root cause" — do not rush to change code.

1. **Read the full error**: use `run_command` to reproduce the error and **read stderr/stdout in full** (not just the last line). Record: error type, error message, the first stack frame that is your code (not a third-party library), line number.
2. **Stabilize the repro**: find the minimal repro command (e.g. `python -m pytest code/tests/test_x.py::test_y -v`). The repro MUST be stable (3 consecutive failures counts as stable; intermittent failures are treated as concurrency issues separately).
3. **Check recent changes**: use `run_command` to run `git diff HEAD~3 -- code/` to see what the last 3 commits changed. Regression bugs are often in recent changes. Read `_ledger.md`'s concerns field for leftover risks from the previous round.
4. **Component-boundary logging**: add temporary `print` or `logging` at the entry/exit of the modules involved in the error (use `write_file` to temporarily modify code) to pinpoint which layer corrupts the data. Logs should print "input + output", not "reached here".
5. **Data-flow tracing**: trace backward from the error point: error variable ← where assigned ← upstream param ← data source (DB / request body / config). Find the first link where "the value is wrong".

### Phase 2: Pattern Analysis (find a reference)

**Goal**: find a "working example" in the same codebase that runs, and compare to understand correct behavior.

1. **Find a working example**: search the workspace or dependency library for **similar code that works**. For example, `test_api.py`'s `/health` passes but `/users` errors — compare the two.
2. **Read the working example in full**: do not just skim a snippet — read the full working file to understand how it does initialization, dependency injection, and error handling.
3. **Compare differences**: list structural differences between the working example and the erroring code (import order, instantiation timing, config loading, dependency version). Regression bugs are often "missing one seemingly-unimportant line of initialization".
4. **Check dependency docs**: if you suspect a library-usage issue, use `run_command` to run `python -c "import xxx; help(xxx.yyy)"` or check the official docs to confirm the API signature and version compatibility.

### Phase 3: Hypothesis Testing (single hypothesis, minimal change)

**Goal**: turn the root cause into a verifiable hypothesis — verify one at a time.

1. **Form a hypothesis**: write the hypothesis in one sentence, format: "the root cause is `<specific location>`'s `<specific problem>`, because `<reasoning>`, verified by `<minimal change>`, expected result is `<observable outcome>`". Example: "the root cause is `main.py:23`'s `db = Database()` running before app instantiation, so routes can't get db; verified by moving db init into `create_app()`, expected `/users` returns 200".
2. **Single-hypothesis principle**: change only one variable at a time. Do not change 3 places at once and run — even if it passes, you won't know which fix worked. If multiple root causes are possible, rank by likelihood and verify one by one.
3. **Minimal change**: use `write_file` to make the minimal modification (one or a few lines); do not refactor opportunistically. Decide whether to expand the fix scope after verification.
4. **Verify the hypothesis**: run the Phase 1 repro command once, paste exit_code + output. Hypothesis holds → go to Phase 4; does not hold → return to Phase 3 with the next hypothesis, or return to Phase 1 to re-investigate.

### Phase 4: Implementation (failing test → single fix → verify)

**Goal**: land the verified hypothesis as a formal fix and ensure no regression.

1. **Write a failing test**: first write a test for the bug (e.g. `test_users_returns_200`), run it and confirm it fails (proving the test is valid and the bug exists).
2. **Land the fix**: use `write_file` to apply the minimal change verified in Phase 3.
3. **Verify the fix**: run the newly written test to confirm pass, then run the full test suite `python -m pytest code/tests/ -v` to confirm no regression.
4. **Clean up temp logs**: remove the temporary `print` / `logging` added in Phase 1 (use `write_file` to restore).
5. **Question the architecture after 3 failures**: if the Phase 3 + Phase 4 loop fails 3 times without fixing, **stop**. This is usually not solvable by "trying another hypothesis" — it's an architectural issue (shared state, circular dependency, abstraction leak). Mark "architecture signal" in `DEBUG_REPORT.md`, list the new coupling point each fix revealed, and recommend discussing a refactor with a human.

## Architecture Signals After 3+ Failures

When the following occur, stop blind changes and switch to an architecture review:

- Each fix reveals a new "shared state" (global vars, singletons, module-level vars modified in multiple places)
- Each fix discovers a "hidden dependency" (A depends on B's init order, but the code doesn't show it)
- Fixing one bug introduces another (whack-a-mole mode)
- The same file is repeatedly modified but the problem is in other modules (abstraction leak)
- Tests pass but runtime hangs (test env vs runtime env inconsistency — config/dependency issue)

At this point, write in `DEBUG_REPORT.md`: the list of verified hypotheses + the coupling point each failure revealed + the recommended refactor direction, and hand it to a human for a decision.

## Execution Steps

1. **Step 1: immediately write the `DEBUG_REPORT.md` skeleton with `write_file`**, with the four-phase headers + symptom description, each item marked "pending investigation". MUST NOT be skipped or deferred.
2. **Phase 1 root-cause investigation**: execute the 5 steps above — use `run_command` to reproduce + `git diff` to check changes + temp logs to trace data flow. Write findings into `DEBUG_REPORT.md`.
3. **Phase 2 pattern analysis**: find a working example, read it in full, compare differences. Write the comparison into `DEBUG_REPORT.md`.
4. **Phase 3 hypothesis testing**: form a hypothesis, verify with a single minimal change. Write the hypothesis + verification result (including run_command output) into `DEBUG_REPORT.md`.
5. **Phase 4 implementation**: write a failing test → land the fix → verify pass + full test suite no regression → clean up temp logs. Write the fix and test evidence into `DEBUG_REPORT.md`.
6. **Check whether architecture signals trigger**: if 3 failures, mark the architecture signal and refactor recommendation in `DEBUG_REPORT.md`, terminate debugging and hand to a human.
7. **Update DEBUG_REPORT.md**: use `write_file` to overwrite the complete report, then run the post-check.

## Post-checks

Before the final `write_file` of `DEBUG_REPORT.md`:

- [ ] All four phases executed (root-cause investigation / pattern analysis / hypothesis testing / implementation); none skipped
- [ ] Each hypothesis has "one-sentence hypothesis + verification command + expected result + actual result"
- [ ] After the fix, test-passing evidence is pasted (exit_code 0 + full test suite no regression)
- [ ] Temp logs cleaned up (no residual `print` debug statements)
- [ ] If architecture signals triggered, the coupling point each failure revealed + refactor recommendation are listed

## Hard Constraints (Red Lines — violation requires rewrite)

- Step 1 MUST use `write_file` to write the `DEBUG_REPORT.md` skeleton; MUST NOT be skipped.
- **Blind changes are FORBIDDEN**: before every `write_file` code modification, the current hypothesis MUST be written in `DEBUG_REPORT.md`. A modification without a hypothesis counts as a blind change.
- **Single-hypothesis principle**: change only one variable at a time; changing multiple places at once and running is FORBIDDEN.
- **Evidence is mandatory**: every hypothesis verification MUST paste the `run_command` exit_code + output summary; "should be fine" is FORBIDDEN.
- **Must stop after 3 failures**: if the Phase 3+4 loop fails 3 times without a fix, you MUST switch to architecture-signal assessment; a 4th blind change is FORBIDDEN.
- After a fix, the full test suite MUST be run to confirm no regression — claiming a fix after only a unit test is NOT allowed.

## Recommendations

- Mark temp logs with a `# DEBUG:` prefix for easy grep-based cleanup.
- Rank hypotheses by likelihood; prioritize verifying "introduced by a recent change".
- If the error involves a third-party library, check the issue tracker and changelog first to confirm whether it's a known bug.
- Keep repro commands minimal (a unit test over the full suite; a single file over the full directory).

## DEBUG_REPORT.md Fixed Template

1. **Symptom Description**: error type / error message / repro command / expected behavior / actual behavior.
2. **Phase 1 Root-Cause Investigation**: full error stack / recent changes (git diff) / component-boundary log findings / data-flow tracing conclusion.
3. **Phase 2 Pattern Analysis**: working example location / difference comparison vs erroring code / dependency doc check.
4. **Phase 3 Hypothesis Testing**: hypothesis list (each with one-sentence hypothesis + verification command + expected + actual + held/rejected).
5. **Phase 4 Implementation**: failing test code + fix diff + verification evidence (unit test pass + full test suite no regression) + temp log cleanup confirmation.
6. **Architecture Signal Assessment (if triggered)**: 3-failure list + the coupling point each revealed + refactor recommendation.
7. **Conclusion**: root cause / fix method / residual risk / whether to recommend re-verification in dev-selfcheck.

## Tools & Error Handling

- `read_file`: read relevant code under `code/`, `REQUIREMENT.md`, `DESIGN.md`, `_ledger.md`, working examples.
- `write_file`: step 1 writes the `DEBUG_REPORT.md` skeleton; temporarily add debug logs; land the fix; finally overwrite `DEBUG_REPORT.md`; clean up temp logs.
- `run_command`: reproduce the error (`pytest` / `python main.py`), `git diff` / `git log` to check changes, check dependency docs (`python -c "help(...)"`). Single timeout 60s.
- `list_files`: find working examples, locate relevant files.
- Error handling:
  - If the error cannot be stably reproduced: mark "intermittent issue" in the report and treat it as a concurrency/timing problem (add locks, add waits, add retries).
  - If `run_command` times out: likely a dead loop or deadlock; mark it and switch to an architecture review.
  - If architecture signals trigger: terminate debugging, hand to a human for a decision; do not force a 4th fix.

## Key Constraints

- Hypothesis-driven; blind trial-and-error is FORBIDDEN.
- One variable at a time; verify with minimal change.
- Paste evidence at every step; hypothetical statements are FORBIDDEN.
- Question the architecture after 3 failures; do not brute-force.
- After a fix, the full test suite MUST show no regression before claiming the fix.
- Temp debug code MUST be cleaned up; it MUST NOT remain in the deliverable.
- **Output language: Chinese (中文).** Although this skill instruction is in English, ALL generated project artifacts — DEBUG_REPORT.md content, code comments, and any other deliverable — MUST be written in Chinese. Do not use emoji.
