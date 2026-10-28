#!/usr/bin/env bash
# Run /ship headless: verify trust, keep the machine awake, cap wall time, log
# everything, and notify with THIS run's result.
#
#   scripts/ship-overnight.sh <approved-slug>          # recommended: after /spec
#   scripts/ship-overnight.sh "add X to Y, details..."  # only for small, unambiguous work
#
# Env:
#   PERMISSION_MODE    acceptEdits (default) | auto   (auto = classifier-reviewed, if your plan has it)
#   WALL_TIMEOUT       max run time, default 6h (needs `timeout`; macOS: brew install coreutils)
#   NTFY_TOPIC         optional: also push to ntfy.sh/<topic> (phone)
#   SKIP_TRUST_CHECK=1 skip the folder-trust preflight (only if you know hooks are active)
set -euo pipefail

[ $# -ge 1 ] || { echo "usage: $0 <approved-slug | \"feature request\">"; exit 1; }
ARGS="$*"
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

# 1. Folder trust: without it Claude Code skips the subagents' guard hooks silently.
if [ "${SKIP_TRUST_CHECK:-0}" != "1" ]; then
  TRUSTED="$(python3 - "$ROOT" <<'PY'
import json, os, sys
root = sys.argv[1]
try:
    projects = json.load(open(os.path.expanduser("~/.claude.json"), encoding="utf-8")).get("projects", {})
except Exception:
    print("unknown"); sys.exit()
cands = {root, os.path.realpath(root)}
print("yes" if any(projects.get(p, {}).get("hasTrustDialogAccepted") for p in cands) else "no")
PY
)"
  case "$TRUSTED" in
    yes) ;;
    no) echo "error: $ROOT is not a trusted folder, so the pipeline's guard hooks would not run." >&2
        echo "       Run 'claude' here once and accept the trust prompt (or SKIP_TRUST_CHECK=1)." >&2
        exit 1 ;;
    *) echo "warning: could not read ~/.claude.json to verify folder trust; continuing" >&2 ;;
  esac
fi

mkdir -p .pipeline/logs
STAMP="$(date +%Y%m%d-%H%M%S)"
LOG=".pipeline/logs/ship-$STAMP.log"
MODE="${PERMISSION_MODE:-acceptEdits}"
MARK=".pipeline/logs/.start-$STAMP"
touch "$MARK"   # only SUMMARY.md files newer than this belong to this run

# 2. Keep the machine awake. Lid-switch inhibition can be refused by polkit
#    (e.g. over SSH); probe it and fall back to sleep/idle only.
AWAKE=()
if command -v systemd-inhibit >/dev/null; then
  if systemd-inhibit --what=sleep:idle:handle-lid-switch true 2>/dev/null; then
    AWAKE=(systemd-inhibit --what=sleep:idle:handle-lid-switch --who="claude-ship" --why="feature pipeline")
  elif systemd-inhibit --what=sleep:idle true 2>/dev/null; then
    AWAKE=(systemd-inhibit --what=sleep:idle --who="claude-ship" --why="feature pipeline")
    echo "warning: lid-close inhibition refused; keep the lid open" >&2
  else
    echo "warning: systemd-inhibit unavailable here (no session bus?); keep the machine awake yourself" >&2
  fi
elif command -v caffeinate >/dev/null; then
  AWAKE=(caffeinate -dimsu)   # macOS still sleeps on lid close unless on power + external display
else
  AWAKE=(); echo "warning: no sleep inhibitor found; keep the machine awake yourself" >&2
fi

# 3. Wall-clock cap so a hung test runner or retry loop can't run all night.
if command -v timeout >/dev/null; then TO=(timeout "${WALL_TIMEOUT:-6h}")
elif command -v gtimeout >/dev/null; then TO=(gtimeout "${WALL_TIMEOUT:-6h}")
else TO=(); echo "warning: no 'timeout' command; the run has no wall-clock cap" >&2
fi

echo "ship: '$ARGS'  mode=$MODE  log=$LOG"
set +e
${AWAKE[@]+"${AWAKE[@]}"} ${TO[@]+"${TO[@]}"} \
  claude -p "/ship $ARGS" --permission-mode "$MODE" < /dev/null 2>&1 | tee "$LOG"
RC=${PIPESTATUS[0]}
set -e
[ "$RC" -eq 124 ] && echo "ship: hit WALL_TIMEOUT (${WALL_TIMEOUT:-6h})" | tee -a "$LOG"

# 4. Only trust a SUMMARY.md written during this run.
# (not -newer "$LOG": tee keeps writing the log, so it is always newer than the summary)
SUMMARY="$(find .pipeline -mindepth 2 -maxdepth 2 -name SUMMARY.md -newer "$MARK" 2>/dev/null | head -1 || true)"
rm -f "$MARK"
if [ -n "$SUMMARY" ]; then
  TITLE="$(head -1 "$SUMMARY" | sed 's/^# //')"
else
  TITLE="ship failed before writing a summary (exit $RC) - see $LOG"
fi

if command -v notify-send >/dev/null; then
  notify-send -u normal "Feature pipeline" "$TITLE" || true
elif command -v osascript >/dev/null; then
  osascript -e 'on run argv' -e 'display notification (item 1 of argv) with title "Feature pipeline"' -e 'end run' "$TITLE" || true
fi
if [ -n "${NTFY_TOPIC:-}" ]; then
  curl -fsS -H "Title: Feature pipeline" -d "$TITLE" "https://ntfy.sh/$NTFY_TOPIC" >/dev/null || true
fi

echo "$TITLE"
[ -n "$SUMMARY" ] && echo "summary: $SUMMARY"
exit "$RC"
