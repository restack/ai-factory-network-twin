# Multi-Vendor Digital Twin Architecture

> A production-aligned executable network twin and infrastructure-intent validation
> architecture for Ethernet AI fabrics.

- **Status:** Proposed post-MVP architecture
- **Scope:** Ethernet AI fabrics, infrastructure intent, open-source assurance, and a
  secure edge
- **Related documents:** [`PLANNING.md`](../PLANNING.md),
  [`RESEARCH.md`](RESEARCH.md), and [`policy-rules.md`](policy-rules.md)

## 1. Purpose and Scope

The MVP proves that assigned addressing and physical topology from NetBox can be
compiled into a deterministic dual-plane L3 fabric, deployed in Containerlab, and
verified with control-plane and reachability evidence. The post-MVP architecture
increases fidelity without implying that a software lab reproduces switch silicon,
RDMA NICs, facility power, or line-rate AI workloads.

The architecture has two related but distinct tracks:

1. **Executable network twin.** Compile vendor-neutral intent into FRR or vendor NOS
   configurations, run the selected backend, normalize observed state, and compare it
   with vendor-neutral expected state.
2. **Infrastructure-intent validation.** Validate non-executable physical intent such as
   rack and power dependencies, rail placement, port capacity, breakout allocation, and
   GPU-to-NIC affinity without claiming to emulate those systems.

Both tracks share NetBox source data, policy profiles, stable findings, provenance, and
evidence contracts. They do not share the same fidelity claim. A report must say
whether a result was statically validated, emulated in software, observed from a
runtime, or left for physical validation.

The design favors open Ethernet interoperability, including the direction of the
[Ultra Ethernet Consortium](https://ultraethernet.org/). RoCEv2, QoS, PFC, and ECN are
configuration and intent concerns unless physical evidence is attached explicitly.
InfiniBand remains a separate intent-validation domain.

## 2. Architecture Decisions

1. **Ethernet is the primary executable twin.** FRR and Linux remain the open baseline;
   vendor NOS backends add configuration and control-plane fidelity.
2. **Infrastructure intent is a separate validation track.** Rack, power, capacity,
   PCIe, NUMA, GPU, and NIC relationships may be validated as data, but Containerlab is
   not their runtime.
3. **Logical network domains do not require separate physical fabrics.** OOB, service,
   GPU compute, and storage are distinct traffic and policy domains. A deployment
   profile decides whether they use independent fabrics or a converged fabric with
   logical isolation.
4. **Plane and rail are different dimensions.** A rail identifies topology-aligned
   endpoint connectivity; a plane identifies an independent fabric carrying a portion
   of that rail. Attachments are identified by both when multiplane is used.
5. **Expected state is vendor-neutral.** Backend renderers generate vendor
   configuration in parallel with expected-state generation. Vendor output never
   becomes policy intent.
6. **Arista and Juniper are candidate production-like platforms.** Default profiles use
   the same NOS in all planes. Mixed-vendor combinations require an explicitly named
   interoperability profile.
7. **FortiGate is a secure edge, not a fabric switch.** It protects north-south and
   service-domain boundaries; it is not implicitly placed in the GPU compute or OOB
   forwarding path.
8. **InfiniBand is not emitted as Ethernet.** NetBox may represent InfiniBand rails,
   switches, ports, managers, and cables, but this project does not claim to emulate its
   control plane or congestion behavior.
9. **Assurance tools contribute evidence, not authority.** Batfish, SuzieQ, direct
   collectors, and gNMI telemetry are admitted per backend only after compatibility and
   normalization tests.
10. **The open baseline cannot depend on proprietary artifacts.** Licensed NOS and
    appliance images remain optional local or self-hosted profiles.
11. **Every result is bound to provenance and a fidelity claim.** Build identity,
    deployed runtime identity, observation metadata, and evidence source remain
    distinguishable.

## 3. Terminology and Identity Dimensions

The following terms are intentionally orthogonal.

| Term | Definition | Example |
| --- | --- | --- |
| Network domain | A logical traffic, policy, and operational role | `oob`, `service`, `gpu-compute`, `storage` |
| Fabric instance | One physical or emulated switching/routing system | `gpu-a`, `gpu-b`, `converged`, `oob-1` |
| Plane | An independent fabric slice used for bandwidth, scale, or failure isolation | `a`, `b`, or a numbered multiplane value |
| Rail | A repeated endpoint-to-leaf alignment, commonly associated with a GPU/NIC position | `rail-0` through `rail-7` |
| Attachment | The connection of an endpoint interface or PF to a domain, fabric, rail, and plane | `gpu01/pf0 → gpu-a/rail-0/plane-a` |
| Failure domain | A shared dependency whose loss can affect multiple objects | switch, rack, power feed, control plane |
| Runtime profile | A selected set of topology, backend, capability, image, and assurance requirements | `functional-frr` |
| Evidence envelope | Non-deterministic observation metadata surrounding deterministic findings | collection time and collector version |

A rail must not be inferred from a plane name. In a multiplane design, each rail may be
split across two or more planes. The canonical attachment coordinate is therefore:

```text
(network_domain, fabric_instance, rail_id, plane_id, endpoint, interface_or_pf)
```

Fields that do not apply to a profile remain absent rather than being assigned a
misleading placeholder. For example, an OOB attachment normally has no GPU rail.

## 4. Fidelity and Claim Contract

| Fidelity level | Valid claims | Representative evidence |
| --- | --- | --- |
| Source and intent | Inventory selection, roles, locations, interfaces, cables, assigned addresses, ASNs, rails, and declared dependencies | NetBox snapshot, Git policy identity, static findings |
| Generated configuration | Backend capability, rendered configuration, routing policy, and expected topology | Compiler artifacts, manifest, schema validation, Batfish answers where admitted |
| Emulated control plane | BGP adjacency, routes, ECMP paths, isolation, and software reachability in the selected runtime | Direct collector output and expected-versus-observed findings |
| Emulated operational behavior | Link or node failure, withdrawal, restoration, drift, and software-lab convergence indicators | Scenario report, SuzieQ evidence where admitted, telemetry envelope |
| Physical infrastructure intent | Rack, power, breakout, media, capacity, rail, and hardware-affinity constraints | NetBox physical model, hardware profile, dependency findings |
| Hardware and workload performance | Not reproduced by the software lab | Physical switches, NICs, traffic generators, telemetry, and GPU workloads |

The executable twin must not claim to reproduce or predict:

- ASIC buffer allocation, queue scheduling, or hardware drop behavior
- hardware PFC, ECN, or DCQCN behavior under production load
- RoCE NIC offload, RDMA queue pairs, or retransmission behavior
- physical 400/800 GbE throughput, latency, or residual capacity
- facility power availability or cooling behavior
- InfiniBand subnet management, credits, SHARP, or adaptive routing
- NCCL collective performance or job-completion time

Linux traffic control and software traffic generators may create controlled loss,
delay, jitter, rate, or incast conditions. These are functional experiments in the
recorded lab environment, not hardware-performance predictions.

## 5. Logical Domains and Physical Realization

### 5.1 Logical Architecture

Compute and storage endpoints attach to network domains in parallel. The domains are
not a serial forwarding chain.

```text
                              External services / WAN
                                         |
                               FortiGate HA pair
                                  secure edge
                                         |
                              Border router pair
                                         |
                              Service / customer domain
                                /        |        \
                         support     compute     storage
                          nodes       nodes       nodes
                                        |
                +-----------------------+-----------------------+
                |                                               |
       GPU compute attachments                         Storage attachments
         rail x plane matrix                        separate or converged
       Plane A     Plane B

       OOB management domain -------------------- management ports and BMCs

       Separate validation domain --------------- InfiniBand intent
```

The secure edge normally protects external and service-domain paths. OOB access may
have its own firewall, bastion, or management boundary, but it is not assumed to pass
through the same FortiGate pair.

Typical attachments are shown below; a profile may omit or converge them explicitly.

| Logical domain | Typical attached objects |
| --- | --- |
| OOB management | BMCs, switch management ports, console servers, PDUs, and management appliances |
| Service / customer | Compute CPU or DPU ports, support servers, storage control interfaces, border routers, and secure edge |
| GPU compute | Compute-node GPU NICs or SuperNIC PFs organized by rail and plane |
| Storage | Compute storage-client interfaces and storage target interfaces |
| InfiniBand intent | Compute or storage HCAs, InfiniBand switches, and fabric managers |

### 5.2 Physical Fabric Profiles

Logical separation and physical separation are independent choices.

| Profile style | Physical realization | Suitable use |
| --- | --- | --- |
| Compact converged | Service, storage, and in-band management share one redundant fabric with VRF/VLAN isolation | Small labs and cost-sensitive deployments |
| Split compute and converged | GPU compute has dedicated rail/plane fabrics; service and storage share a separate fabric | General production-aligned reference |
| Fully separated | GPU compute, storage, service, and OOB use independent fabrics | Explicit isolation or high-throughput requirements |

A policy profile declares which logical domains may share a fabric and which failure
domains they must not share. The architecture does not require a separate physical
storage fabric universally.

### 5.3 Ethernet GPU Compute Fabric

The Ethernet compute domain is a rail-aware Clos. Each declared plane is independently
cabled through its selected leaf and spine set. The baseline is L3 eBGP and ECMP;
EVPN/VXLAN is an optional service or DCI profile rather than a prerequisite.

Future policy may validate:

- rail-plane attachment completeness and symmetry
- independent switch and power dependencies across required planes
- MTU and traffic-class consistency along every intended path
- ECMP path diversity and profile-specific entropy assumptions
- permitted PFC and ECN scope without claiming hardware behavior
- residual capacity after an allowed failure
- telemetry coverage for drops, congestion, and queue state

### 5.4 Secure Edge

The FortiGate HA pair may connect to redundant border leaves or dedicated border
routers and exchange routes through BGP. Its profile should validate:

- HA membership, heartbeat connectivity, and primary/secondary state
- redundant northbound and southbound attachments
- expected BGP peers, route filters, and default-route behavior
- firewall policy and NAT intent
- session-preserving failover only when the selected virtual platform supports it

A compact lab may combine border routing and firewall functions. A production-aligned
profile should keep fabric forwarding, border routing, and stateful security as
separate roles.

### 5.5 InfiniBand Intent Domain

InfiniBand uses its own roles, platform metadata, rail semantics, and findings. The
initial profile is non-executable and validates:

- rail-aligned server connectivity
- leaf/spine or fat-tree completeness
- port counts, media intent, and cable placement
- redundant fabric-manager connectivity
- failure-domain isolation
- storage and compute fabric separation when required by policy

An InfiniBand object may appear in NetBox and reports, but it must never be rendered as
an Ethernet NOS node merely to make a graph executable.

## 6. Intent, Ownership, and Source Boundaries

| Data | Owner or evidence source |
| --- | --- |
| Installed devices, roles, locations, racks, interfaces, cables, assigned addresses, and ASNs | NetBox |
| Permitted address pools, prefix-length constraints, topology policy, capacity targets, and failure-domain constraints | Git policy profiles |
| Platform capabilities, backend mappings, renderers, assurance queries, hardware templates, and scenarios | Git |
| Generated topology, configuration, expected state, inventory, and manifests | Compiler build output |
| Deployed lab name, topology digest, build identity, and expected container set | Runtime deployment stamp |
| Adjacencies, routes, interface state, HA state, and telemetry | Runtime collectors |
| Observation time, collector versions, fidelity claim, and raw-evidence references | Evidence envelope |
| Findings and comparison results | Versioned report schema |

The current MVP reads assigned IP Address objects from NetBox. Git policy owns permitted
address pools and prefix-length constraints. Moving pool ownership to native NetBox
Prefix objects is a separate migration that must update the adapter, policy model,
provenance, and contract tests together.

Native NetBox objects are preferred for installed physical facts. Post-MVP source
adapters may read interface speed, MTU, management-only state, rack and location,
device components, cable type/profile, power ports/outlets, power feeds, and power
panels. NetBox's power model ends at the power panel; upstream utility, UPS, cooling, or
building dependencies require an explicit extension or an external facilities source.

Hardware affinity has three sources that must not be conflated:

- NetBox records the intended installed interface, NIC/module identity, and attachment.
- A Git-owned hardware profile declares model-specific invariants and expected
  GPU/NIC/NUMA relationships.
- A hardware collector may contribute observed PCIe, NUMA, firmware, and link evidence.

Discovered runtime facts must not silently overwrite intended state.

## 7. Infrastructure-Intent Model

The following is a conceptual contract, not an immediate commitment to Python classes
or NetBox custom fields.

```text
NetworkDomain
  id, kind, isolation_requirements

FabricInstance
  id, technology, topology_kind, failure_domains

Plane
  id, fabric_instance, independence_requirements

Rail
  id, endpoint_position, symmetry_requirements

Attachment
  endpoint, interface_or_pf, domain, fabric, plane?, rail?

FailureDomain
  id, kind, parent?, members

HardwareAffinity
  server_model, nic_slot, pf?, numa_node?, pcie_root?, gpu_set?
```

### 7.1 Physical Dependency Graph

Physical resilience is evaluated as shared dependency, not as device naming convention.

```text
Device PSU → Power outlet → PDU → Power feed → Power panel
Device     → Rack → Row / Location
Interface  → Leaf switch → Rack / power / control failure domains
```

Profiles declare which dependencies may be shared. Example policy intent:

```yaml
failure_domain_policy:
  endpoint_planes:
    must_not_share: [leaf_switch, power_feed]
  dual_psu:
    must_not_share: [power_feed]
  rack_separation:
    required: false
```

Sharing a rack is not inherently an error when independent feeds and switches satisfy
the selected policy. Findings must identify the complete shared-dependency path.

### 7.2 Breakout and Media

Capacity validation requires multi-position cable and lane semantics. The current MVP
normalizes one termination on each cable side; a post-MVP adapter must preserve cable
profiles, parent ports, lanes, media, and configured speed before breakout allocation
rules are enabled.

The normalized model must distinguish:

- a physical parent port and its total capacity
- logical or breakout child lanes
- configured speed and maximum supported speed
- optic or media compatibility
- administrative and operational state

## 8. Capacity, QoS, and Routing Policy

### 8.1 Capacity Contract

Capacity is calculated per physical scope rather than as one site-wide number:

```text
(fabric_instance, plane, rail, leaf, direction)
```

Reports distinguish:

- maximum port capability
- configured and effective capacity
- active-path capacity
- residual capacity after an allowed failure
- oversubscription target and observed design ratio

Candidate capacity findings include downlink-to-uplink target violations, endpoint and
switch speed mismatch, breakout over-allocation, and insufficient residual capacity.
Rule IDs become stable only when they are added to `docs/policy-rules.md` with tests.

### 8.2 RoCE and QoS Contract

The architecture defines end-to-end consistency, not universal queue values. A selected
profile owns DSCP, priority, traffic-class, MTU, PFC, ECN, and telemetry requirements.
Validation may compare:

```text
endpoint intent
→ leaf ingress classification
→ transit mapping
→ leaf egress queue policy
→ telemetry coverage
```

No common profile assumes that DSCP 26, priority 3, or PFC on a particular class is
correct for every vendor and deployment. Configuration presence is insufficient when
path mappings disagree. Conversely, a configuration finding must not be reported as
proof of physical lossless behavior.

### 8.3 Routing and Convergence Contract

Deterministic routing intent may include BFD, BGP timers, maximum-prefix limits,
route-policy references, graceful-restart behavior, maximum paths, multipath rules, and
next-hop handling. Unsupported attributes fail capability validation before rendering.

Failure scenarios may record an event sequence:

```text
fault requested
→ link state observed
→ route withdrawal observed
→ required reachability restored
→ fault repaired
→ baseline restored
```

Durations are software-lab convergence indicators, not physical SLAs. Their evidence
envelope records clock source, polling interval, repetitions, host/runtime information,
and min/median/max results. Volatile timing does not contribute to build identity.

## 9. Compiler, Backend, and Observed-State Boundaries

Intent branches into expected state and backend-specific configuration in parallel.

```text
                         ┌──→ vendor-neutral expected state ────────────┐
NetBox → domain model ───┤                                              ├→ compare
                         └──→ backend renderer → runtime → collector ───┘
                                                   vendor-neutral observed state
```

The current compiler supports `frr` and `linux_endpoint` renderers and still requires
network roles to select the FRR renderer. M6 replaces that role-to-FRR requirement with
backend capability contracts.

A platform backend contains:

```text
Platform backend
├── capability declaration and version
├── source-name to runtime-name interface mapping
├── configuration renderer
├── Containerlab node renderer
├── startup and readiness checks
├── observed-state collector
└── assurance adapter declarations
```

The common observed-state schema is versioned independently from vendor parsers.
Vendor command output, parser-specific field names, and proprietary payloads must not
leak into domain policy or expected state.

Juniper container and VM profiles remain separate. cRPD is a lightweight routing
control-plane backend over Linux data interfaces; vJunos is a VM-backed,
production-like runtime with different resource, boot, license, and fidelity contracts.

## 10. Runtime Profiles and Capability Admission

| Profile | Purpose | Expected runtime |
| --- | --- | --- |
| `functional-frr` | Deterministic development and required CI baseline | FRR and Linux containers |
| `ethernet-srlinux` | First model-driven NOS backend and gNMI collector | Nokia SR Linux container |
| `ethernet-arista` | EOS configuration and operational validation | User-supplied cEOS image |
| `ethernet-juniper-crpd` | Lightweight Junos routing control-plane validation | User-supplied cRPD image |
| `ethernet-juniper-vjunos` | VM-backed Junos operational validation | User-supplied vJunos-router image |
| `multivendor-interop` | Explicit routing and management interoperability | Selected tested NOS combination |
| `secure-edge-fortigate` | BGP, policy, NAT, HA, and failure scenarios | User-supplied FortiGate VM image |
| `infiniband-intent` | Structural validation without Ethernet emulation | NetBox and policy engine only |
| `infrastructure-intent` | Rack, power, capacity, and hardware-affinity validation | Source adapters and policy engine only |

The following matrix is an adoption plan, not a claim that every combination already
works. `Candidate` requires a project compatibility spike and golden evidence;
`Not advertised` means official tool coverage is absent or has not been established.

| Backend | Runtime | Direct collector | Batfish | SuzieQ | Telemetry |
| --- | --- | --- | --- | --- | --- |
| FRR | Required | Required | Candidate | Spike | Optional |
| SR Linux | Candidate | gNMI candidate | Not advertised | Not advertised | gNMI candidate |
| Arista EOS | Candidate | eAPI/gNMI candidate | Candidate | Candidate | gNMI candidate |
| Junos cRPD | Candidate | NETCONF/CLI candidate | Candidate | Spike | Profile-specific |
| Junos vJunos | Candidate | NETCONF/gNMI candidate | Candidate | Candidate | gNMI candidate |
| FortiGate | Candidate | API/CLI required | Candidate | Not advertised | Profile-specific |

A runtime profile is rejected before compilation or deployment when required
capabilities, images, licenses, host resources, collector support, or assurance support
are unavailable. A generic upstream tool support statement is insufficient; this
project must test the exact generated syntax, NOS version, question, and normalized
field set.

## 11. Layered Assurance Workflow

```text
NetBox intended state
        |
        v
Domain policy engine -------- source and AI-fabric invariants
        |
        v
Deterministic compiler ------ expected state + backend configuration
        |                                      |
        |                                      +--> Batfish candidate evidence
        v
Containerlab runtime
        |
        +--> Direct collector ---------------- required exact checks
        +--> SuzieQ candidate evidence ------- network-wide normalized state
        +--> gNMIc candidate telemetry ------- time-series observations
        |
        v
Expected-versus-observed report + evidence envelope
```

| Layer | Primary question | Evidence role |
| --- | --- | --- |
| Domain policy engine | Does source intent satisfy the selected profile? | Authoritative project finding over intended state |
| Batfish | What behavior follows from supported rendered configuration? | Derived pre-deployment evidence |
| Direct collector | Did the selected runtime establish exact expected state? | Required profile-specific runtime evidence |
| SuzieQ | Where is normalized network-wide state inconsistent? | Optional derived operational evidence |
| gNMIc | How did supported telemetry change over time? | Optional time-series evidence |

### 11.1 Batfish Admission

Initial questions may cover reachability, isolation, routing loops, black holes, BGP
policy, path diversity, and comparison between builds. A backend advertises Batfish
only when generated configurations parse without unsupported critical syntax and every
adopted question has golden expected answers.

### 11.2 SuzieQ Admission

Initial uses may cover LLDP topology drift, interface state, BGP, routes, duplicate
addressing, MTU observations, and before/after snapshots. SuzieQ never becomes intended
or expected state. Direct collectors remain available for unsupported NOS features and
for the lightweight FRR profile.

### 11.3 gNMI and Telemetry

gNMIc may collect streaming telemetry from admitted backends and export metrics to
Prometheus. It complements rather than feeds SuzieQ: telemetry explains change over
time, while SuzieQ supplies queryable normalized snapshots through its supported
transports. Neither tool writes back to NetBox during compile or verification.

## 12. Provenance and Evidence Contract

### 12.1 Implemented Build Identity

The MVP manifest already binds:

- compiler version
- NetBox source revision
- policy-profile name and semantic SHA-256 identity
- platform-map name and semantic SHA-256 identity
- generated artifact paths, sizes, and SHA-256 identities
- one derived build hash

### 12.2 Implemented Deployment Identity

After successful deployment and inspection, the runtime stamp binds:

- lab name and topology path
- topology SHA-256 identity
- build hash and source revision
- exact expected container names

Verify and scenario operations require manifest integrity, stamp/current-build
agreement, and the exact running container set before collecting evidence.

### 12.3 Future Observation Envelope

Observation metadata is deliberately separate from deterministic report findings and
build identity.

```json
{
  "schema_version": 1,
  "build_hash": "...",
  "source_revision": "...",
  "runtime_profile": "ethernet-arista",
  "node_images": {"leaf-a1": "ceos:<compatible-version>"},
  "collector_versions": {"direct-eos": "..."},
  "observed_from": "...",
  "observed_until": "...",
  "fidelity_claim": "emulated-control-plane",
  "evidence_refs": ["evidence/bgp/leaf-a1.json"]
}
```

Reports may remain byte-stable for the same normalized findings. Volatile timestamps,
raw counters, and host measurements live in the envelope or referenced evidence and do
not alter the compiled build hash.

## 13. Image, License, Security, and CI Policy

- Do not redistribute proprietary NOS or security-appliance images.
- Require users to import vendor images from authorized sources.
- Keep compatible version tags in platform mappings; strict local digests remain an
  optional reproducibility control rather than a universal open-source requirement.
- Detect missing images, licenses, capabilities, and host resources before deployment
  with actionable messages.
- Mark VM-backed and licensed profiles as local or privileged self-hosted tests.
- Use least-privilege read-only accounts for collectors.
- Keep secrets, license files, vendor credentials, and sensitive raw state out of Git,
  source snapshots, and default reports.
- Run the FRR profile in ordinary CI so the core workflow remains open and reproducible.
- Upload only sanitized topology, manifest, expected-state, and report artifacts from
  privileged E2E jobs.

## 14. Delivery Tracks

### 14.1 Foundation Gate

Before adding another backend, finalize and test:

- domain, fabric, plane, rail, attachment, and failure-domain terminology
- backend capability and observed-state schemas
- report evidence-source and fidelity fields
- source-name to runtime-name interface mapping
- admission-test conventions for third-party assurance tools

### 14.2 Executable Network Track

1. **M6 — Platform Backend Abstraction:** remove the network-role-to-FRR constraint,
   implement the backend contract, and deliver SR Linux as the second end-to-end
   runtime without claiming Batfish or SuzieQ support prematurely.
2. **M7 — Batfish Pre-Deployment Assurance:** start with a renderer that Batfish can
   parse and import selected answers as project findings.
3. **M8 — Multi-Vendor Operational Assurance:** add one production-like NOS profile,
   normalize observed state, and evaluate SuzieQ only for an admitted backend.
4. **M9 — FortiGate Secure Edge:** add border and firewall roles, HA topology, routing,
   policy, direct collection, and failure scenarios.
5. Add a second production-like NOS and explicit interoperability profile only after
   the first single-vendor profile is stable.

### 14.3 Infrastructure-Intent Track

1. **I1 — Physical Source Contract:** ingest rack/location, interface speed and MTU,
   cable profiles, breakout terminations, and device component identity.
2. **I2 — Dependency and Capacity Policy:** build physical dependency graphs and add
   failure-domain, speed, breakout, residual-capacity, and oversubscription findings.
3. **I3 — Rail and Hardware Affinity:** model rail-plane attachments and validate
   hardware-profile and observed GPU/NIC/NUMA relationships.
4. **I4 — InfiniBand Intent:** add InfiniBand roles, topology completeness, managers,
   media, and isolated policy/report namespaces without Ethernet rendering.

The two tracks may progress independently, but both must preserve the same ownership,
provenance, finding, and fidelity contracts.

## 15. Acceptance Principles

A post-MVP profile or infrastructure-intent feature is complete only when:

- its scope and fidelity claim are explicit;
- the same source and Git inputs produce the same deterministic build identity;
- expected state remains vendor-neutral;
- backend-specific configuration and observed fields do not leak into domain policy;
- unsupported capabilities fail before deployment or evidence collection;
- every third-party evidence source has versioned compatibility tests;
- findings identify source, target, cause, remediation, and evidence origin;
- failure scenarios restore the original state;
- timing and hardware observations are separated from deterministic build identity;
- reports state hardware and workload limitations;
- licensed profiles do not weaken the open FRR baseline;
- infrastructure-intent validation does not claim that non-executable dependencies were
  emulated.

## 16. Reference Anchors

These references inform the terminology and adoption gates; they do not replace project
tests or profile-specific contracts.

- [NVIDIA HGX AI Factory networking logical architecture](https://docs.nvidia.com/enterprise-reference-architectures/hgx-ai-factory/latest/network-logical-architecture.html)
- [NVIDIA HGX AI Factory networking physical topologies](https://docs.nvidia.com/enterprise-reference-architectures/hgx-ai-factory/latest/networking-physical-topologies.html)
- [NVIDIA Spectrum-X software multiplane configuration](https://docs.nvidia.com/networking/display/kubernetes2640/spectrum-x/quick-start-swplb.html)
- [NetBox interface model](https://netbox.readthedocs.io/en/stable/models/dcim/interface/)
- [NetBox cable model](https://netbox.readthedocs.io/en/stable/models/dcim/cable/)
- [NetBox power tracking](https://netbox.readthedocs.io/en/stable/features/power-tracking/)
- [Containerlab supported kinds](https://containerlab.dev/manual/kinds/)
- [Containerlab Juniper cRPD kind](https://containerlab.dev/manual/kinds/crpd/)
- [Batfish supported network devices](https://batfish.readthedocs.io/en/latest/supported_devices.html)
- [SuzieQ supported tables and devices](https://suzieq.readthedocs.io/en/latest/tables/)
- [SuzieQ supported transports](https://suzieq.readthedocs.io/en/latest/transports/)
