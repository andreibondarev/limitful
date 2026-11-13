#!/usr/bin/env bash
# Paradev workspace setup: runs once, in the new worktree, when a workspace is created.
#   1. Copies untracked env files (.env, .env.local, ...) from the root checkout.
#   2. Installs dependencies for whatever stack the repo contains.
# Starts no long-running processes; the dev server is started by run.sh.
set -euo pipefail

ROOT="${SUPERSET_ROOT_PATH:-}"

# --- 1. Copy untracked env files from the root checkout ----------------------
if [ -n "$ROOT" ] && [ -d "$ROOT" ] && [ "$ROOT" != "$PWD" ]; then
  # Anything tracked by git is already in the worktree, so "missing here" means
  # "untracked there". Existing files are never overwritten.
  find "$ROOT" -maxdepth 4 \
    \( -name node_modules -o -name .git -o -name vendor -o -name .venv -o -name dist -o -name .next \) -prune \
    -o -type f \( -name '.env' -o -name '.env.*' -o -name '.dev.vars' \) -print0 |
    while IFS= read -r -d '' src; do
      rel="${src#"$ROOT"/}"
      if [ ! -e "$rel" ]; then
        mkdir -p "$(dirname "$rel")"
        cp "$src" "$rel"
        echo "setup: copied $rel"
      fi
    done
else
  echo "setup: SUPERSET_ROOT_PATH not set; skipping env file copy"
fi

# --- 2. Install dependencies --------------------------------------------------
has() { command -v "$1" >/dev/null 2>&1; }

if [ -f package.json ]; then
  if [ -f bun.lock ] || [ -f bun.lockb ]; then bun install
  elif [ -f pnpm-lock.yaml ]; then pnpm install --frozen-lockfile
  elif [ -f yarn.lock ]; then yarn install
  elif [ -f package-lock.json ]; then npm ci
  else npm install
  fi
fi

if [ -f Gemfile ]; then bundle install; fi

if [ -f uv.lock ] && has uv; then uv sync
elif [ -f poetry.lock ] && has poetry; then poetry install
elif [ -f requirements.txt ]; then
  [ -d .venv ] || python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi

if [ -f go.mod ]; then go mod download; fi
if [ -f Cargo.toml ]; then cargo fetch; fi

echo "setup: done"
