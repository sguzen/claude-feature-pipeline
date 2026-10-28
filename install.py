#!/usr/bin/env python3
"""Install or update the Claude Code feature pipeline into a project.

  install.py [PROJECT_DIR] [--stack dotnet|node|python|go|rust|generic] [--update] [--force] [--dry-run]

Fresh install : copies agents/commands/hooks/scripts, writes .claude/pipeline.json and
                .claude/pipeline/project.md, merges .claude/settings.json, ignores .pipeline/.
--update      : overwrites kit-owned files (agents, commands, hook, scripts) with this kit's
                version. pipeline.json gains missing keys and any new preset bans for its
                stack; project.md and your settings values are never changed.
--force       : on a fresh install, overwrite existing kit files that differ.
"""
import argparse
import glob
import json
import os
import shutil
import stat
import subprocess
import sys

KIT = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(KIT, "template")
STACKS = os.path.join(KIT, "stacks")
VERSION = "1.2.0"
DETECT_ORDER = ["dotnet", "node", "go", "rust", "python"]

# Kit-owned files: replaced on --update
OWNED = [
    ".claude/agents/planner.md", ".claude/agents/test-writer.md",
    ".claude/agents/coder.md", ".claude/agents/reviewer.md",
    ".claude/commands/ship.md", ".claude/commands/spec.md", ".claude/commands/pipeline-setup.md",
    ".claude/hooks/guard.py",
    "scripts/ship-overnight.sh", "scripts/test-guards.sh",
]
# Project-owned files: written once, never overwritten
PROJECT_OWNED = [".claude/pipeline/project.md"]

BASE_ALLOW = [
    "Bash(git status)", "Bash(git status *)", "Bash(git diff)", "Bash(git diff *)",
    "Bash(git log *)", "Bash(git show *)", "Bash(git rev-parse *)", "Bash(git merge-base *)",
    "Bash(git ls-files *)", "Bash(git ls-files)", "Bash(git blame *)",
    "Bash(git add *)", "Bash(git commit *)", "Bash(git switch *)", "Bash(git rm *)",
    "Bash(mv .pipeline/*)",
    "Bash(mkdir *)", "Bash(ls *)", "Bash(cat *)", "Bash(head *)", "Bash(tail *)",
    "Bash(wc *)", "Bash(grep *)", "Bash(rg *)", "Bash(find *)", "Bash(sort *)",
    "Bash(true)",
]
BASE_DENY = [
    "Bash(git push)", "Bash(git push *)", "Bash(git merge *)", "Bash(git rebase *)",
    "Bash(git reset --hard *)", "Bash(git clean *)",
    "Bash(sudo *)", "Bash(curl *)", "Bash(wget *)", "Bash(ssh *)", "Bash(scp *)",
    "Read(./.env)", "Read(./.env.*)", "Read(./**/*.pem)", "Read(./**/*.key)",
    "Read(./**/secrets*.json)", "Read(./**/credentials*.json)",
]
BASE_ENV = {"CLAUDE_CODE_FORK_SUBAGENT": "0"}

warnings = []
actions = []


def warn(msg):
    warnings.append(msg)


def load_stack(name):
    with open(os.path.join(STACKS, f"{name}.json"), encoding="utf-8") as f:
        return json.load(f)


def root_has(target, patterns):
    return any(glob.glob(os.path.join(target, p)) for p in patterns)


def detect(target):
    found = [s for s in DETECT_ORDER if root_has(target, load_stack(s)["detect"])]
    if not found:
        warn("No known stack detected at the repo root. Using 'generic': set build_cmd/test_cmd in .claude/pipeline.json.")
        return "generic"
    if len(found) > 1:
        warn(f"Several stacks detected ({', '.join(found)}); using '{found[0]}'. "
             f"Use --stack to choose, or edit .claude/pipeline.json.")
    return found[0]


def dotnet_vars(target):
    slns = sorted(glob.glob(os.path.join(target, "*.sln")) + glob.glob(os.path.join(target, "*.slnx")))
    if not slns:
        slns = sorted(glob.glob(os.path.join(target, "*", "*.sln")) + glob.glob(os.path.join(target, "*", "*.slnx")))
    if len(slns) > 1:
        warn(f"Multiple solutions found; using {os.path.relpath(slns[0], target)}. Check build_cmd/test_cmd.")
    if slns:
        return {"solution": os.path.relpath(slns[0], target) + " "}
    warn("No .sln/.slnx found; dotnet commands run without a solution path. Check they work from the root.")
    return {"solution": ""}


def node_vars(target, stack):
    if os.path.exists(os.path.join(target, "pnpm-lock.yaml")):
        pm = "pnpm"
    elif os.path.exists(os.path.join(target, "yarn.lock")):
        pm = "yarn"
    elif glob.glob(os.path.join(target, "bun.lock*")):
        pm = "bun"
    else:
        pm = "npm"
    pm_run = f"{pm} run"
    try:
        scripts = json.load(open(os.path.join(target, "package.json"), encoding="utf-8")).get("scripts", {})
    except Exception:
        scripts = {}
    v = {"pm": pm, "pm_run": pm_run}
    if "build" not in scripts:
        if "typecheck" in scripts:
            stack["build_cmd"] = f"{pm_run} typecheck"
        elif os.path.exists(os.path.join(target, "tsconfig.json")):
            stack["build_cmd"] = "npx tsc --noEmit"
        else:
            stack["build_cmd"] = "true"
            warn("No build/typecheck script: build_cmd set to 'true' (no compile gate).")
    if "test" not in scripts:
        stack["test_cmd"] = "TODO: command that runs the full test suite once and exits"
        warn("package.json has no 'test' script; set test_cmd in .claude/pipeline.json.")
    else:
        t = scripts["test"]
        if "vitest" in t and "run" not in t.split():
            warn("Your test script runs vitest; CI=true is set so it shouldn't enter watch mode, but verify it exits.")
    return v


def python_vars(target):
    if os.path.exists(os.path.join(target, "uv.lock")):
        return {"py_run": "uv run ", "py": "uv run python"}
    if os.path.exists(os.path.join(target, "poetry.lock")):
        return {"py_run": "poetry run ", "py": "poetry run python"}
    if os.path.exists(os.path.join(target, "pdm.lock")):
        return {"py_run": "pdm run ", "py": "pdm run python"}
    warn("No uv/poetry/pdm lock found; using 'python3 -m pytest'. Make sure the right virtualenv is active for overnight runs.")
    return {"py_run": "python3 -m ", "py": "python3"}


def fill(obj, v):
    if isinstance(obj, str):
        for k, val in v.items():
            obj = obj.replace("{" + k + "}", val)
        return obj
    if isinstance(obj, list):
        out = []
        for x in obj:
            y = fill(x, v)
            if y not in out:
                out.append(y)
        return out
    if isinstance(obj, dict):
        return {k: fill(x, v) for k, x in obj.items()}
    return obj


def resolve_stack(target, name):
    stack = load_stack(name)
    v = {}
    if name == "dotnet":
        v = dotnet_vars(target)
    elif name == "node":
        v = node_vars(target, stack)
    elif name == "python":
        v = python_vars(target)
    stack = fill(stack, v)
    if stack.get("warning"):
        warn(stack["warning"])
    return stack


def write(path, content, dry):
    actions.append(f"write   {path}")
    if dry:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def copy_owned(target, update, force, dry):
    for rel in OWNED:
        src, dst = os.path.join(TEMPLATE, rel), os.path.join(target, rel)
        exists = os.path.exists(dst)
        same = exists and open(src, "rb").read() == open(dst, "rb").read()
        if same:
            continue
        if exists and not (update or force):
            warn(f"{rel} exists and differs; kept yours (use --update to replace kit files).")
            continue
        actions.append(f"{'update ' if exists else 'add    '} {rel}")
        if not dry:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            if dst.endswith((".sh", ".py")):
                os.chmod(dst, os.stat(dst).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def write_pipeline_json(target, stack, dry):
    path = os.path.join(target, ".claude", "pipeline.json")
    cfg = {
        "stack": stack["name"],
        "build_cmd": stack["build_cmd"],
        "test_cmd": stack["test_cmd"],
        "test_path_patterns": stack["test_path_patterns"],
        "banned_commands": stack["banned_commands"],
        "reviewer_extra_commands": [],
        "max_fix_rounds": 2,
        "max_red_retries": 2,
        "branch_prefix": "feat/",
    }
    if os.path.exists(path):
        try:
            cur = json.load(open(path, encoding="utf-8"))
        except Exception as e:
            sys.exit(f"ERROR: {path} is not valid JSON ({e}). Fix it and rerun.")
        missing = {k: v for k, v in cfg.items() if k not in cur}
        cur.update(missing)  # add new keys only; your values stay
        # Safety bans are additive, like settings deny rules: new preset bans reach existing
        # projects of the same stack. Your own bans and edits are kept.
        new_bans = []
        if cur.get("stack") == stack["name"] and "banned_commands" not in missing:
            have = {b.get("pattern") for b in cur.get("banned_commands", [])}
            new_bans = [b for b in stack["banned_commands"] if b["pattern"] not in have]
            cur.setdefault("banned_commands", []).extend(new_bans)
        if not missing and not new_bans:
            actions.append("keep    .claude/pipeline.json")
            return
        write(path, json.dumps(cur, indent=2) + "\n", dry)
        parts = ([f"added keys: {', '.join(missing)}"] if missing else []) + \
                ([f"new bans: {len(new_bans)}"] if new_bans else [])
        actions[-1] = f"upgrade .claude/pipeline.json ({'; '.join(parts)})"
        return
    write(path, json.dumps(cfg, indent=2) + "\n", dry)


def write_project_md(target, stack, dry):
    path = os.path.join(target, ".claude", "pipeline", "project.md")
    if os.path.exists(path):
        actions.append("keep    .claude/pipeline/project.md")
        return
    tpl = open(os.path.join(TEMPLATE, ".claude", "pipeline", "project.md"), encoding="utf-8").read()
    tpl = tpl.replace("## Data & migrations\n",
                      f"## Data & migrations\n<!-- Stack default: {stack['migration_hint']} -->\n")
    write(path, tpl, dry)


def merge_settings(target, stack, dry):
    path = os.path.join(target, ".claude", "settings.json")
    data = {}
    if os.path.exists(path):
        try:
            data = json.load(open(path, encoding="utf-8"))
        except Exception as e:
            sys.exit(f"ERROR: {path} is not valid JSON ({e}). Fix it and rerun.")
    before = json.dumps(data, sort_keys=True)
    env = data.setdefault("env", {})
    for k, v in {**BASE_ENV, **stack.get("env", {})}.items():
        env.setdefault(k, v)  # never override a value you set
    perms = data.setdefault("permissions", {})
    for key, extra in (("allow", BASE_ALLOW + stack.get("allow", [])),
                       ("deny", BASE_DENY + stack.get("deny", []))):
        lst = perms.setdefault(key, [])
        for rule in extra:
            if rule not in lst:
                lst.append(rule)
    if json.dumps(data, sort_keys=True) != before:
        write(path, json.dumps(data, indent=2) + "\n", dry)
        actions[-1] = "merge   .claude/settings.json"


def gitignore(target, dry):
    path = os.path.join(target, ".gitignore")
    lines = open(path, encoding="utf-8", errors="replace").read().splitlines() if os.path.exists(path) else []
    if any(l.strip() in (".pipeline", ".pipeline/", "/.pipeline/", "/.pipeline") for l in lines):
        return
    actions.append("append  .gitignore (.pipeline/)")
    if not dry:
        with open(path, "a", encoding="utf-8") as f:
            if lines and lines[-1].strip():
                f.write("\n")
            f.write(".pipeline/\n")


def main():
    ap = argparse.ArgumentParser(description="Install the Claude Code feature pipeline into a project.")
    ap.add_argument("project", nargs="?", default=".")
    ap.add_argument("--stack", choices=DETECT_ORDER + ["generic"])
    ap.add_argument("--update", action="store_true", help="replace kit-owned files with this version")
    ap.add_argument("--force", action="store_true", help="overwrite differing kit files on install")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    target = os.path.abspath(a.project)
    if not os.path.isdir(target):
        sys.exit(f"ERROR: {target} is not a directory")
    try:
        top = subprocess.run(["git", "-C", target, "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, check=True).stdout.strip()
        if os.path.realpath(top) != os.path.realpath(target):
            warn(f"{target} is not the git root ({top}). Claude Code finds .claude/ by walking up, "
                 "but /ship's git gates assume the repo root.")
    except Exception:
        warn("Not a git repository. /ship needs git; run `git init` and commit first.")

    name = a.stack or detect(target)
    stack = resolve_stack(target, name)

    copy_owned(target, a.update, a.force, a.dry_run)
    write_pipeline_json(target, stack, a.dry_run)
    write_project_md(target, stack, a.dry_run)
    merge_settings(target, stack, a.dry_run)
    gitignore(target, a.dry_run)
    write(os.path.join(target, ".claude", "pipeline", "VERSION"), VERSION + "\n", a.dry_run)

    print(f"Feature pipeline {VERSION} -> {target}  (stack: {name}{', dry run' if a.dry_run else ''})")
    for x in actions:
        print("  " + x.replace(target + os.sep, ""))
    for w in warnings:
        print("  ! " + w)
    if not a.update:
        print("""
Next:
  1. cd into the project, run `claude`, accept the trust prompt if shown (frontmatter hooks need a trusted folder).
  2. /pipeline-setup      verifies build/test commands and test paths, drafts .claude/pipeline/project.md with you
  3. bash scripts/test-guards.sh
  4. git add .claude scripts .gitignore && git commit -m "chore: add feature pipeline"
  5. /spec <feature>  then  scripts/ship-overnight.sh <slug>""")


if __name__ == "__main__":
    main()
