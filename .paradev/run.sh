#!/usr/bin/env bash
# Paradev Run button: starts the dev server on a port that is free for this workspace.
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
  PORT=$((4000 + hash % 1000)) # 4000-4999, clear of the root checkout's default 3000
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

if [ -f package.json ] && grep -q '"dev"[[:space:]]*:' package.json; then
  if [ -f bun.lock ] || [ -f bun.lockb ]; then pm="bun run"; sep=""
  elif [ -f pnpm-lock.yaml ]; then pm="pnpm run"; sep=""
  elif [ -f yarn.lock ]; then pm="yarn run"; sep=""
  else pm="npm run"; sep="--"
  fi
  # Next.js, Express, etc. read $PORT; Vite and Astro only take a --port flag.
  if grep -Eq '"dev"[[:space:]]*:[[:space:]]*"[^"]*(vite|astro)' package.json; then
    exec $pm dev $sep --port "$PORT"
  fi
  exec $pm dev
elif [ -x bin/dev ]; then
  exec bin/dev
elif [ -x bin/rails ]; then
  exec bin/rails server -p "$PORT"
elif [ -f manage.py ]; then
  exec python3 manage.py runserver "$PORT"
fi

rm -f "$PID_FILE"
echo "run: no dev server found (no package.json \"dev\" script, bin/dev, bin/rails or manage.py)." >&2
echo "run: add your start command to .paradev/run.sh and make it listen on \$PORT." >&2
exit 1
