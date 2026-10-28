---
description: Plan a feature interactively (planner + your answers) and approve the spec for /ship
argument-hint: <feature request>
---

Plan this feature with me. Do not write any code in this command.

Request: $ARGUMENTS

1. Make a slug: kebab-case, max 40 chars, from the request, prefixed with today's date `YYYYMMDD-`. Run dir = `.pipeline/<slug>/`. Create it and write the request verbatim to `<run_dir>/request.md`.
2. Delegate to the `planner` subagent with: the run dir path and the slug. Wait for it to finish.
3. Show me the Acceptance criteria and Open questions from `<run_dir>/spec.md`.
4. If there are open questions: ask me, append my answers under `## Answers` in request.md, and run the planner again. Repeat until there are none.
5. Ask me to approve. On approval, change `Status: DRAFT` to `Status: APPROVED` in spec.md.
6. Tell me the exact command for tonight: `scripts/ship-overnight.sh <slug>`.
