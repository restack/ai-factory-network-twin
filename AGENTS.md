# AGENTS.md

Source of truth for agents working in this repository. `CLAUDE.md` points here; do not
duplicate these rules in tool-specific files.

## Repository purpose

This project builds and verifies a deterministic, NetBox-driven digital twin of an AI
factory network. Preserve the contracts documented in:

- `README.md` for the executable workflow;
- `docs/DIGITAL_TWIN_ARCHITECTURE.md` for architecture boundaries;
- `docs/policy-rules.md` for validation behavior;
- `PLANNING.md` and `docs/GOAL.md` for scope and sequencing.

Before changing behavior, identify the affected module and explain how the change fits
those contracts.

## Worktree setup

Orca creates one isolated Git worktree per task and runs the committed setup command from
`orca.yaml`.

Manual equivalent:

```bash
./scripts/worktree-setup.sh
```

The script:

- restores `.env` from the canonical checkout when available, otherwise from
  `.env.example`;
- installs the locked Python 3.12 environment with `uv`;
- keeps the shared uv cache off the workspace filesystem when `/data` is available;
- does not start NetBox, Containerlab, or any persistent service.

Do not create per-worktree Conda/Poetry environments or duplicate CUDA/ML runtimes.

## Feedback loop

Use TDD for behavior changes:

```text
reproduce or write a failing test → minimal fix → focused test → just check → review diff
```

Canonical commands:

```bash
just bootstrap   # locked runtime and development dependencies
just lint        # formatting and lint checks
just typecheck   # strict Pyright
just test        # unit/golden tests
just check       # lint + typecheck + test
just build       # package build
```

Run privileged integration suites only when their prerequisites and scope are explicit:

```bash
just test-netbox
just test-containerlab
```

Never claim a check passed without running the real command and reporting its result.

## Unrestricted execution guardrails

Unrestricted/YOLO execution is intentional. Proceed without confirmation for normal
worktree-local edits, tests, builds, dependency installs, local servers, generated-file
cleanup, and ordinary commits.

Before an explicitly requested remote or infrastructure write, state:

```text
Target: <repo/cluster/service>
Mutation: <exact change>
Persistent data deletion: <none or exact target>
Rollback: <revision/command/backup>
```

Ask once immediately before:

- `just netbox-reset` or any Docker volume/database deletion;
- destructive work outside the active worktree;
- force-push or shared-history rewrite;
- secret disclosure/rotation;
- IAM, firewall, SSH trust, or destroy operations;
- actions whose rollback depends on an unverified backup.

`just lab-down` is scoped to the matching disposable Containerlab instance; run it without
an extra prompt when teardown was part of the explicitly requested lab workflow, but still
verify the target site.

Before non-trivial deletion, resolve the absolute target, inspect its mount and Git state,
and establish a recovery path. Treat `/`, `$HOME`, `/data`, `/cache`, workspace parents,
and mount roots as protected.

## Environment and secrets

- `.env` is ignored and local-only. Never commit it.
- The bundled NetBox credential is development-only and must remain loopback-bound.
- Do not print complete environment dumps, token values, auth files, Kubernetes Secret
  values, credential-bearing DSNs, or shell traces containing secrets.
- Report credential names and successful use, not values.
- Never seed or mutate a non-loopback NetBox unless Aaron explicitly requests that exact
  target and the CLI's external-target safeguard is acknowledged.

## Confidentiality

Treat Restack repository context, internal topology, logs, and infrastructure identifiers
as private. Do not paste repository content into web searches, public issues, paste sites,
telemetry, or external MCP/analysis services unless disclosure was explicitly approved.
Public research may be used as inbound context without including private source material
in the query.

## Git and scope

- Work only in the active worktree; do not follow absolute paths from another agent's
  worktree.
- Preserve unrelated user changes and untracked files.
- Use small, atomic Conventional Commits.
- Do not push, open a PR, or deploy unless requested.
- Inspect `git status --short` and the scoped diff before committing.

## Done criteria

A task is done only when:

- changes stay inside the declared scope;
- focused and repository-level checks appropriate to the change pass;
- generated artifacts are intentional and reproducible;
- no secret or confidential payload was exposed;
- external mutations, if any, were read back from the source of truth;
- remaining risk and skipped privileged validation are stated plainly.
