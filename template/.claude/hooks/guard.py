#!/usr/bin/env python3
"""PreToolUse guard for the feature pipeline subagents.

Usage (from a subagent's frontmatter hook):  guard.py <role>
Roles: planner | test-writer | coder | reviewer

Reads the hook JSON on stdin. Exit 0 = allow, exit 2 = block (stderr goes back
to the agent). Configured by .claude/pipeline.json. This is a backstop, not a
sandbox: the orchestrator also checks the git diff after each stage.
"""
import json
import os
import re
import sys

ROLE = sys.argv[1] if len(sys.argv) > 1 else "unknown"
PROJECT = os.path.abspath(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())


def load_cfg():
    try:
        with open(os.path.join(PROJECT, ".claude", "pipeline.json")) as f:
            return json.load(f)
    except Exception:
        return {}


CFG = load_cfg()
TEST_RES = [re.compile(p) for p in CFG.get("test_path_patterns", [r"(^|/)tests?/"])]

FILE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}

GIT_WRITE = {"commit", "push", "reset", "checkout", "switch", "restore", "rebase",
             "merge", "stash", "clean", "branch", "tag", "am", "cherry-pick",
             "revert", "rm", "mv", "apply", "pull", "fetch", "worktree", "config",
             "submodule", "remote", "update-ref", "gc", "filter-branch"}
GIT_READ = {"diff", "log", "show", "status", "rev-parse", "merge-base", "ls-files",
            "blame", "grep", "shortlog", "describe", "cat-file", "name-rev"}

GLOBAL_BANS = [
    (r"\bsudo\b", "sudo is not allowed"),
    (r"\b(curl|wget|ssh|scp|rsync|nc|ncat)\b", "no network tools"),
    (r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*f?\s+(/|~|\$HOME)", "recursive delete outside the repo"),
    (r"\bgit\s+push\b", "git push is never allowed"),
]
PROJECT_BANS = [(b["pattern"], b.get("reason", "banned for this project"))
                for b in CFG.get("banned_commands", []) if b.get("pattern")]

# Shell commands that mutate files; file changes must go through Edit/Write
MUTATORS = re.compile(
    r"(^|\s)(sed\s+-i|perl\s+-[a-z]*i|tee|truncate|mv|cp|rm|rmdir|dd|install|chmod|chown|ln|touch)(\s|$)")

READONLY_BINS = {"git", "grep", "rg", "cat", "head", "tail", "wc", "ls", "find", "sort",
                 "uniq", "cut", "diff", "jq", "pwd", "echo", "tree", "file", "stat",
                 "basename", "dirname", "true", "test", "["}

# Commands the reviewer may run besides READONLY_BINS: the project's own build/test
def _split(cmd):
    return [s.strip() for s in re.split(r"&&|\|\||;|\||\n", cmd or "") if s.strip()]


REVIEWER_PREFIXES = [seg for c in [CFG.get("build_cmd", ""), CFG.get("test_cmd", "")]
                     + CFG.get("reviewer_extra_commands", [])
                     for seg in _split(c) if seg != "true"]


def block(msg):
    print(f"[pipeline guard:{ROLE}] BLOCKED: {msg}", file=sys.stderr)
    sys.exit(2)


def rel(path):
    if not path:
        return ""
    ap = path if os.path.isabs(path) else os.path.join(PROJECT, path)
    return os.path.relpath(os.path.abspath(ap), PROJECT).replace(os.sep, "/")


def is_test(r):
    return any(rx.search(r) for rx in TEST_RES)


def in_pipeline(r):
    return r == ".pipeline" or r.startswith(".pipeline/")


def check_file(tool_input):
    r = rel(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
    if not r:
        return
    if r == ".." or r.startswith("../"):
        block(f"{r} is outside the repository")
    if r.startswith(".git/") or r.startswith(".claude/") or r == ".claude":
        block(f"{r}: pipeline agents may not modify .git/ or .claude/")

    if ROLE == "planner":
        if not in_pipeline(r):
            block(f"planner may only write under .pipeline/ (tried {r})")
    elif ROLE == "test-writer":
        if not (is_test(r) or in_pipeline(r)):
            block(f"test-writer may only write test files or .pipeline/ (tried {r}). "
                  "Do not create production code or stubs; the coder does that. "
                  "If your test path is not recognised, the project's test_path_patterns need updating: "
                  "report it as a SPEC PROBLEM.")
    elif ROLE == "coder":
        if is_test(r):
            block(f"{r} is a test file. Tests are the contract and are read-only for the coder. "
                  "If a test is wrong, write a '## TEST DISPUTE' section in changes.md and stop.")
        base = os.path.basename(r)
        if in_pipeline(r) and (base in {"spec.md", "tests.md", "request.md", "SUMMARY.md", "state.md"}
                               or base.startswith("review")):
            block(f"coder may only write changes.md in .pipeline/ (tried {r})")
    elif ROLE == "reviewer":
        block("reviewer is read-only")


def segments(cmd):
    return [s.strip() for s in re.split(r"&&|\|\||;|\||\n", cmd) if s.strip()]


def has_write_redirect(seg, allow_pipeline=True):
    s = re.sub(r"\d?>&\d", "", seg)                   # 2>&1, >&2
    s = re.sub(r"\d?>>?\s*/dev/null", "", s)           # > /dev/null
    if allow_pipeline:
        s = re.sub(r"\d?>>?\s*\.pipeline/\S+", "", s)  # logs into .pipeline/ (coder/test-writer)
    return ">" in s


def reviewer_may_run(seg):
    return any(seg == p or seg.startswith(p + " ") for p in REVIEWER_PREFIXES)


def check_bash(cmd):
    for pat, why in GLOBAL_BANS + PROJECT_BANS:
        if re.search(pat, cmd):
            block(why)

    if ROLE == "reviewer" and ("$(" in cmd or "`" in cmd):
        block("no command substitution in reviewer shell")

    for seg in segments(cmd):
        words = seg.split()
        while words and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]):
            words = words[1:]  # skip FOO=bar prefixes
        if not words:
            continue
        exe = os.path.basename(words[0])
        sub = words[1] if len(words) > 1 else ""
        bare = " ".join(words)

        if exe == "git" and sub in GIT_WRITE:
            block(f"'git {sub}' is reserved for the orchestrator")

        if ROLE in ("coder", "test-writer"):
            if MUTATORS.search(seg) or has_write_redirect(seg):
                block(f"'{seg}': change files with the Edit/Write tools, not the shell. "
                      "To delete a file, list it under '## Files to delete' in your report.")

        if ROLE == "reviewer":
            if has_write_redirect(seg, allow_pipeline=False):
                block("output redirection is not allowed for the reviewer")
            if reviewer_may_run(bare):
                continue
            if exe not in READONLY_BINS:
                block(f"'{exe}' is not on the reviewer's read-only allowlist "
                      f"(allowed project commands: {REVIEWER_PREFIXES or 'none configured'})")
            if exe == "git" and sub not in GIT_READ:
                block(f"'git {sub}' is not read-only")
            if exe == "find" and re.search(r"-(delete|exec|execdir|ok|fprint|fls)\b", seg):
                block("find with -delete/-exec is not allowed")


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)  # unparseable input: don't wedge the run; the git gates still apply
    tool = data.get("tool_name", "")
    ti = data.get("tool_input", {}) or {}
    if tool in FILE_TOOLS:
        check_file(ti)
    elif tool == "Bash":
        check_bash(ti.get("command", ""))
    sys.exit(0)


if __name__ == "__main__":
    main()
