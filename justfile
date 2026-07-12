set dotenv-load := true
set shell := ["bash", "-euo", "pipefail", "-c"]

default:
    @just --list

bootstrap:
    uv sync --all-groups

format:
    uv run ruff format .
    uv run ruff check --fix .

lint:
    uv run ruff format --check .
    uv run ruff check .

typecheck:
    uv run pyright

test:
    uv run pytest

check: lint typecheck test

help:
    uv run aftwin --help

netbox-up:
    docker compose -f deploy/netbox/docker-compose.yml up -d --wait

netbox-down:
    docker compose -f deploy/netbox/docker-compose.yml down

netbox-reset:
    docker compose -f deploy/netbox/docker-compose.yml down --volumes

seed fixture="fixtures/mini-dual-plane.yaml":
    uv run aftwin seed --fixture {{fixture}}

seed-smoke:
    uv run aftwin seed --fixture fixtures/smoke.yaml

validate site="aif-lab" profile="config/policies/mini-dual-plane.yaml":
    uv run aftwin validate --site {{site}} --profile {{profile}}

compile site="aif-lab":
    uv run aftwin compile --site {{site}}

endpoint-image:
    docker build -t aftwin-endpoint:0.1.0 deploy/endpoint

lab-up site="aif-lab":
    uv run aftwin deploy --site {{site}}

verify site="aif-lab":
    uv run aftwin verify --site {{site}}

lab-down site="aif-lab":
    uv run aftwin lab down --site {{site}}

test-netbox: netbox-up
    NETBOX_URL=http://localhost:8000 \
    NETBOX_TOKEN=nbt_aftwindev001.0123456789abcdef0123456789abcdef01234567 \
    AFTWIN_RUN_NETBOX_INTEGRATION=1 \
    uv run pytest -m netbox

test-containerlab: endpoint-image
    AFTWIN_RUN_CONTAINERLAB_INTEGRATION=1 uv run pytest -m containerlab
