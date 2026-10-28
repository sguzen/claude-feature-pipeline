#!/usr/bin/env bash
# 1) Unit-test the guard hook against a fixed synthetic config (stack-independent).
# 2) Show which files in THIS repo the configured test_path_patterns treat as tests.
set -uo pipefail
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
G="$ROOT/.claude/hooks/guard.py"
[ -f "$G" ] || { echo "guard not found at $G"; exit 1; }

SANDBOX="$(mktemp -d)"
trap 'rm -rf "$SANDBOX"' EXIT
mkdir -p "$SANDBOX/.claude"
cat > "$SANDBOX/.claude/pipeline.json" <<'EOF'
{
  "build_cmd": "make build",
  "test_cmd": "make test",
  "test_path_patterns": ["(^|/)tests?/", "\\.Tests?/", "_test\\.go$", "\\.(test|spec)\\.[jt]sx?$"],
  "banned_commands": [{"pattern": "\\bmigrate\\s+deploy\\b", "reason": "never apply migrations"}]
}
EOF

pass=0; fail=0
t() { # role expect tool input-json
  local role=$1 expect=$2 tool=$3 input=$4
  printf '{"tool_name":"%s","tool_input":%s}' "$tool" "$input" \
    | CLAUDE_PROJECT_DIR="$SANDBOX" python3 "$G" "$role" >/dev/null 2>&1
  local rc=$?; local got=allow; [ $rc -eq 2 ] && got=block
  if [ "$got" = "$expect" ]; then pass=$((pass+1)); else fail=$((fail+1)); echo "FAIL [$role] $tool $input -> $got (want $expect)"; fi
}

# planner
t planner allow Write '{"file_path":".pipeline/x/spec.md"}'
t planner block Write '{"file_path":"src/app/service.py"}'
t planner block Write '{"file_path":".claude/agents/planner.md"}'
# test-writer
t test-writer allow Write '{"file_path":"tests/unit/test_orders.py"}'
t test-writer allow Write '{"file_path":"src/App.Tests/OrderTests.cs"}'
t test-writer allow Write '{"file_path":"web/src/cart.test.ts"}'
t test-writer allow Write '{"file_path":"pkg/orders/orders_test.go"}'
t test-writer block Write '{"file_path":"src/app/orders.py"}'
t test-writer allow Bash  '{"command":"make test 2>&1 | tail -60 > .pipeline/x/tests-red.log"}'
t test-writer block Bash  '{"command":"git commit -m wip"}'
t test-writer block Bash  '{"command":"touch src/app/stub.py"}'
# coder
t coder allow Write '{"file_path":"src/app/orders.py"}'
t coder block Edit  '{"file_path":"tests/integration/test_orders.py"}'
t coder block Edit  '{"file_path":"web/src/cart.spec.tsx"}'
t coder block Edit  '{"file_path":"pkg/orders/orders_test.go"}'
t coder allow Write '{"file_path":".pipeline/x/changes.md"}'
t coder block Write '{"file_path":".pipeline/x/spec.md"}'
t coder block Write '{"file_path":"../other-repo/file.py"}'
t coder allow Bash  '{"command":"make test"}'
t coder block Bash  '{"command":"sed -i s/a/b/ tests/unit/test_orders.py"}'
t coder block Bash  '{"command":"echo x > src/app/hack.py"}'
t coder block Bash  '{"command":"npx prisma migrate deploy"}'
t coder block Bash  '{"command":"git checkout -- tests/"}'
t coder block Bash  '{"command":"curl https://example.com"}'
t coder block Bash  '{"command":"git push origin HEAD"}'
# reviewer
t reviewer allow Bash '{"command":"git diff abc123..HEAD"}'
t reviewer allow Bash '{"command":"git diff abc..HEAD --stat && make build && make test 2>&1 | tail -40"}'
t reviewer allow Bash '{"command":"rg -n \"logger\" src/"}'
t reviewer block Bash '{"command":"make clean"}'
t reviewer block Bash '{"command":"echo VERDICT > .pipeline/x/review.md"}'
t reviewer block Bash '{"command":"python3 --version"}'
t reviewer block Bash '{"command":"git commit -am x"}'
t reviewer block Bash '{"command":"find . -name \"*.py\" -delete"}'
t reviewer block Bash '{"command":"cat $(echo src/a.py)"}'
t reviewer block Write '{"file_path":"src/a.py"}'

echo "guard logic: $pass passed, $fail failed"

# --- this repo's real patterns ---
CFG="$ROOT/.claude/pipeline.json"
if [ -f "$CFG" ] && git -C "$ROOT" rev-parse >/dev/null 2>&1; then
  git -C "$ROOT" ls-files | python3 -c '
import json, re, sys
cfg = json.load(open(sys.argv[1]))
rx = [re.compile(p) for p in cfg.get("test_path_patterns", [])]
files = [l.strip() for l in sys.stdin if l.strip()]
hits = [f for f in files if any(r.search(f) for r in rx)]
print(f"this repo: {len(hits)} of {len(files)} tracked files count as tests")
for f in hits[:8]: print("   test:", f)
sus = [f for f in files if f not in hits and not f.startswith((".claude/", "scripts/", ".pipeline/"))
       and re.search(r"(?i)(test|spec)", f)]
if sus:
    print(f"   check these {len(sus)} non-matching files with test-like names:")
    for f in sus[:8]: print("   ?", f)
' "$CFG"
fi

[ $fail -eq 0 ]
