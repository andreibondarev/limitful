#!/usr/bin/env bash
# Paradev Run button: starts the Lifelog web app on a port that is free for this workspace.
#
# Paradev does not assign port ranges, so each workspace derives a preferred port
# from its name (stable across restarts) and walks upward until it finds a free one.
# Set PORT yourself to force a specific port.
set -euo pipefail

PID_FILE=".paradev/.dev-server.pid"

port_in_use() {
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1 && return 0
  fi
  (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null
}

if [ -z "${PORT:-}" ]; then
  name="${SUPERSET_WORKSPACE_NAME:-$(basename "$PWD")}"
  hash="$(printf '%s' "$name" | cksum | cut -d' ' -f1)"
  PORT=$((4000 + hash % 1000)) # 4000-4999; the app's own default, 4747, is in this range, so a busy port moves on
  tries=0
  while port_in_use "$PORT"; do
    PORT=$((PORT + 1))
    tries=$((tries + 1))
    if [ "$tries" -ge 200 ]; then
      echo "run: no free port found near $PORT" >&2
      exit 1
    fi
  done
fi
export PORT
echo "run: dev server on http://localhost:$PORT"

# Record our PID so teardown.sh can stop the server; exec keeps the PID the same.
echo $$ >"$PID_FILE"

# The Lifelog web app. It serves the real data folder (~/Limitful, or $LIMITFUL_DATA).
exec uv run limitful serve --port "$PORT"
