---
description: Configure the feature pipeline for this repo - verify build/test commands and test paths, draft project.md with me
---

Set up the feature pipeline for this repository with me. Change only `.claude/pipeline.json` and `.claude/pipeline/project.md`.

1. **Commands.** Read `.claude/pipeline.json`. Run `build_cmd` and `test_cmd` exactly as written. If either fails for a configuration reason (wrong solution path, missing script, watch mode that never exits), propose a fix, show me, and update the file once I agree. Each must be a single non-interactive command that exits on its own. If the suite is red for real failures, tell me: /ship will refuse to start until main is green.
2. **Test paths.** Run `git ls-files` and apply `test_path_patterns`. Show me: how many files match, 10 sample matches, and any file that looks like a test but does NOT match (and vice versa: production files that match). Adjust the patterns with my approval. Production code must never match; every test file must.
3. **project.md.** Explore the codebase (structure, layering, data access, migrations tooling, test setup, any CLAUDE.md, ADRs, `.claude/MEMORY.md`/`.claude/ERRORS.md`, available skills). Draft every section of `.claude/pipeline/project.md` with concrete, checkable rules taken from what the code actually does. Mark anything you inferred rather than saw with "(inferred)". Show me the draft, apply my corrections, then remove the TODO line at the top.
4. Finish with: the final build/test commands, pattern match counts, and the reminder to commit `.claude/` and `scripts/` before the first /ship.
