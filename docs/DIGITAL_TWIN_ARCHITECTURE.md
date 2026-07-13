# Multi-Vendor Digital Twin Architecture

- **Status:** Proposed post-MVP architecture
- **Scope:** Ethernet AI fabrics, open-source assurance, and a secure edge
- **Related documents:** [`PLANNING.md`](../PLANNING.md),
  [`RESEARCH.md`](RESEARCH.md), and [`policy-rules.md`](policy-rules.md)

## 1. Purpose

The MVP proves that NetBox intent can be compiled into a deterministic dual-plane L3
fabric, deployed in Containerlab, and verified with control-plane and reachability
evidence. The next architecture should increase operational fidelity without implying
that a software lab reproduces switch silicon, RDMA NICs, or line-rate AI workloads.

This document defines two post-MVP extensions:

1. A multi-vendor Ethernet digital twin built from production-like network operating
   systems, with FortiGate at the security boundary and InfiniBand modeled separately.
2. A layered assurance workflow in which Batfish performs pre-deployment analysis and
   SuzieQ performs post-deployment operational-state analysis.

The architecture favors open Ethernet interoperability, including the direction of the
[Ultra Ethernet Consortium](https://ultraethernet.org/), and treats RoCEv2 as a design
and policy concern rather than as behavior that Containerlab can reproduce accurately.

## 2. Architecture Decisions

1. **Ethernet is the primary executable twin.** The main runtime profiles model an L3
   Ethernet AI fabric using FRR first and vendor NOS backends later.
2. **InfiniBand is a separate validation domain.** NetBox may represent InfiniBand
   devices, rails, ports, and cabling, but the project does not claim to emulate
   InfiniBand control-plane, congestion, SHARP, or adaptive-routing behavior.
3. **Arista and Juniper are candidate fabric platforms.** A default deployment profile
   should use the same NOS in both planes. Mixed-vendor planes belong in an explicit
   interoperability profile.
4. **FortiGate is a secure edge, not a fabric switch.** A FortiGate HA pair may provide
   north-south routing, policy enforcement, NAT, and stateful failover outside the
   compute fabric.
5. **Open-source assurance tools complement the project verifier.** Batfish and SuzieQ
   add breadth, but neither replaces the AI-fabric-specific invariant engine or the
   deterministic expected-state comparison.
6. **Every claim is bounded by a fidelity contract.** Reports must identify what was
   validated and what requires physical hardware.

## 3. Digital Twin Fidelity Contract

The term *digital twin* has different meanings at different layers. This project uses
the following contract.

| Level | What the project can validate | Representative evidence |
| --- | --- | --- |
| Intent and inventory | Devices, roles, rails, planes, interfaces, cables, IPAM, and ASNs | NetBox snapshot and static findings |
| Configuration and control plane | Rendered configuration, BGP policy, adjacencies, routes, ECMP paths, and isolation | Compiler artifacts, Batfish answers, and NOS state |
| Operational behavior | Link and node failures, route withdrawal, reachability, drift, and convergence indicators | Scenario reports, SuzieQ assertions, and direct collectors |
| Hardware and workload performance | Not reproduced by the software lab | Requires physical switches, RDMA NICs, traffic generators, and GPU workloads |

The executable twin must not claim to reproduce:

- ASIC buffer allocation or queue scheduling
- Hardware PFC, ECN, or DCQCN behavior
- RoCE NIC offload, RDMA queue pairs, or retransmission behavior
- 400/800 GbE throughput and latency
- InfiniBand subnet management, credits, SHARP, or adaptive routing
- NCCL collective performance

Linux traffic control and software traffic generators may create controlled loss,
delay, jitter, rate, or incast conditions. Those scenarios are functional experiments,
not hardware-performance predictions.

## 4. Target Logical Architecture

```text
                         External services / WAN
                                  |
                        FortiGate-A == FortiGate-B
                          HA and security policy
                                  |
                          Border leaf/router pair
                             /             \
                    Ethernet Plane A   Ethernet Plane B
                     spine and leaf     spine and leaf
                             \             /
                         Dual-homed compute nodes

          Separate domain: InfiniBand rails, switches, links, and intent
          represented in NetBox and checked by structural policy rules
```

### 4.1 Ethernet AI Fabric

The Ethernet fabric remains a dual-plane, rail-aware Clos. Each plane is an independent
failure domain, and compute endpoints attach to both planes without cross-plane fabric
links. The baseline remains L3 eBGP and ECMP; EVPN/VXLAN is an optional profile rather
than a prerequisite.

RoCEv2 and Ultra Ethernet concepts influence future validation rules, including:

- rail symmetry and independent failure domains
- MTU consistency
- ECMP path diversity and entropy assumptions
- QoS-class consistency
- PFC and ECN configuration presence and scope
- oversubscription and link-speed intent
- telemetry coverage for drops, congestion, and queue state

These are configuration and topology checks unless physical hardware evidence is
explicitly attached to a report.

### 4.2 Secure Edge

The FortiGate HA pair sits outside the compute fabric. It may connect to redundant
border leaves or dedicated border routers and advertise or receive routes through BGP.
The secure-edge profile should validate:

- HA membership, heartbeat links, and primary/secondary state
- redundant northbound and southbound connectivity
- expected BGP peers and route filters
- default-route propagation and withdrawal
- firewall policy and NAT intent
- session-preserving failover where the virtual platform supports it

A small lab may combine border routing and firewall functions. A reference-like lab
should keep fabric forwarding, border routing, and stateful security as separate roles.

### 4.3 InfiniBand Domain

InfiniBand should use its own device roles, platform metadata, rails, and validation
rules. The first implementation is an intent-only profile that verifies:

- rail-aligned server connectivity
- leaf/spine or fat-tree completeness
- port counts and cable placement
- redundant fabric-manager connectivity
- isolated failure domains
- expected storage and compute fabric separation

An InfiniBand object may appear in NetBox and reports, but it must not be emitted as an
Ethernet NOS node merely to make the topology executable.

## 5. Runtime Profiles

| Profile | Purpose | Expected runtime |
| --- | --- | --- |
| `functional-frr` | Fast deterministic development and CI baseline | FRR and Linux containers |
| `ethernet-srlinux` | First model-driven NOS backend and gNMI integration | Nokia SR Linux containers |
| `ethernet-arista` | EOS configuration and operational validation | User-supplied cEOS image |
| `ethernet-juniper` | Junos configuration and operational validation | User-supplied cRPD or vJunos image |
| `multivendor-interop` | Explicit routing and management-protocol interoperability tests | Selected NOS combination |
| `secure-edge-fortigate` | BGP, policy, NAT, and HA failure scenarios | User-supplied FortiGate VM image |
| `infiniband-intent` | Structural and inventory validation without emulation claims | NetBox and policy engine only |

The FRR profile remains the required CI reference. Vendor profiles are optional
integration tests until their images, licenses, boot times, and host requirements can
be supported reliably.

## 6. Platform Backend Boundary

The current compiler assumes that every routed node uses FRR. Post-MVP work should
replace this assumption with explicit backend contracts.

```text
Platform backend
├── capability declaration
├── configuration renderer
├── Containerlab node renderer
├── startup and readiness checks
└── observed-state collector
```

Each backend declares capabilities such as eBGP, EVPN, gNMI, NETCONF, structured CLI,
or HA. A profile is rejected before compilation when a required capability is missing.

Vendor-specific collectors normalize their output into a common observed-state model.
The verifier continues to compare that model with the vendor-neutral expected state;
vendor command output must not leak into domain policy rules.

## 7. Open-Source Assurance Workflow

### 7.1 Layered Pipeline

```text
NetBox intended state
        |
        v
Domain policy engine ---- topology and AI-fabric invariants
        |
        v
Deterministic compiler --- topology, vendor configs, expected state
        |                                      |
        |                                      +--> Batfish
        |                                           pre-deployment analysis
        v
Containerlab runtime
        |
        +--> Direct NOS collectors -------- fast profile-specific verification
        |
        +--> SuzieQ ------------------------ network-wide observed state
        |
        v
Expected-versus-observed report
```

The tools answer different questions:

| Layer | Primary question | Authority |
| --- | --- | --- |
| Domain policy engine | Is the NetBox design a valid dual-plane AI fabric? | Project-specific rules |
| Batfish | What should the rendered configurations permit or route before deployment? | Configuration analysis |
| Direct collectors | Did this lab establish the exact sessions and routes expected by the compiler? | Runtime NOS output |
| SuzieQ | What is the network-wide operational state, and where is it inconsistent? | Normalized observed state |

### 7.2 Batfish

Batfish is a candidate pre-deployment assurance backend. The compiler supplies rendered
configurations and topology metadata; a Batfish adapter turns selected questions into
the project's finding and evidence models.

Initial questions should cover:

- expected reachability and isolation
- routing loops and black holes
- BGP session and route-policy intent
- path diversity before and after a modeled failure
- configuration comparison between two builds

Adoption requires a time-boxed compatibility spike for every supported renderer. A
vendor profile must not advertise Batfish assurance unless its generated syntax is
parsed correctly and its answers are covered by golden tests.

### 7.3 SuzieQ

SuzieQ is a candidate operational assurance backend. It collects and normalizes state
from a running multi-vendor topology, then supports topology, routing, interface, and
network-wide consistency assertions.

Initial uses should cover:

- interface and LLDP topology drift
- BGP and route state across all nodes
- duplicate addressing or inconsistent MTU observations
- before-and-after failure snapshots
- reusable assertions for the Markdown and JSON reports

SuzieQ must not become the source of truth. NetBox owns intended state, the compiler
owns expected state, and SuzieQ contributes observed evidence. Direct collectors remain
available for the lightweight FRR profile and for vendor features that SuzieQ cannot
normalize.

### 7.4 gNMI and Telemetry

gNMIc may collect streaming telemetry from capable vendor backends and export metrics
to Prometheus. It is complementary to SuzieQ: streaming telemetry explains changes over
time, while SuzieQ provides queryable network-wide state. Neither changes NetBox during
the read-only compile and verify workflow.

## 8. Data Ownership

| Data | Owner |
| --- | --- |
| Devices, platforms, roles, cables, rails, IPAM, and ASNs | NetBox |
| Profiles, backend mappings, renderers, assurance queries, and scenarios | Git |
| Generated topology, configs, expected state, and manifests | Compiler build output |
| Adjacencies, routes, interfaces, telemetry, and HA state | Runtime collectors |
| Findings and comparison evidence | Validation report |

Batfish and SuzieQ caches are derived data. They must be reproducible or disposable and
must never silently override NetBox or compiler-owned state.

## 9. Image, License, and CI Policy

- Do not redistribute proprietary NOS or security-appliance images.
- Require users to import vendor images from authorized sources.
- Keep image tags in platform mappings and validate compatibility rather than exact
  image digests by default.
- Detect missing images and licenses before deployment with actionable messages.
- Mark VM-backed and licensed profiles as local or self-hosted integration tests.
- Keep secrets, license files, vendor credentials, and collected sensitive state out of
  Git, snapshots, and reports.
- Continue to run the FRR profile in ordinary CI so that the core workflow remains open
  and reproducible.

## 10. Delivery Sequence

1. **M6 — Platform Backend Abstraction:** remove FRR assumptions and implement SR Linux
   as the second end-to-end backend.
2. **M7 — Batfish Pre-Deployment Assurance:** validate supported rendered configs and
   import selected answers as project findings.
3. **M8 — Multi-Vendor Operational Assurance:** add one production-like NOS profile,
   normalize observed state, and evaluate SuzieQ against the same expected state.
4. **M9 — FortiGate Secure Edge:** add border and firewall roles, HA topology, routing,
   policy, and failure scenarios.
5. Add the second production-like NOS and the explicit interoperability profile only
   after the single-vendor profile is stable.
6. Keep InfiniBand as a separate intent-validation track until a credible executable
   backend and hardware validation environment exist.

## 11. Acceptance Principles

A post-MVP profile is complete only when:

- the same NetBox intent compiles deterministically for the selected backend;
- expected state remains vendor-neutral;
- unsupported capabilities fail before deployment;
- static, pre-deployment, and runtime findings identify their evidence source;
- failure scenarios restore the original state;
- reports state the applicable fidelity level and hardware limitations;
- the open FRR baseline continues to pass without proprietary dependencies.
