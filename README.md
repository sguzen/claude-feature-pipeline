# Claude Code feature pipeline

Four guarded subagents plus an orchestrator: **plan → failing tests → implementation → read-only review**, with a bounded fix loop. Runs unattended, never merges or pushes, and leaves a `SUMMARY.md` per feature. Installs into any git repo; stack presets for .NET, Node, Python, Go and Rust.

```
/spec  (you, interactive)                    scripts/ship-overnight.sh <slug>  (unattended)
  planner ⇄ your answers ─► APPROVED spec ─►  baseline gate ─► test-writer ─► commit tests
                                              ─► coder ─► tamper gate + build/test gate ─► commit
                                              ─► reviewer ─► SHIP | NEEDS_WORK (≤2 rounds) | BLOCK
                                              ─► SUMMARY.md + notification
```

## Install into a project

```bash
python3 /path/to/claude-feature-pipeline/install.py /path/to/project            # autodetects stack
python3 /path/to/claude-feature-pipeline/install.py /path/to/project --stack node
python3 /path/to/claude-feature-pipeline/install.py /path/to/project --dry-run   # show what it would do
```

Then, in the project:

1. Run `claude` and accept the trust prompt if shown. Project-subagent hooks don't run in an untrusted folder, and `-p` runs don't grant trust. Check: `jq --arg p "$(pwd)" '.projects[$p].hasTrustDialogAccepted' ~/.claude.json` → `true`.
2. `/pipeline-setup`: runs the build/test commands, checks which files the test patterns catch, and drafts `.claude/pipeline/project.md` with you. `/ship` refuses to run until that file has no `TODO` line.
3. `bash scripts/test-guards.sh`: guard logic must pass; it also lists what your patterns count as tests.
4. Commit: `git add .claude scripts .gitignore && git commit -m "chore: add feature pipeline"`. `/ship` won't start on a dirty tree.

Update a project to a newer kit: `install.py /path/to/project --update`. Agents, commands, hook and scripts are replaced. `pipeline.json` only gains missing keys. `project.md` and your settings values are never changed.

## What gets installed

| Path | Owner | Purpose |
|---|---|---|
| `.claude/agents/{planner,test-writer,coder,reviewer}.md` | kit | Generic agents; read `project.md` for project rules |
| `.claude/commands/{spec,ship,pipeline-setup}.md` | kit | Interactive planning, orchestrator, setup |
| `.claude/hooks/guard.py` | kit | Per-role PreToolUse guard (paths, git, shell writes, bans) |
| `scripts/ship-overnight.sh`, `scripts/test-guards.sh` | kit | Headless runner with sleep inhibit + notify; guard tests |
| `.claude/pipeline.json` | project | build/test commands, test path patterns, banned commands, fix rounds |
| `.claude/pipeline/project.md` | project | Architecture, migrations, required spec sections, test rules, review checklist |
| `.claude/settings.json` | merged | `CLAUDE_CODE_FORK_SUBAGENT=0`, allow/deny rules (git + stack), secret-file read denies |

## Daily use

```bash
claude
> /spec add CSV export of renewals due in N days
#   answer open questions, approve
scripts/ship-overnight.sh 20261028-csv-export-renewals    # NTFY_TOPIC=xyz for a phone ping
```
Morning: `.pipeline/<slug>/SUMMARY.md` → `review-r*.md` → the diff.

## Stop statuses

| Status | Meaning | Your move |
|---|---|---|
| SHIP | Green, no MUST findings | Review the diff yourself, merge |
| NOT_CONFIGURED | TODOs left in pipeline.json / project.md | `/pipeline-setup` |
| NEEDS_INPUT | Spec has open questions | `/spec` |
| DIRTY_TREE / BASELINE_RED | Uncommitted changes / main already failing | Commit / fix main |
| AGENT_MISSING | Project agents not loaded | Check `.claude/agents/`, restart `claude` |
| SPEC_PROBLEM / TEST_DISPUTE | Tests and spec disagree | Fix the spec, rerun |
| TEST_TAMPER / SCOPE_VIOLATION | An agent wrote outside its lane | Inspect; tighten patterns |
| RED_EXHAUSTED / NEEDS_WORK_EXHAUSTED | Fix rounds used up | Take over or split the feature |
| BLOCK | Needs a human decision | Read the review |

## Stack presets (`stacks/*.json`)

| Stack | Build / test | Notes |
|---|---|---|
| dotnet | `dotnet build <sln>` / `dotnet test <sln> --no-build` | Bans `dotnet ef database`, `run`, `publish` |
| node | `<pm> run build` (or `tsc --noEmit`) / `<pm> run test` | Detects npm/pnpm/yarn/bun; sets `CI=true` so vitest/jest don't watch |
| python | `true` / `uv\|poetry\|pdm run pytest -q` | Set build_cmd to your type checker if you have one |
| go | `go build ./...` / `go test ./...` | `_test.go` files are protected |
| rust | `cargo build` / `cargo test` | Inline `#[cfg(test)]` modules can't be protected by path |

Add a stack by dropping a JSON file in `stacks/` with the same keys and adding it to `DETECT_ORDER` in `install.py`.

## Rules for build_cmd / test_cmd
- Non-interactive, exits on its own (no watch mode).
- The reviewer may run only these exact commands (plus a suffix such as a filter) and read-only tools. Extra reviewer commands go in `reviewer_extra_commands`.

## Known limits
- Guards are pattern-matching backstops, not a sandbox. The real enforcement is the orchestrator's git-diff gates and the reviewer re-running the suite.
- Test protection is path-based. Test files the patterns don't match are unprotected; `scripts/test-guards.sh` shows what matches.
- Tests-first means the planner's interfaces must be right; bad ones surface early as `SPEC_PROBLEM`, which is the cheap place to fail.
- Don't add `memory:` to the reviewer: it auto-grants Write/Edit.
- `acceptEdits` is the default overnight mode: shell commands outside `permissions.allow` are denied. If a run stalls, the log names the command; add a narrow allow rule. `PERMISSION_MODE=auto` if your plan has auto mode. Never `bypassPermissions`.

## Example
`examples/iams/project.md`: a filled-in project file for a multi-tenant .NET system (tenant isolation, per-tenant migrations, PII rules).
