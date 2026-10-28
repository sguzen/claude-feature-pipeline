#!/usr/bin/env python3
"""PreToolUse guard for the feature pipeline subagents.

Usage (from a subagent's frontmatter hook):  guard.py <role>
Roles: planner | test-writer | coder | reviewer

Reads the hook JSON on stdin. Exit 0 = allow, exit 2 = block (stderr goes back
to the agent). Configured by .claude/pipeline.json. Fails CLOSED: any internal
error blocks the tool call, because Claude Code treats any exit code other
than 2 as non-blocking. This is a backstop, not a sandbox: the orchestrator
also checks the git diff after each stage.
"""
import json
import os
import re
import sys

ROLE = sys.argv[1] if len(sys.argv) > 1 else "unknown"
ROLES = {"planner", "test-writer", "coder", "reviewer"}
PROJECT = os.path.realpath(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())

FILE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}

GIT_WRITE = {"commit", "push", "reset", "checkout", "switch", "restore", "rebase",
             "merge", "stash", "clean", "branch", "tag", "am", "cherry-pick",
             "revert", "rm", "mv", "apply", "pull", "fetch", "worktree", "config",
             "submodule", "remote", "update-ref", "gc", "filter-branch", "notes",
             "replace", "symbolic-ref", "init", "clone"}
GIT_READ = {"diff", "log", "show", "status", "rev-parse", "merge-base", "ls-files",
            "blame", "grep", "shortlog", "describe", "cat-file", "name-rev"}
GIT_OPTS_WITH_ARG = {"-C", "-c", "--git-dir", "--work-tree", "--namespace",
                     "--exec-path", "--super-prefix", "--config-env"}

GLOBAL_BANS = [
    (r"\bsudo\b", "sudo is not allowed"),
    (r"\b(curl|wget|ssh|scp|rsync|nc|ncat)\b", "no network tools"),
    (r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*f?\s+(/|~|\$HOME)", "recursive delete outside the repo"),
]

# Shell commands that mutate files; file changes must go through Edit/Write
MUTATORS = re.compile(
    r"(^|\s)(sed\s+-[a-zA-Z]*i|perl\s+-[a-zA-Z]*i|tee|truncate|mv|cp|rm|rmdir|dd|install|"
    r"chmod|chown|ln|touch|xargs)(\s|$)")
# Inline interpreter one-liners can write anything (python -c "open(...).write(...)")
INLINE_CODE = re.compile(
    r"(^|\s)(python[0-9.]*|node|deno|bun|perl|ruby|php|pwsh|powershell|bash|sh|zsh|dash)"
    r"\s+(-[a-zA-Z]*[ce]\b|--eval\b|--command\b|-Command\b)")

READONLY_BINS = {"git", "grep", "rg", "cat", "head", "tail", "wc", "ls", "find", "sort",
                 "uniq", "cut", "diff", "jq", "pwd", "echo", "tree", "file", "stat",
                 "basename", "dirname", "true", "test", "["}


def block(msg):
    print(f"[pipeline guard:{ROLE}] BLOCKED: {msg}", file=sys.stderr)
    sys.exit(2)


def load_cfg():
    path = os.path.join(PROJECT, ".claude", "pipeline.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)  # invalid JSON -> exception -> fail closed


def mask_quotes(cmd):
    """Replace quoted strings with a placeholder so operators inside them are ignored."""
    return re.sub(r"'[^']*'|\"(?:[^\"\\]|\\.)*\"", " Q ", cmd)


def split_segments(cmd):
    return [s.strip() for s in re.split(r"&&|\|\||;|\||\n", cmd or "") if s.strip()]


CFG, TEST_RES, PROJECT_BANS, REVIEWER_PREFIXES = {}, [], [], []


def init():
    """Load config inside main()'s try, so a bad pipeline.json fails closed."""
    global CFG, TEST_RES, PROJECT_BANS, REVIEWER_PREFIXES
    CFG = load_cfg()
    TEST_RES = [re.compile(p) for p in CFG.get("test_path_patterns", [r"(^|/)tests?/"])]
    PROJECT_BANS = [(b["pattern"], b.get("reason", "banned for this project"))
                    for b in CFG.get("banned_commands", []) if b.get("pattern")]
    for pat, _ in PROJECT_BANS:
        re.compile(pat)
    # Commands the reviewer/planner may run besides READONLY_BINS: the project's own build/test
    REVIEWER_PREFIXES = [seg for c in [CFG.get("build_cmd", ""), CFG.get("test_cmd", "")]
                         + CFG.get("reviewer_extra_commands", [])
                         for seg in split_segments(mask_quotes(c)) if seg != "true"]
    REVIEWER_PREFIXES.append("python3 .claude/hooks/lanes.py")  # read-only commit-lane check


def rel(path):
    if not path:
        return ""
    ap = path if os.path.isabs(path) else os.path.join(PROJECT, path)
    return os.path.relpath(os.path.realpath(ap), PROJECT).replace(os.sep, "/")


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


def has_write_redirect(seg, allow_pipeline=True):
    s = re.sub(r"(=>|->|>=|<=>)", "", seg)            # lambdas/comparisons left unquoted
    s = re.sub(r"\d?>&\d", "", s)                       # 2>&1, >&2
    s = re.sub(r"\d?>>?\s*/dev/null", "", s)             # > /dev/null
    if allow_pipeline:
        s = re.sub(r"\d?>>?\s*\.pipeline/\S+", "", s)    # logs into .pipeline/ (coder/test-writer)
    return ">" in s


def git_subcommand(words):
    """First real git subcommand, skipping global options like -C <dir>, -c k=v, --no-pager."""
    i = 1
    while i < len(words):
        w = words[i]
        if w in GIT_OPTS_WITH_ARG:
            i += 2
        elif w.startswith("-"):
            i += 1  # --git-dir=x, --no-pager, -P, --bare ...
        else:
            return w
    return ""


def reviewer_may_run(seg):
    return any(seg == p or seg.startswith(p + " ") for p in REVIEWER_PREFIXES)


def check_bash(cmd):
    for pat, why in GLOBAL_BANS + PROJECT_BANS:
        if re.search(pat, cmd):
            block(why)
    if "$(" in cmd or "`" in cmd or "<(" in cmd:
        block("no command substitution in pipeline agent shells; run the commands separately")

    masked = mask_quotes(cmd)
    for seg in split_segments(masked):
        words = seg.split()
        while words and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]):
            words = words[1:]  # skip FOO=bar prefixes
        if not words:
            continue
        exe = os.path.basename(words[0])
        bare = " ".join(words)
        sub = git_subcommand(words) if exe == "git" else (words[1] if len(words) > 1 else "")

        if exe == "git" and sub in GIT_WRITE:
            block(f"'git {sub}' is reserved for the orchestrator")
        if exe == "git" and sub == "push":
            block("git push is never allowed")

        if ROLE in ("coder", "test-writer"):
            if INLINE_CODE.search(seg):
                block(f"'{seg}': inline interpreter code is not allowed; use the Edit/Write tools "
                      "or the project's build/test commands.")
            if MUTATORS.search(seg) or has_write_redirect(seg):
                tip = ("To remove a file, overwrite it with a minimal valid stub (empty, or e.g. just "
                       "`package x` in Go) and list it under '## Files to delete' in changes.md."
                       if ROLE == "coder" else "")
                block(f"'{seg}': change files with the Edit/Write tools, not the shell. {tip}".strip())
            if exe == "find" and re.search(r"-(delete|exec|execdir|ok|okdir|fprint|fls)\b", seg):
                block("find with -delete/-exec is not allowed")

        if ROLE in ("reviewer", "planner"):
            if has_write_redirect(seg, allow_pipeline=False):
                block(f"output redirection is not allowed for the {ROLE}")
            if reviewer_may_run(bare):
                continue
            if exe not in READONLY_BINS:
                block(f"'{exe}' is not on the {ROLE}'s read-only allowlist "
                      f"(allowed project commands: {REVIEWER_PREFIXES or 'none configured'})")
            if exe == "git" and sub not in GIT_READ:
                block(f"'git {sub}' is not read-only")
            if exe == "find" and re.search(r"-(delete|exec|execdir|ok|okdir|fprint|fls)\b", seg):
                block("find with -delete/-exec is not allowed")


def main():
    if ROLE not in ROLES:
        block(f"unknown role '{ROLE}' in hook configuration")
    init()
    data = json.load(sys.stdin)
    tool = data.get("tool_name", "")
    ti = data.get("tool_input", {}) or {}
    if tool in FILE_TOOLS:
        check_file(ti)
    elif tool == "Bash":
        check_bash(ti.get("command", ""))
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:  # fail closed: a crashing guard must not become "allow"
        print(f"[pipeline guard:{ROLE}] BLOCKED: guard error ({type(e).__name__}: {e}). "
              "Check .claude/pipeline.json and .claude/hooks/guard.py.", file=sys.stderr)
        sys.exit(2)
