#!/usr/bin/env bash
# Paradev workspace teardown: runs in the worktree when the workspace is deleted.
# setup.sh starts nothing long-running, so the only thing to stop is a dev server
# left running by run.sh. Never fails, so it cannot block workspace deletion.
set -u

PID_FILE=".paradev/.dev-server.pid"

kill_tree() {
  local child
  for child in $(pgrep -P "$1" 2>/dev/null); do
    kill_tree "$child"
  done
  kill "$1" 2>/dev/null
}

if [ -f "$PID_FILE" ]; then
  pid="$(cat "$PID_FILE")"
  case "$pid" in
    '' | *[!0-9]*) ;;
    *)
      if kill -0 "$pid" 2>/dev/null; then
        echo "teardown: stopping dev server (pid $pid)"
        kill_tree "$pid"
      fi
      ;;
  esac
  rm -f "$PID_FILE"
fi

echo "teardown: done"
exit 0
