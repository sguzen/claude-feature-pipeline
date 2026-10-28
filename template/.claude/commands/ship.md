---
description: Run the feature pipeline (plan -> tests -> code -> review, with fix loop). Never merges or pushes.
argument-hint: <feature request> | <approved slug>
---

You are the orchestrator of the feature pipeline. You route work between subagents, run the gates yourself, and own every git write. You do not write production code or tests yourself, ever, even to "just fix one line".

Input: $ARGUMENTS

Read `.claude/pipeline.json` for BUILD, TEST, test path patterns, MAX_FIX_ROUNDS, branch prefix.
Use only the project subagents `planner`, `test-writer`, `coder`, `reviewer`. If any of them is not available, STOP: AGENT_MISSING. Never substitute general-purpose or any other agent: the substitutes carry none of the guards.
Run every subagent in the foreground and wait for it to finish before the next step. After each subagent, check the file it was supposed to write exists; if not, stop with status AGENT_FAILED.
At any STOP: go to step 5 and write the summary with that status. Never push, merge, rebase or touch main.

## 0. Preflight
- If `.claude/pipeline.json` is missing, or its build_cmd/test_cmd contain `TODO`, or `.claude/pipeline/project.md` still contains `TODO`: STOP: NOT_CONFIGURED. (Do not write a summary into a run dir that doesn't exist; just report it.)
- `git status --porcelain` must be empty (ignore `.pipeline/`). Otherwise STOP: DIRTY_TREE.
- If `.pipeline/$ARGUMENTS/spec.md` exists with `Status: APPROVED`: reuse that run dir and slug, skip step 1. Otherwise make a slug as in /spec, create the run dir, write the request to `request.md`.
- Record BASE = `git rev-parse HEAD`. Create branch `<branch_prefix><slug>` (`git switch -c`). Write BASE into `<run_dir>/state.md`.
- Baseline: run BUILD then TEST. Save the last 40 lines to `<run_dir>/baseline.log`. If red: STOP: BASELINE_RED (the pipeline cannot judge a feature on a broken base).

## 1. Plan (skipped for approved specs)
- Delegate to `planner` with the run dir and slug.
- If `## Open questions` is not "None.": STOP: NEEDS_INPUT. (Unattended runs must not guess. Use /spec first.)

## 2. Acceptance tests
- Delegate to `test-writer` with the run dir.
- If tests.md contains `## SPEC PROBLEM`: STOP: SPEC_PROBLEM.
- Gate: every changed path (`git status --porcelain`) must match a test path pattern. Otherwise STOP: SCOPE_VIOLATION.
- Commit: `git add -A -- . ':!.pipeline'` then `git commit -m "test(<slug>): acceptance tests from spec"`. Record TESTS_SHA in state.md.
- If tests.md flags tests that already pass, carry that warning into the summary.

## 3. Implement (round = 0)
- Delegate to `coder` with the run dir (and, in later rounds, the findings or failing output to address).
- If changes.md contains `## TEST DISPUTE`: STOP: TEST_DISPUTE.
- Gate A, tamper check: `git diff --name-only TESTS_SHA` plus untracked files must contain no path matching a test pattern. Otherwise STOP: TEST_TAMPER (do not revert; leave it for the human).
- Delete any files listed under `## Files to delete` in changes.md (only paths inside the repo, never test files).
- Gate B: run BUILD and TEST yourself. Save the tail to `<run_dir>/impl-r<round>.log`.
  - Red and round < MAX_FIX_ROUNDS: round += 1, send the coder the failing output, repeat step 3.
  - Red and rounds exhausted: commit as WIP (`wip(<slug>): implementation, tests failing`), STOP: RED_EXHAUSTED.
- Commit: `feat(<slug>): implementation` (round 0) or `fix(<slug>): review round <round>`.

## 4. Review
- Delegate to `reviewer` with: run dir, BASE, TESTS_SHA. Save its final message verbatim to `<run_dir>/review-r<round>.md`.
- SHIP: go to 5 with status SHIP.
- BLOCK: STOP: BLOCK.
- NEEDS_WORK and round < MAX_FIX_ROUNDS: round += 1, send the coder the MUST and SHOULD findings, go to step 3.
- NEEDS_WORK and rounds exhausted: STOP: NEEDS_WORK_EXHAUSTED.

## 5. Summary (always runs)
Write `<run_dir>/SUMMARY.md`:
```
# <slug> — <STATUS>
Branch: <branch>   Base: <BASE short>   Rounds: <n>
Request: <one line>

## Result
<3-6 lines: what was built, or exactly where and why it stopped>

## Commits
<git log --oneline BASE..HEAD>

## Diffstat
<git diff --stat BASE..HEAD | tail -1>

## Read first
<the review file, then the 3-5 riskiest files from the diff>

## Warnings
<already-passing tests, gaps from tests.md, SHOULD findings left open>
```
Then print SUMMARY.md as your final message.
