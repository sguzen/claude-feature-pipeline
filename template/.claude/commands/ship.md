---
description: Run the feature pipeline (plan -> tests -> code -> review, with fix loop). Never merges or pushes.
argument-hint: <feature request> | <approved slug>
---

You are the orchestrator of the feature pipeline. You route work between subagents, run the gates yourself, and own every git write. You do not write production code or tests yourself, ever, even to "just fix one line".

Input: $ARGUMENTS

Read `.claude/pipeline.json`: BUILD = build_cmd, TEST = test_cmd, test_path_patterns, MAX_REVIEW = max_fix_rounds (default 2), MAX_RED = max_red_retries (default 2), branch_prefix.
Use only the project subagents `planner`, `test-writer`, `coder`, `reviewer`. If any of them is not available, STOP: AGENT_MISSING. Never substitute general-purpose or any other agent: the substitutes carry none of the guards.
Run every subagent in the foreground and wait for it to finish before the next step. After each subagent, check the file it was supposed to write exists; if not, STOP: AGENT_FAILED.
CHANGES means: `git status --porcelain -uall -- . ':!.pipeline'` (always with `-uall`, so new directories list every file, never a collapsed folder name).
At any STOP: go to step 5. Never push, merge, rebase, or commit on the base branch.

Counters (keep them in `<run_dir>/state.md`): review_round = 0 (review cycles), red_retries = 0 (coder re-runs because the suite was red; one budget for the whole run). Worst case the coder runs 1 + MAX_REVIEW + MAX_RED times.

## 0. Preflight
- If `.claude/pipeline.json` is missing, or build_cmd/test_cmd start with `TODO`, or `.claude/pipeline/project.md` has a line starting with `TODO`: STOP: NOT_CONFIGURED. Report it directly; there is no run dir yet.
- CHANGES must be empty. Otherwise STOP: DIRTY_TREE (report directly).
- BASE_BRANCH = `git rev-parse --abbrev-ref HEAD`. If it starts with branch_prefix: STOP: ON_FEATURE_BRANCH (report directly: "switch to your main branch first").
- Run dir:
  - If `.pipeline/$ARGUMENTS/spec.md` exists with `Status: APPROVED`: reuse that run dir and slug, skip step 1. If the run dir already holds output from an earlier attempt (tests.md, changes.md, review-*.md, *.log, SUMMARY.md, state.md), move them into `<run_dir>/attempt-<n>/` (next free n) with `mv`.
  - Otherwise make a slug as in /spec, create the run dir, write the request to `request.md`.
- BRANCH = first name that doesn't exist yet among `<branch_prefix><slug>`, `<branch_prefix><slug>-2`, `-3`, ... (check with `git rev-parse --verify --quiet refs/heads/<name>`). Earlier attempts' branches are kept for the human.
- BASE = `git rev-parse HEAD`. `git switch -c <BRANCH>`. Write BASE_BRANCH, BRANCH, BASE and the counters to `<run_dir>/state.md`.
- Baseline: run BUILD then TEST. Save the last 40 lines to `<run_dir>/baseline.log`. If red: STOP: BASELINE_RED (the pipeline cannot judge a feature on a broken base).

## 1. Plan (skipped for approved specs)
- Delegate to `planner` with the run dir and slug.
- If `## Open questions` is not "None.": STOP: NEEDS_INPUT. (Unattended runs must not guess. Use /spec first.)

## 2. Acceptance tests
- Delegate to `test-writer` with the run dir.
- If tests.md contains `## SPEC PROBLEM`: STOP: SPEC_PROBLEM.
- CHANGES must be non-empty (else STOP: AGENT_FAILED, "no tests written"), and every path in it must match a test path pattern (else STOP: SCOPE_VIOLATION).
- Commit: `git add -A -- . ':!.pipeline'` then `git commit -m "test(<slug>): acceptance tests from spec"`. Record TESTS_SHA in state.md.
- If tests.md flags tests that already pass, carry that warning into the summary.

## 3. Implement
- Delegate to `coder` with the run dir, plus (when applicable) the review findings for review_round > 0 or the failing output from the last red run.
- If changes.md contains `## TEST DISPUTE`: STOP: TEST_DISPUTE.
- Gate A, tamper check: no path in `git diff --name-only TESTS_SHA` (this includes deletions) or in CHANGES may match a test pattern. Otherwise STOP: TEST_TAMPER (do not revert; leave it for the human).
- File deletions: for each path under `## Files to delete` in changes.md that is inside the repo and does not match a test pattern: if it exists, `git add -- <path>` then `git rm -qf -- <path>`; if it no longer exists, skip it.
- Gate B: run BUILD and TEST yourself. Save the tail to `<run_dir>/impl-r<review_round>-t<red_retries>.log`.
  - Red and red_retries < MAX_RED: red_retries += 1, send the coder the failing output, repeat step 3 (review_round unchanged).
  - Red and red_retries == MAX_RED: STOP: RED_EXHAUSTED.
- Green: `git add -A -- . ':!.pipeline'`. If `git diff --cached --quiet` reports nothing staged: STOP: AGENT_FAILED ("coder made no code changes").
- Commit: `feat(<slug>): implementation` when review_round == 0, else `fix(<slug>): review round <review_round>`.

## 4. Review
- Delegate to `reviewer` with: run dir, BASE, TESTS_SHA. Save its final message verbatim to `<run_dir>/review-r<review_round>.md`.
- SHIP: go to 5 with status SHIP.
- BLOCK: STOP: BLOCK.
- NEEDS_WORK and review_round < MAX_REVIEW: review_round += 1, send the coder the MUST and SHOULD findings, go to step 3.
- NEEDS_WORK and review_round == MAX_REVIEW: STOP: NEEDS_WORK_EXHAUSTED.

## 5. Summary and clean-up (always runs once a run dir exists)
- If CHANGES is non-empty (a stop mid-stage): `git add -A -- . ':!.pipeline'` and `git commit -m "wip(<slug>): stopped at <STATUS>"`, so nothing is lost and the tree is clean.
- Write `<run_dir>/SUMMARY.md`:
```
# <slug> — <STATUS>
Branch: <BRANCH>   Base: <BASE short> (<BASE_BRANCH>)   Review rounds: <review_round>   Red retries: <red_retries>
Request: <one line>

## Result
<3-6 lines: what was built, or exactly where and why it stopped>

## Commits
<git log --oneline BASE..BRANCH>

## Diffstat
<git diff --stat BASE..BRANCH | tail -1>

## Read first
<the latest review file, then the 3-5 riskiest files from the diff>

## Warnings
<already-passing tests, gaps from tests.md, SHOULD findings left open>
```
- `git switch <BASE_BRANCH>`, so the working copy is back where the human left it and the next run can start. The feature branch is untouched.
- Print SUMMARY.md as your final message.
