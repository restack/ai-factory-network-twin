#!/usr/bin/env bash
set -euo pipefail

export NETBOX_URL="${NETBOX_URL:-http://localhost:8000}"
export NETBOX_TOKEN="${NETBOX_TOKEN:-nbt_aftwindev001.0123456789abcdef0123456789abcdef01234567}"

compose=(docker compose -f deploy/netbox/docker-compose.yml)

cleanup() {
    status=$?
    trap - EXIT INT TERM
    if [[ -f build/aif-lab/topology.clab.yml ]]; then
        uv run aftwin lab down --site aif-lab >/dev/null 2>&1 || true
    fi
    "${compose[@]}" down >/dev/null 2>&1 || true
    exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if [[ -f build/aif-lab/topology.clab.yml ]]; then
    uv run aftwin lab down --site aif-lab >/dev/null 2>&1 || true
fi
"${compose[@]}" up -d --wait
docker build -t aftwin-endpoint:0.1.0 deploy/endpoint
uv run aftwin seed --fixture fixtures/mini-dual-plane.yaml
uv run aftwin validate --site aif-lab
uv run aftwin compile --site aif-lab
uv run aftwin deploy --site aif-lab
uv run aftwin verify --site aif-lab
uv run aftwin scenario run --site aif-lab --path scenarios/link-failure.yaml
uv run aftwin scenario run --site aif-lab --path scenarios/spine-failure.yaml
uv run aftwin verify --site aif-lab
uv run aftwin lab down --site aif-lab

trap - EXIT INT TERM
"${compose[@]}" down
