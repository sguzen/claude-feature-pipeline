---
description: Settle a TEST_DISPUTE with me, record the decisions in the spec, and mark the run for /ship to resume
argument-hint: <slug>
---

Settle the test dispute for run `.pipeline/$ARGUMENTS/`. Change only files in that run dir: no code, no tests, no git.

1. Read `state.md`. If it doesn't say `STATUS=TEST_DISPUTE`, say so in one line and stop.
2. Read the `## TEST DISPUTE` section of `changes.md`, the disputed tests, and the ACs they cover. Show me one line per item, nothing else:
   `D1  <test name>: coder says <why> → proposes <fix>  [my read: test wrong | coder wrong | unclear]`
   "My read" is your one-phrase judgement against the spec.
3. Ask me to decide each item: accept (the test is wrong; change it as proposed), reject (the test stands; the coder must satisfy it as written), or my own wording. "all accept" or "1,3 accept, 2 reject" is fine.
4. Append to `spec.md`, creating the section at the end if missing:
   ```
   ## Amendments
   A<n> (D<k>, <YYYY-MM-DD>): accepted|rejected — <one line: what the test must assert now, or why it stands>
   ```
   Number amendments after any existing ones. If an accepted item changes what an AC means, also edit that AC line in place and append ` (amended A<n>)`.
5. In `state.md` add the line `RESUME=dispute`.
6. Final line only: `Resolved: <a> accepted, <r> rejected. Resume: /ship $ARGUMENTS  (or scripts/ship-overnight.sh $ARGUMENTS)`
