# Autonomous MVP Delivery Goal

Use the following prompt to continue the project across milestones without
losing scope or stopping after intermediate scaffolding.

## Goal Prompt

Create and pursue a persistent goal with this objective:

> Complete the AI Factory Network Twin MVP described in `PLANNING.md`, from
> the current repository state through every remaining milestone and the MVP
> Definition of Done. Work in small, reviewable vertical slices; validate each
> slice against real dependencies where practical; publish it through a pull
> request; merge only after all required checks pass; then continue with the
> next uncompleted slice. Do not stop merely because one milestone, PR, or
> scaffold is complete.

### Sources of Truth

1. Read `PLANNING.md` completely before making milestone decisions.
2. Read `docs/RESEARCH.md`, all relevant files under `docs/adr/`, and the
   current implementation before acting.
3. Treat `PLANNING.md` as the product and milestone authority. Treat accepted
   ADRs as implementation constraints. If they conflict, record and resolve
   the conflict explicitly before implementation.
4. Use current official primary documentation for NetBox, Containerlab, FRR,
   and other technical dependencies. Pin every runtime version or image used
   for reproducible tests.

### Current Baseline

Verify this baseline rather than assuming it remains unchanged:

- M0 repository scaffolding, M1 NetBox fixtures/adapter, M2 static policy
  engine, and M3 deterministic compiler are complete.
- The repository includes pinned local NetBox, versioned `smoke` and
  `mini-dual-plane` fixtures, idempotent seeding, deterministic snapshots,
  normalized domain/graph models, explicit policy profiles, stable rule IDs,
  human/JSON reports, and live NetBox integration tests.
- The next expected slice is M4 deployment and runtime verification.

### Execution Loop

For each uncompleted slice:

1. Inspect the Git branch, worktree, open pull requests, CI state, and relevant
   code. Preserve unrelated user changes.
2. State the exact acceptance criteria being targeted and maintain a short
   working plan.
3. Research unresolved details from official sources before choosing schemas,
   APIs, image versions, or command formats. Capture durable design decisions
   as ADRs.
4. Implement the smallest complete slice that moves an acceptance criterion
   from failing to passing. Do not add post-MVP dependencies or speculative
   abstractions.
5. Add proportionate unit, contract, golden, and integration tests. Reproduce
   meaningful runtime behavior with real NetBox, Containerlab, and FRR where
   the milestone requires it.
6. Run formatting, linting, strict type checking, unit tests, relevant live
   integration tests, package builds, and deterministic-output comparisons.
7. Update README, operational documentation, fixture documentation, ADRs, and
   `PLANNING.md` status when the implementation changes their truth.
8. Commit with Conventional Commits. Push a focused feature branch, open a
   ready-for-review PR with the scope and validation evidence, inspect the
   complete diff and CI, and merge only when checks pass and no actionable
   review issue remains. Delete the merged branch and synchronize local
   `main` before continuing.
9. Re-evaluate the milestone acceptance criteria. Continue immediately to the
   next slice unless the entire MVP Definition of Done is satisfied or a real
   external blocker requires user authority.

### Required Milestone Order and Gates

- **M1 — NetBox Fixtures and Adapter:** Finish `mini-dual-plane`; prove seed
  idempotency; fetch devices, interfaces, cables, addresses, and ASNs by site;
  save a secret-free raw snapshot; normalize it deterministically; pass unit,
  contract, and live NetBox tests.
- **M2 — Static Policy Engine:** Implement stable finding/severity models and
  general, plane, Clos, and addressing rule IDs; report multiple findings in
  human and JSON formats; prove valid and deliberately invalid fixtures.
- **M3 — Compiler:** Render Containerlab topology, FRR configuration, endpoint
  VRF setup, expected state, inventory, and manifest; guarantee stable ordering,
  final newlines, byte-identical repeat builds, and reviewed golden snapshots.
- **M4 — Deploy and Verify:** Add the subprocess executor and Containerlab
  lifecycle boundary; verify BGP JSON, routes, ECMP expectations, per-plane
  reachability, and cross-plane isolation; always clean up integration labs.
- **M5 — Failure Scenarios:** Implement link-down and spine-down scenarios,
  before/after evidence, recovery checks, and restoration of the original lab.

Never bypass a milestone gate simply because later code is easier to write.
Small end-to-end spikes are allowed when they reduce uncertainty, but they do
not mark a milestone complete without its tests and acceptance evidence.

### Parallel Work

Parallel agent work is explicitly authorized when tasks are independent and
bounded. Use it to reduce latency, not to split tightly coupled judgment.

- Good parallel candidates include official-document research, isolated rule
  implementations, independent renderer modules, negative fixture design,
  golden-output review, and test coverage audits.
- Give every sub-agent a concrete deliverable, owned files or read-only scope,
  and explicit acceptance criteria.
- Do not assign overlapping file edits to multiple agents. The primary agent
  owns architecture decisions, integration, final diff review, tests, Git
  history, PR publication, and merge.
- Reconcile every delegated result against `PLANNING.md` and the actual
  worktree. Never accept a sub-agent's completion claim without verification.
- Continue useful primary-agent work while parallel tasks run, and keep the
  user informed during long-running integration or deployment checks.

### Architecture and Safety Constraints

- Preserve dependency direction: `domain` is independent of NetBox, rendering,
  and runtime; `netbox` converts external records to domain models; `compiler`
  never invokes runtime; `verify` compares expected and observed state.
- `compile`, `validate`, `deploy`, and `verify` must not write to NetBox. Only
  the explicitly invoked development `seed` flow may write fixture objects.
- Keep secrets out of logs, exceptions, snapshots, reports, commits, and PRs.
- Keep `build/` and runtime artifacts untracked. Commit only intentional golden
  fixtures and snapshots.
- Put all subprocess execution behind the runtime executor abstraction. Use
  argument arrays, bounded timeouts, captured evidence, and reliable cleanup.
- Do not touch production networks, production NetBox instances, or external
  infrastructure. Destructive operations are limited to explicitly scoped
  ephemeral local lab resources.
- Preserve deterministic sorting, serialization, hashes, and final newlines.
- Do not claim hardware, RDMA, GPU, NCCL, PFC, ECN, or ASIC performance fidelity.

### Blockers and Decision Policy

- Make reasonable, documented, reversible decisions when the plan and official
  sources provide enough context. Do not pause for minor naming or internal
  implementation choices.
- Ask for user direction before expanding product scope, changing an accepted
  architecture decision, spending money, using production credentials, or
  performing an irreversible external action.
- When a dependency or runtime check fails, inspect logs, isolate the cause,
  try safe in-scope alternatives, and preserve evidence. Do not silently skip
  the check or weaken its acceptance criterion.
- Report a genuine blocker only after safe diagnostics and alternatives are
  exhausted. Otherwise keep progressing toward the goal.

### Completion Standard

The goal is complete only when every item under `PLANNING.md` section
"Definition of Done for the MVP" is evidenced in the repository and CI,
including a reproducible seed-to-verify demo, static error detection before
deployment, deterministic `mini-dual-plane` artifacts, runnable FRR and Linux
endpoints, automated routing and isolation verification, actionable failures,
passing golden and unit tests, clear scope documentation, and a demo runnable
in ten or fewer commands or via `just demo`.

Before declaring completion:

1. Run the complete clean-room demo from documented prerequisites.
2. Run all local checks and required live integration suites.
3. Confirm CI is green on `main`.
4. Confirm the worktree is clean and generated runtime resources are removed.
5. Audit `PLANNING.md`, README, ADRs, and commands against actual behavior.
6. Provide a concise final report with merged PRs, evidence, known limitations,
   and exact reproduction commands.
