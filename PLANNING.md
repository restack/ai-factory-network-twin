# AI Factory Network Twin — Planning

- **Status:** Draft v0.3
- **Working repository name:** `ai-factory-network-twin`
- **CLI name:** `aftwin`
- **Owner:** Aaron Yoon
- **Primary language:** Python 3.12+
- **Initial target:** A local Linux host with Docker and Containerlab

### Implementation Status

- **M0:** Complete and merged
- **M1:** Complete
- **M2:** Complete
- **M3:** Complete and merged
- **M4:** Complete and merged
- **M5:** Complete locally; clean-room demo passed, pending PR merge
- **Next:** Final MVP Definition of Done audit

## 1. Decision Summary

This project is not a simulator for an entire AI factory. It is a digital twin for validating the design intent and control plane of an AI cluster network fabric.

The MVP is defined by one statement:

> Read physical topology and IPAM data from NetBox, deterministically generate a dual-plane L3 fabric, and automatically validate the structural invariants and basic connectivity required by an AI fabric.

The initial implementation follows these decisions:

1. NetBox is the source of truth for physical topology, cabling, addressing, and ASNs.
2. Git is the source of truth for platform mappings, rendering templates, validation policies, and test scenarios.
3. Containerlab is an ephemeral runtime for the generated network.
4. The MVP treats NetBox as read-only. Only the development-only `seed` command may write fixture data.
5. The data plane begins with L3 Clos, eBGP, and ECMP.
6. EVPN/VXLAN, RoCE/PFC/ECN, a telemetry stack, and bidirectional synchronization are outside the MVP.
7. The project differentiates itself through AI-fabric-specific validation and reproducible verification, not by recreating a general-purpose NetBox-to-Containerlab exporter.

## 2. Problem Statement

AI cluster network designs commonly distribute their intent across several tools and documents:

- Physical connections among racks, devices, interfaces, and cables
- Loopback, point-to-point, and management addressing and ASNs
- Fabric planes and failure domains
- Intended GPU-node NIC-to-leaf connections
- Configuration files and deployed topology
- Design rules and pre-change validation results

Even when this information is recorded in NetBox, additional automation is required to answer:

- Can the recorded cables and addresses produce an executable lab?
- Is every compute node correctly connected to independent fabric planes?
- Is each leaf connected to every spine in its plane?
- Are there duplicate addresses, missing ASNs, or cross-plane connections?
- Are generated artifacts deterministic and reviewable?
- Does minimum connectivity survive a link or spine failure?

This project closes that gap by compiling NetBox data into an executable topology, rendered configuration, expected state, and validation evidence.

## 3. Product Thesis

A general topology exporter produces deployable YAML. This project must produce four related artifact classes:

1. **Runnable topology** — a Containerlab topology
2. **Rendered configuration** — FRR and Linux endpoint configuration
3. **Expected state** — expected BGP sessions, routes, paths, and reachability
4. **Validation evidence** — static policy and post-deployment verification results

The primary value is the complete validation flow:

```text
NetBox intended state
        ↓
Normalized fabric model
        ↓
Policy and invariant validation
        ↓
Deterministic compilation
        ↓
Containerlab deployment
        ↓
Runtime verification
```

## 4. Goals

### 4.1 MVP Goals

- Select devices and connections by NetBox site or tag.
- Normalize NetBox objects into a typed domain model independent of the external API.
- Perform static validation of a dual-plane L3 Clos fabric.
- Generate a Containerlab topology and FRR startup configuration.
- Configure per-plane VRFs and addressing on Linux compute endpoints.
- Produce byte-stable output for identical input.
- Deploy the lab and verify BGP, routes, and per-plane ping matrices.
- Run unit tests, golden snapshot tests, linting, and type checking in CI.
- Reproduce one golden topology from seed through verification.

### 4.2 Phase 2 Goals

- Link, leaf, and spine failure scenarios
- Before-and-after convergence and reachability comparison
- Drift detection between expected NetBox topology and runtime LLDP/interface state
- An SR Linux backend
- A basic `iperf3` workload traffic profile
- JSON and Markdown validation reports

### 4.3 Phase 3 Goals

- Telemetry based on gNMIc, Prometheus, and Grafana
- Topology and failure-domain visualization
- Multiple sites or DCI topologies
- An EVPN/VXLAN frontend fabric profile
- Integration labs on GitHub Actions self-hosted runners
- Compile triggers based on NetBox webhooks or Event Rules

## 5. Non-Goals

The MVP does not implement or claim to accurately reproduce:

- GPU, CUDA, NCCL, or real distributed-training performance
- InfiniBand credit behavior
- RoCE NIC offload
- ASIC-level PFC, ECN, or DCQCN behavior
- SHARP, adaptive routing, or packet spraying
- 400G/800G switch buffers and queues
- NVLink or NVSwitch
- A NetBox plugin
- Production network configuration push
- Bidirectional reconciliation that writes runtime state back to NetBox
- A general-purpose multi-vendor automation framework

Project descriptions should prefer:

> NetBox-driven AI cluster network digital twin and validation lab

over the term `AI Factory Simulator`.

## 6. Guiding Principles

### 6.1 Native NetBox Objects First

Prefer Site, Location, Rack, Device Role, Device Type, Device, Interface, Cable, Prefix, IP Address, ASN, Platform, and Tag. Use custom fields only for the minimum AI-fabric-specific semantics.

### 6.2 Read-Only Compile Path

`compile`, `validate`, `deploy`, and `verify` never modify NetBox. Only `seed` may write development fixtures.

### 6.3 Explicit Ownership

- **NetBox:** physical objects, cabling, IPAM, and ASNs
- **Git:** renderers, policies, platform mappings, scenarios, and golden tests
- **Containerlab:** ephemeral runtime state
- **`build/`:** reproducible generated artifacts

### 6.4 Deterministic Generation

Sort every object and link explicitly. Exclude timestamps and random identifiers from rendered output. The same source snapshot must produce the same hash and files.

### 6.5 Fail Before Deploy

If cabling, ASN, addressing, or plane data is missing, do not generate a partial topology. Exit with a complete and actionable error list.

### 6.6 Evidence over Successful Exit

A successful `containerlab deploy` is insufficient. Completion requires evidence such as BGP adjacency, expected routes, and endpoint reachability.

## 7. Initial Architecture

```text
┌──────────────────────────────────────────────────────────────┐
│ NetBox                                                       │
│ Site / Device / Interface / Cable / IP / Prefix / ASN       │
└──────────────────────────────┬───────────────────────────────┘
                               │ REST API
                               ▼
┌──────────────────────────────────────────────────────────────┐
│ NetBox Adapter                                               │
│ Query, pagination, API errors, raw snapshot                  │
└──────────────────────────────┬───────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────┐
│ Domain Model                                                 │
│ Fabric, Plane, Node, Interface, Link, Address, ASN           │
└──────────────────────────────┬───────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────┐
│ Policy Engine                                                │
│ Schema checks, AI-fabric invariants, graph validation        │
└──────────────────────────────┬───────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────┐
│ Compiler                                                     │
│ Containerlab YAML, FRR config, endpoint setup, manifest      │
└──────────────────────────────┬───────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────┐
│ Runtime                                                      │
│ Containerlab, FRR routers, Linux compute endpoints           │
└──────────────────────────────┬───────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────┐
│ Verifier                                                     │
│ BGP, routes, per-plane ping matrix, report                   │
└──────────────────────────────────────────────────────────────┘
```

## 8. Source-of-Truth Contract

### 8.1 NetBox-Owned Data

| Data | NetBox object |
| --- | --- |
| Datacenter or lab boundary | Site |
| Rack or zone | Location, Rack |
| Spine, leaf, or compute role | Device Role |
| Platform family | Platform |
| Physical device | Device |
| Physical or logical port | Interface |
| Direct connection | Cable |
| Loopback, P2P, and management ranges | Prefix, IP Address |
| BGP autonomous system | ASN |
| Lab inclusion | Tag |

The exact mechanism that associates an ASN with a device must be resolved as part of the M1 NetBox schema. It must remain explicit, queryable, and fixture-testable.

### 8.2 Git-Owned Data

| Data | Proposed file |
| --- | --- |
| NetBox platform to Containerlab mapping | `config/platform-map.yaml` |
| Fabric policy | `config/policies/*.yaml` or Python rules |
| Jinja templates | `src/aftwin/render/templates/` |
| Golden fixture intent | `fixtures/mini-dual-plane.yaml` |
| Failure scenarios | `scenarios/*.yaml` |
| Expected snapshots | `tests/golden/` |

### 8.3 Runtime-Owned Data

- Container IDs and the runtime management network
- Interface operational state
- BGP adjacency state
- Installed route state
- Ping and workload results

Runtime data is not written back to NetBox. Phase 2 drift reports compare intended and observed state.

## 9. NetBox Data Model

### 9.1 Required Device Roles

- `fabric-spine`
- `fabric-leaf`
- `compute`
- `storage` — late Phase 1 or Phase 2
- `oob` — optional

### 9.2 Required Tags

- `ai-fabric`
- `digital-twin`
- `fixture` — development data only

### 9.3 Minimal Custom Fields

| Field | Object | Type | Purpose |
| --- | --- | --- | --- |
| `fabric_plane` | Device, Interface | Selection: `a`, `b`, `shared` | Plane and failure-domain membership |
| `fabric_role` | Interface | Selection: `uplink`, `downlink`, `host`, `loopback`, `mgmt` | Interface semantics |
| `rail_id` | Interface | Optional integer | Future rail-optimized topology support |

`gpu_type`, `gpu_count`, and `roce_enabled` are not required by the network MVP and are excluded from the initial schema.

### 9.4 Platform Mapping

Containerlab `kind`, image, and renderer mappings belong in Git rather than NetBox custom fields.

```yaml
platforms:
  frr:
    kind: linux
    image: frrouting/frr:<pinned-version>
    renderer: frr
  linux-endpoint:
    kind: linux
    image: ghcr.io/<project>/aftwin-endpoint:<pinned-version>
    renderer: linux_endpoint
```

Pin tested image versions after the first integration test.

## 10. Golden Topology

The MVP golden fixture is named `mini-dual-plane`.

### 10.1 Inventory

- One site
- Two fabric planes: A and B
- Two spines per plane, four total
- Two leaves per plane, four total
- Four compute endpoints
- Two fabric NICs per compute node, one per plane
- One optional storage endpoint after MVP stabilization

### 10.2 Logical Shape

```text
Plane A                            Plane B

 spine-a1       spine-a2           spine-b1       spine-b2
    │  ╲         ╱  │                 │  ╲         ╱  │
    │   ╲       ╱   │                 │   ╲       ╱   │
 leaf-a1       leaf-a2             leaf-b1       leaf-b2
   │  │           │  │               │  │           │  │
 gpu01 gpu02    gpu03 gpu04         gpu01 gpu02    gpu03 gpu04
```

Each compute node is represented by one Linux container with `fabric-a` and `fabric-b` VRFs. Each fabric interface belongs to its corresponding VRF, and per-plane tests use `ip vrf exec`.

### 10.3 Routing Profile

- L3-only Clos
- eBGP between leaves and spines
- A unique ASN per network device
- IPv4 `/31` point-to-point links
- IPv4 `/32` router loopbacks
- Leaves advertise attached endpoint prefixes to spines
- Spines retain ECMP routes
- Compute endpoints use a static default route toward the leaf in each plane VRF
- No direct links or route leaks between Plane A and Plane B

EVPN/VXLAN may be added later as a separate profile for frontend service networks or DCI.

## 11. Domain Model

Renderers must not consume API responses directly.

```text
Fabric
├── name
├── site
├── planes[]
├── nodes[]
├── links[]
└── source_revision

Plane
├── name: a | b
└── failure_domain

Node
├── name
├── role
├── platform
├── plane
├── asn
├── loopback
└── interfaces[]

Interface
├── name
├── role
├── plane
├── addresses[]
└── peer

Link
├── endpoint_a
├── endpoint_b
├── plane
└── kind: fabric | host | management
```

Pydantic validates field-level consistency; NetworkX policies validate graph-level invariants.

## 12. Compile Pipeline

### Stage 1 — Fetch

- Select a site slug or tag.
- Retrieve all required API endpoints with pagination.
- Save the raw response to `build/<site>/source/netbox.json`.
- Never include tokens or secrets in the snapshot.

### Stage 2 — Normalize

- Convert NetBox representations into the domain model.
- Prefer stable names and slugs over object IDs.
- Sort every collection by a stable key.

### Stage 3 — Validate

- Collect schema and policy errors together where possible.
- Report all actionable errors rather than stopping at the first one.
- Classify findings as `error`, `warning`, or `info`.

### Stage 4 — Render

```text
build/<site>/
├── topology.clab.yml
├── configs/
│   ├── routers/<node>/frr.conf
│   └── endpoints/<node>/setup.sh
├── expected-state.json
├── inventory.json
├── manifest.json
└── reports/static-validation.json
```

### Stage 5 — Deploy

- Run `containerlab deploy -t build/<site>/topology.clab.yml`.
- Require successful static validation before deployment.
- Fail if the lab already exists unless `--reconfigure` is explicitly supplied.

### Stage 6 — Verify

- Confirm every expected BGP neighbor is Established.
- Confirm expected prefixes on every router.
- Run a per-plane compute endpoint ping matrix.
- Emit JSON and a console summary.

## 13. Static Validation Rules

### 13.1 General Rules

- Every selected device has the `ai-fabric` tag.
- Every network device has a supported platform.
- Every spine and leaf has an ASN and loopback.
- Every cable endpoint resolves within the selected site.
- IP addresses and device ASNs are unique where required by the selected profile.
- An interface cannot terminate more than one cable.

### 13.2 Plane Rules

- Every spine and leaf belongs to exactly one plane.
- Every compute fabric interface belongs to exactly one plane.
- Both endpoints of a fabric link belong to the same plane.
- A cross-plane link is invalid unless it has an explicit shared or border role.
- Every compute node has at least one fabric interface in both A and B.
- A compute node's A and B interfaces cannot connect to the same leaf device.

### 13.3 Clos Rules

- Every leaf connects to every spine in its plane.
- The base profile forbids spine-to-spine and leaf-to-leaf fabric links.
- Each leaf's uplink degree equals the configured spine count.
- Each host-facing interface connects to exactly one compute or storage interface.
- No spine or leaf is isolated in the graph.

### 13.4 Addressing Rules

- Loopbacks use `/32`.
- Both endpoints of a leaf–spine link belong to the same `/31`.
- Host-facing P2P links use `/31` when required by the profile.
- Management prefixes are excluded from fabric route advertisement.
- Plane A and Plane B address pools do not overlap.

## 14. Runtime Verification Rules

### 14.1 BGP

- Every expected leaf–spine adjacency is Established.
- No unexpected neighbor exists.
- Each node's local ASN matches expected state.

### 14.2 Routing

- Every spine learns all compute prefixes in its plane.
- Every leaf learns compute prefixes attached to remote leaves.
- Prefixes expected to use ECMP meet the minimum next-hop count.
- No prefix from another plane appears in the route table.

### 14.3 Endpoint Reachability

- All Plane A compute interfaces can reach one another.
- All Plane B compute interfaces can reach one another.
- A Plane A VRF cannot reach Plane B addresses.
- Management-network results do not affect fabric reachability status.

### 14.4 Report Example

```text
Static validation: PASS
Nodes compiled: 12
Links compiled: 16
BGP sessions: 8/8 established
Plane A reachability: 12/12 passed
Plane B reachability: 12/12 passed
Cross-plane isolation: PASS
Result: PASS
```

## 15. CLI Contract

The CLI uses Cyclopts.

```bash
# Seed a development NetBox fixture
aftwin seed --fixture fixtures/mini-dual-plane.yaml

# Validate NetBox source data
aftwin validate --site aif-lab

# Generate topology and configuration
aftwin compile --site aif-lab

# Deploy the generated lab
aftwin deploy --site aif-lab

# Verify runtime state
aftwin verify --site aif-lab

# Run the complete local workflow
aftwin lab up --site aif-lab
aftwin lab test --site aif-lab
aftwin lab down --site aif-lab
```

Every command supports human-readable console output and machine-readable JSON.

```bash
aftwin validate --site aif-lab --output json
```

Exit codes:

- `0`: success
- `2`: source or schema validation failure
- `3`: compilation failure
- `4`: deployment failure
- `5`: runtime verification failure
- `10`: configuration or authentication failure

## 16. Proposed Repository Structure

```text
ai-factory-network-twin/
├── PLANNING.md
├── README.md
├── pyproject.toml
├── uv.lock
├── justfile
├── .env.example
├── .gitignore
├── config/
│   ├── platform-map.yaml
│   └── policies/mini-dual-plane.yaml
├── deploy/netbox/
│   ├── README.md
│   ├── docker-compose.override.yml
│   └── initializers/
├── fixtures/
│   ├── smoke.yaml
│   └── mini-dual-plane.yaml
├── scenarios/
│   ├── link-failure.yaml
│   └── spine-failure.yaml
├── src/aftwin/
│   ├── __init__.py
│   ├── cli.py
│   ├── settings.py
│   ├── errors.py
│   ├── netbox/{client,adapter,queries,seeder}.py
│   ├── domain/{models,graph,enums}.py
│   ├── policy/
│   │   ├── engine.py
│   │   ├── findings.py
│   │   └── rules/
│   ├── compiler/{compiler,manifest,expected_state}.py
│   ├── render/
│   │   ├── containerlab.py
│   │   ├── frr.py
│   │   ├── endpoint.py
│   │   └── templates/
│   ├── runtime/{containerlab,executor,lifecycle}.py
│   └── verify/{bgp,routes,reachability,report}.py
├── tests/{unit,contract,integration,fixtures,golden}/
├── build/                  # gitignored
└── scripts/
    ├── bootstrap-netbox.sh
    └── check-prerequisites.sh
```

## 17. Technology Choices

| Area | Choice | Reason |
| --- | --- | --- |
| Language | Python 3.12+ | Strong NetBox and network-automation ecosystem |
| Packaging | `uv` | Fast environment and lockfile management |
| CLI | Cyclopts | Concise typed command definitions |
| Domain validation | Pydantic v2 | Explicit schemas and errors |
| Graph policy | NetworkX | Topology invariants and path analysis |
| NetBox access | pynetbox behind an adapter | Fast implementation with API isolation |
| Rendering | Jinja2 plus PyYAML or ruamel.yaml | Configuration and deterministic YAML generation |
| Testing | pytest | Unit, snapshot, and integration tests |
| Quality | Ruff and Pyright | Formatting, linting, and static typing |
| Task runner | Just | Simple local workflows |

Do not add Nornir, Ansible, Batfish, or SuzieQ to the MVP without a demonstrated requirement. Select one YAML library before M3 based on deterministic-output tests.

## 18. Testing Strategy

### 18.1 Unit Tests

- NetBox response normalization
- Pydantic model validation
- Individual policy rules
- Platform mappings
- Renderer helpers
- Stable sorting and manifest hashing

### 18.2 Contract Tests

- Adapter behavior against stored NetBox API fixtures
- Clear failures when required API fields are missing or changed
- Secret and token redaction

### 18.3 Golden Snapshot Tests

Compare output from `mini-dual-plane` with committed snapshots of:

- `topology.clab.yml`
- Each router's `frr.conf`
- Each endpoint's `setup.sh`
- `expected-state.json`

Intentional changes require snapshot-diff review before updates.

### 18.4 Integration Tests

```text
NetBox up
→ seed
→ validate
→ compile
→ containerlab deploy
→ verify
→ containerlab destroy
```

If privileged networking is impractical on GitHub-hosted runners, mark integration tests as `local` or `self-hosted`.

## 19. Development Workflow

### 19.1 Local Commands

```bash
just bootstrap
just netbox-up
just seed
just validate
just compile
just lab-up
just verify
just lab-down
just test
```

### 19.2 Generated File Policy

- Do not commit `build/`.
- Commit only intentional golden output under `tests/golden/`.
- Record the source hash and compiler version in every build.
- Add a `DO NOT EDIT` header to generated files where the format permits comments.

### 19.3 Secret Handling

```dotenv
NETBOX_URL=http://localhost:8000
NETBOX_TOKEN=replace-me
AFTWIN_SITE=aif-lab
AFTWIN_BUILD_DIR=build
```

- Ignore `.env` in Git.
- Remove tokens from reports and snapshots.
- Never print credentials in command output.

## 20. Milestones

### M0 — Repository Scaffold

**Deliverables**

- Python package and CLI entry point
- `uv`, Ruff, Pyright, and pytest configuration
- `justfile`
- Settings and structured error models
- Empty command skeletons

**Acceptance criteria**

- `uv run aftwin --help` succeeds.
- `just check` runs linting, type checking, and unit tests.
- The basic CI job passes.

### M1 — NetBox Fixtures and Adapter

**Deliverables**

- Local NetBox bootstrap documentation
- A minimal `smoke` fixture for the first vertical slice
- The `mini-dual-plane` golden fixture
- An idempotent `seed` command
- A read-only API adapter
- A raw source snapshot
- The normalized domain model

**Acceptance criteria**

- Seeding either fixture twice does not duplicate objects.
- The adapter retrieves the required devices, interfaces, cables, IPs, and ASNs by site.
- Adapter unit and contract tests pass.

### M2 — Static Policy Engine

**Deliverables**

- Finding and severity models
- General, plane, Clos, and addressing rules
- NetworkX graph construction
- Human-readable and JSON reports

**Acceptance criteria**

- Valid fixtures pass.
- Fixtures with deliberately broken cables, ASNs, or plane data fail with expected rule IDs.
- Multiple errors are reported together.

### M3 — Compiler

**Deliverables**

- Containerlab topology renderer
- FRR configuration renderer
- Endpoint VRF setup renderer
- Expected-state and manifest generation
- Golden snapshot tests

**Acceptance criteria**

- Two compilations of the same source produce the same hash.
- Generated YAML passes Containerlab schema validation.
- Every golden snapshot test passes.

### M4 — Deploy and Verify

**Deliverables**

- Containerlab lifecycle wrapper
- BGP JSON parser
- Route verifier
- Per-plane ping matrix
- Summary report

**Acceptance criteria**

- The golden lab deploys successfully.
- Every expected BGP session is Established.
- Per-plane all-to-all ping succeeds.
- Cross-plane isolation passes.
- Destroy removes related containers and links.

### M5 — Failure Scenarios

**Deliverables**

- Link-down and spine-down scenarios
- Before-and-after state capture
- Recovery validation

**Acceptance criteria**

- Endpoint reachability survives one leaf–spine link failure.
- Plane reachability survives one spine failure.
- The scenario restores the original state.

## 21. Initial Backlog

### P0

1. Project scaffold and CLI
2. Settings and NetBox authentication
3. Domain model
4. NetBox fixture schema
5. Idempotent seeding
6. NetBox adapter
7. Static rule framework
8. `mini-dual-plane` graph validation
9. Containerlab renderer
10. FRR renderer
11. Endpoint VRF setup
12. Golden snapshot tests
13. Deployment wrapper
14. BGP and route verification
15. Ping-matrix verification

### P1

- Failure scenario runner
- Drift detector
- Markdown reports
- SR Linux backend
- `iperf3` traffic profile
- Topology diagram export

### P2

- Telemetry stack
- DCI profile
- EVPN/VXLAN profile
- Webhook-triggered compilation
- Web UI or NetBox plugin

## 22. Initial ADRs

### ADR-001 — Custom Compiler over an NRX-Only Workflow

**Decision:** Use NRX as a reference and baseline rather than as the sole compiler. Maintain a project-specific compiler.

**Reason:** Generic topology export already exists. The project's value is its AI-fabric domain model, invariants, expected state, and runtime verification.

### ADR-002 — L3 Clos before EVPN/VXLAN

**Decision:** Implement an eBGP-based L3-only Clos for the MVP.

**Reason:** It directly supports AI backend fabric validation while avoiding overlay complexity during plane, ECMP, and failure-domain validation.

### ADR-003 — Read-Only NetBox during Compile

**Decision:** Compilation and verification never modify NetBox.

**Reason:** Allowing execution or verification to mutate the authoritative source would reduce safety and reproducibility.

### ADR-004 — FRR First, SR Linux Second

**Decision:** Complete the end-to-end workflow first with the lightweight, freely available FRR/Linux backend.

**Reason:** Validating the compiler and policy architecture is more important initially than vendor images or advanced telemetry.

### ADR-005 — Native Objects and Minimal Custom Fields

**Decision:** Prefer the native NetBox model and limit custom fields to plane, role, and rail metadata.

**Reason:** A simpler schema is easier to adopt in other NetBox environments and avoids plugin dependencies.

## 23. Risks and Mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| The project resembles a generic exporter | Weak differentiation | Keep AI-specific rules and expected state central |
| Dual-plane endpoint networking is complex | MVP delay | Limit endpoints to Linux VRFs and static defaults |
| NetBox schema or API drift | Adapter failures | Isolate the adapter, store contract fixtures, pin versions |
| Container image changes | Poor reproducibility | Pin tested versions or image digests |
| Integration tests require privileges | CI limitations | Separate local or self-hosted integration tests |
| Telemetry is introduced too early | Excess dependencies | Prohibit observability dependencies until M4 passes |
| Users assume hardware-level performance | Misleading conclusions | State the control-plane and functional-twin boundary clearly |

## 24. Definition of Done for the MVP

The MVP is complete when all of the following are true:

- One command prepares a local NetBox fixture.
- NetBox data-quality errors are detected before deployment.
- `mini-dual-plane` compiles deterministically.
- The FRR fabric and Linux compute endpoints run in Containerlab.
- BGP, routes, per-plane reachability, and cross-plane isolation are automatically verified.
- Failures include a rule ID, target object, cause, and remediation hint.
- Golden snapshots and unit tests pass in CI.
- The README clearly states that this is not hardware-level simulation.
- The demo is reproducible in ten or fewer commands or through one `just demo` command.

## 25. Scaffolding Instructions for Coding Agents

1. Implement M0 first; leave later-milestone modules as explicit placeholders.
2. Preserve dependency direction under `src/aftwin`:
   - `domain` does not import NetBox, renderers, or runtime modules.
   - `netbox` converts external data into domain models only.
   - `compiler` does not invoke the runtime.
   - `verify` compares expected state with runtime results only.
3. Add type annotations to every public function and model.
4. Never include secrets in logs or exceptions.
5. Put every subprocess call behind one runtime executor abstraction.
6. Guarantee stable ordering and final newlines for generated artifacts.
7. Do not advance to the next milestone without tests.
8. Record post-MVP ideas in the backlog rather than implementing them early.

## 26. First Implementation Slice

The first vertical slice uses a `smoke` fixture with one spine, one leaf, and one endpoint rather than the complete topology.

```text
NetBox seed
→ fetch
→ normalize
→ validate
→ render topology and configuration
→ deploy
→ verify BGP or static connectivity
```

Expand to `mini-dual-plane` only after this slice succeeds. This validates the NetBox API, renderer, Containerlab runtime, and verifier boundaries early.

## 27. Recommended Demo Story

1. Show the dual-plane topology and cables in NetBox.
2. Run `aftwin validate` and show a passing result.
3. Move one compute cable to a leaf in the wrong plane.
4. Show the cross-plane or redundancy-rule failure.
5. Repair the cable, then compile and deploy.
6. Show BGP and per-plane reachability evidence.
7. Stop one spine and demonstrate preserved reachability.

This sequence communicates the project's intent more clearly than topology generation alone.
