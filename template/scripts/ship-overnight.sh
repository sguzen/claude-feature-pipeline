#!/usr/bin/env bash
# Run /ship headless, keep the machine awake (lid closed included), log everything,
# and notify when done.
#
#   scripts/ship-overnight.sh <approved-slug>          # recommended: after /spec
#   scripts/ship-overnight.sh "add X to Y, details..."  # only for small, unambiguous work
#
# Env:
#   PERMISSION_MODE  acceptEdits (default) | auto   (auto = classifier-reviewed, if your plan has it)
#   NTFY_TOPIC       optional: also push to ntfy.sh/<topic> (phone)
set -euo pipefail

[ $# -ge 1 ] || { echo "usage: $0 <approved-slug | \"feature request\">"; exit 1; }
ARGS="$*"
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

mkdir -p .pipeline/logs
STAMP="$(date +%Y%m%d-%H%M%S)"
LOG=".pipeline/logs/ship-$STAMP.log"
MODE="${PERMISSION_MODE:-acceptEdits}"

echo "ship: '$ARGS'  mode=$MODE  log=$LOG"

set +e
# Keep the machine awake: systemd (Linux), caffeinate (macOS), else nothing
if command -v systemd-inhibit >/dev/null; then
  AWAKE=(systemd-inhibit --what=sleep:idle:handle-lid-switch --who="claude-ship" --why="feature pipeline")
elif command -v caffeinate >/dev/null; then
  AWAKE=(caffeinate -dimsu)   # note: macOS still sleeps on lid close unless on power + external display
else
  AWAKE=(); echo "warning: no sleep inhibitor found; keep the machine awake yourself"
fi

${AWAKE[@]+"${AWAKE[@]}"} claude -p "/ship $ARGS" --permission-mode "$MODE" 2>&1 | tee "$LOG"
RC=${PIPESTATUS[0]}
set -e

# Pull the status line from the newest SUMMARY.md, if one was written
SUMMARY="$(ls -t .pipeline/*/SUMMARY.md 2>/dev/null | head -1 || true)"
TITLE="ship finished (exit $RC)"
[ -n "$SUMMARY" ] && TITLE="$(head -1 "$SUMMARY" | sed 's/^# //')"

if command -v notify-send >/dev/null; then notify-send -u normal "Feature pipeline" "$TITLE" || true
elif command -v osascript >/dev/null; then osascript -e "display notification \"$TITLE\" with title \"Feature pipeline\"" || true
fi
if [ -n "${NTFY_TOPIC:-}" ]; then
  curl -s -H "Title: Feature pipeline" -d "$TITLE" "https://ntfy.sh/$NTFY_TOPIC" >/dev/null || true
fi

echo "$TITLE"
[ -n "$SUMMARY" ] && echo "summary: $SUMMARY"
exit "$RC"
