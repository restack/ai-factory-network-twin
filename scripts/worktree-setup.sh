#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

log() {
  printf '[worktree-setup] %s\n' "$*"
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf '[worktree-setup] required command not found: %s\n' "$1" >&2
    exit 1
  fi
}

require_command uv
require_command git

# New worktrees do not contain ignored files. Prefer the canonical checkout's local
# environment, but never print it. Fall back to the committed development-only example.
if [[ ! -e .env ]]; then
  env_source=''
  if [[ -n "${ORCA_ROOT_PATH:-}" && -f "${ORCA_ROOT_PATH}/.env" ]]; then
    env_source="${ORCA_ROOT_PATH}/.env"
  elif [[ -f .env.example ]]; then
    env_source='.env.example'
  fi

  if [[ -n "$env_source" ]]; then
    install -m 0600 "$env_source" .env
    log 'created local .env without printing its contents'
  else
    log 'no .env source found; continuing without one'
  fi
else
  log 'kept existing .env'
fi

# Keep the shared package cache away from the small workspace filesystem. Allow an
# explicit caller-provided UV_CACHE_DIR to win.
if [[ -z "${UV_CACHE_DIR:-}" && -d /data && -w /data ]]; then
  export UV_CACHE_DIR=/data/uv-cache
fi

# `/data` and `/cache` are separate filesystems on the workstation, so uv cannot
# hardlink cached packages into worktree virtualenvs. Make the intentional fallback
# explicit and quiet while still keeping bulky cache data off the workspace volume.
if [[ -z "${UV_LINK_MODE:-}" && "${UV_CACHE_DIR:-}" == /data/* ]]; then
  export UV_LINK_MODE=copy
fi

log "syncing locked Python environment (cache: ${UV_CACHE_DIR:-uv default}, link: ${UV_LINK_MODE:-uv default})"
uv sync --all-groups --frozen --python 3.12

log 'setup complete'
