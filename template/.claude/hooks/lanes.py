#!/usr/bin/env python3
"""Commit-lane check for a pipeline branch.

  python3 .claude/hooks/lanes.py <BASE> <slug>      (run from the repo root)

Rule: commits whose subject starts with `test(<slug>)` may touch only test files
(per test_path_patterns in .claude/pipeline.json); every other commit on
BASE..HEAD may touch no test file. Renames are split into delete + add, so moving
a test file out of the test tree is caught.

Exit 0 = clean, 1 = violation(s), 2 = error. One line of output per problem.
"""
import json
import re
import subprocess
import sys


def main():
    if len(sys.argv) != 3:
        print("usage: lanes.py <BASE> <slug>")
        return 2
    base, slug = sys.argv[1], sys.argv[2]
    with open(".claude/pipeline.json", encoding="utf-8") as f:
        cfg = json.load(f)
    rx = [re.compile(p) for p in cfg.get("test_path_patterns", [r"(^|/)tests?/"])]

    def is_test(path):
        return any(r.search(path) for r in rx)

    out = subprocess.run(
        ["git", "log", "--reverse", "--no-renames", "--name-only", "--format=@%h %s", f"{base}..HEAD"],
        capture_output=True, text=True, check=True).stdout

    commits, cur = [], None
    for line in out.splitlines():
        if line.startswith("@"):
            sha, _, subject = line[1:].partition(" ")
            cur = (sha, subject, [])
            commits.append(cur)
        elif line.strip() and cur:
            cur[2].append(line.strip())

    prefix = f"test({slug})"
    bad = 0
    for sha, subject, files in commits:
        test_lane = subject.startswith(prefix)
        wrong = [f for f in files if is_test(f) != test_lane]
        if wrong:
            bad += 1
            kind = "non-test files in a test commit" if test_lane else "test files in a non-test commit"
            shown = ", ".join(wrong[:5]) + (f" (+{len(wrong) - 5} more)" if len(wrong) > 5 else "")
            print(f"lanes: VIOLATION {sha} \"{subject}\": {kind}: {shown}")
    if bad:
        return 1
    print(f"lanes: ok ({len(commits)} commits)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"lanes: ERROR {type(e).__name__}: {e}")
        sys.exit(2)
