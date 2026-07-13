# Research and References

This document collects papers, technical documentation, open-source projects, and design references related to the AI Factory Network Twin project.

The project focuses on building a NetBox-driven digital twin for generating, validating, and testing AI cluster network fabrics with Containerlab.

## Research Scope

The research is organized around the following topics:

- AI cluster and AI Factory network architecture
- Distributed training communication patterns
- Clos and rail-optimized network topologies
- Network emulation with Containerlab
- NetBox-driven topology generation
- Network digital twins and pre-change validation
- Failure injection and convergence testing
- RoCE, congestion control, and AI fabric limitations
- Network observability and state validation

## Reading Priority


| Priority | Meaning                                  |
| -------- | ---------------------------------------- |
| P0       | Directly influences the MVP architecture |
| P1       | Relevant to later implementation phases  |
| P2       | Background or long-term research         |
| Watch    | Emerging work that should be revisited   |


---

# 1. Adjacent Research and Transferable Ideas

## 1.1 ScaleAcross

- **Title:** ScaleAcross: Designing Multi-Data-Center Infrastructure for Geo-Distributed AI Training
- **Authors:** Naved Inam, Aryan Alpesh Bhavsar, Masabattula Teja Nikhil, Sidharth Sharma
- **Submitted:** 11 June 2026
- **Version:** arXiv:2606.12963v1
- **Type:** arXiv preprint; peer-review status not confirmed
- **Priority:** P1
- **Links:**
  - [https://arxiv.org/abs/2606.12963v1](https://arxiv.org/abs/2606.12963v1)
  - [https://arxiv.org/html/2606.12963v1](https://arxiv.org/html/2606.12963v1)
- **Artifact Status:** No complete experiment repository is linked from the paper or arXiv record.
- **Relationship:** Adjacent research reference; not an implementation dependency, architecture
  blueprint, or reproduction target.
- **Project Note:** [ScaleAcross: Transferable Experiment Patterns for a Network Digital Twin](papers/scaleacross-geo-distributed-ai-training.md)

### Summary

ScaleAcross describes a software network-emulation framework for geo-distributed AI training.
The authors characterize it as open and reproducible, but this project has not independently
reproduced the environment or results.

The implementation uses:

- Containerlab
- FRRouting
- EVPN/VXLAN
- ECMP
- BFD
- WAN latency emulation
- QEMU-based Soft-RoCE endpoints
- PyTorch DDP AllReduce training
- Ray and PyTorch Parameter Server training

### Relevance

ScaleAcross is an adjacent example of combining a software network, a real but small-scale
distributed-training workload, controlled network conditions, and measured observations.

AI Factory Network Twin is independently designed and does not reproduce the paper's topology,
overlay, transport modification, workload, or reported performance. The useful relationship is
limited to transferable experiment patterns.

### Lessons for This Project

- Treat configured path diversity and observed path use as different questions.
- Encode network failures as bounded, repeatable experiments with restoration evidence.
- Keep workload experiments optional and separate from the core routing verifier.
- Preserve an explicit boundary between software-network evidence and physical ASIC, RDMA, NIC,
  or GPU performance.
- Treat the paper's WAN, EVPN/VXLAN, Soft-RoCE, BFD, and workload choices as source-specific, not
  as requirements for this project.

### Follow-up Questions

- Is a complete experiment repository available from the authors?
- Which reported experiments can be reproduced independently from the published material?
- Would a project-specific CPU collective or TCP flow matrix add evidence beyond routing and
  reachability checks?
- Which functional workload metrics would fit this project's fidelity contract?

---

# 2. Containerlab

## 2.1 Containerlab Documentation

- **Project:** Containerlab
- **Priority:** P0
- **Links:**
  - [https://containerlab.dev/](https://containerlab.dev/)
  - [https://github.com/srl-labs/containerlab](https://github.com/srl-labs/containerlab)
  - [https://containerlab.dev/quickstart/](https://containerlab.dev/quickstart/)
  - [https://containerlab.dev/manual/topo-def-file/](https://containerlab.dev/manual/topo-def-file/)
  - [https://containerlab.dev/manual/config-mgmt/](https://containerlab.dev/manual/config-mgmt/)

### Relevant Capabilities

- Declarative YAML topology definitions
- Container-based network operating systems
- Regular Linux containers as topology nodes
- Startup configuration support
- Automatic management network creation
- Generated inventories for external automation
- Node lifecycle operations
- Topology inspection
- Link impairment support through Linux networking tools

### Relevance

Containerlab is the runtime responsible for turning the generated topology and startup configuration into an executable network lab.

### Design Implications

- Generated topology files should be treated as build artifacts.
- Startup configuration should be generated outside Containerlab.
- Containerlab lifecycle commands should be wrapped by the `aftwin` CLI.
- Runtime state should not become the source of truth.
- Containerlab version and container images should be pinned.

## 2.2 Linux Container Nodes

- **Priority:** P0
- **Link:**
  - [https://containerlab.dev/manual/kinds/linux/](https://containerlab.dev/manual/kinds/linux/)

### Relevance

Linux nodes can represent:

- GPU compute servers
- Storage servers
- Traffic generators
- Verification agents
- Telemetry components

For the MVP, compute nodes can use Linux VRFs to isolate Fabric A and Fabric B.

## 2.3 FRRouting

- **Project:** FRRouting
- **Priority:** P0
- **Links:**
  - [https://frrouting.org/](https://frrouting.org/)
  - [https://github.com/FRRouting/frr](https://github.com/FRRouting/frr)
  - [https://docs.frrouting.org/](https://docs.frrouting.org/)

### Relevance

FRR is the initial routing backend for implementing:

- eBGP underlay
- ECMP
- BFD
- Route advertisement
- JSON-based operational state inspection

### Design Implications

FRR should be the first supported backend because it is lightweight, open source, and easy to run in Linux containers.

Vendor-specific network operating systems can be added after the complete compile–deploy–verify workflow is stable.

## 2.4 Nokia SR Linux

- **Priority:** P1
- **Links:**
  - [https://containerlab.dev/manual/kinds/srl/](https://containerlab.dev/manual/kinds/srl/)
  - [https://learn.srlinux.dev/](https://learn.srlinux.dev/)

### Relevance

SR Linux provides a stronger telemetry and model-driven management environment than plain FRR.

Potential later uses include:

- gNMI-based state collection
- Structured configuration
- Event-driven telemetry
- More realistic network operating system behavior

---

# 3. NetBox Integration

## 3.1 NetBox

- **Project:** NetBox
- **Priority:** P0
- **Links:**
  - [https://netboxlabs.com/products/netbox/](https://netboxlabs.com/products/netbox/)
  - [https://github.com/netbox-community/netbox](https://github.com/netbox-community/netbox)
  - [https://netbox.readthedocs.io/](https://netbox.readthedocs.io/)

### Relevant Capabilities

- Device and rack modeling
- Interface and cable modeling
- IP address management
- ASN management
- Sites and locations
- Device roles and platforms
- Tags and custom fields
- REST API
- GraphQL API
- Event rules and webhooks

### Relevance

NetBox is the intended source of truth for physical topology and addressing intent.

### Project Boundary

NetBox should own:

- Devices
- Interfaces
- Cables
- IP addresses
- Prefixes
- ASNs
- Physical locations
- Fabric plane metadata

Git should own:

- Validation policies
- Rendering templates
- Platform mappings
- Test scenarios
- Golden snapshots

## 3.2 NetBox, NetReplica, and Containerlab

- **Project:** NetBox + NetReplica + Containerlab
- **Priority:** P0
- **Link:**
  - [https://github.com/srl-labs/netbox-nrx-clab](https://github.com/srl-labs/netbox-nrx-clab)
- **Reviewed Revision:**
  [`srl-labs/netbox-nrx-clab@a2eec5a`](https://github.com/srl-labs/netbox-nrx-clab/tree/a2eec5a56fcf818583f3e68d0349ef92a5b7900f)
- **Relationship:** Adjacent implementation reference and comparison point; not a dependency or
  reproduction target.
- **Project Note:** [NetBox, NRX, and Containerlab: An Adjacent Digital-Twin Implementation Pattern](papers/netbox-nrx-containerlab-digital-twin.md)

### Summary

This project demonstrates how selected NetBox data can be exported with NRX, deployed as an SR
Linux Containerlab replica, configured by a separate Python workflow, and used to rehearse an
OSPF-to-IS-IS migration.

### Relevance

It is a concrete open-source implementation of a NetBox-to-Containerlab workflow. AI Factory
Network Twin uses it to compare generic extraction, platform mapping, and artifact-generation
patterns while retaining an independent architecture and validation contract.

### Lessons for This Project

Transferable comparison points include:

- selecting an executable subgraph from NetBox,
- keeping platform and interface mappings explicit,
- generating disposable runtime artifacts from intended state, and
- rehearsing an operational change in an executable replica.

The project's AI-fabric domain model, deterministic compiler, policy rules, expected state,
runtime verifier, and failure scenarios are independent project decisions rather than features
derived from this reference.

## 3.3 NetReplica NRX

- **Project:** NRX
- **Priority:** P0
- **Links:**
  - [https://github.com/netreplica/nrx](https://github.com/netreplica/nrx)
  - [https://nrx.netreplica.com/](https://nrx.netreplica.com/)
  - [https://github.com/netreplica/templates](https://github.com/netreplica/templates)

### Summary

NRX exports NetBox topologies into formats such as Containerlab, Cisco Modeling Labs, and NVIDIA Air.

### Research Questions

- Which NetBox objects and relationships does NRX support?
- How does NRX map NetBox platforms to Containerlab kinds?
- Can NRX be used as an optional topology-export backend?
- Is it better to extend NRX or maintain a project-specific compiler?
- Which parts can be reused without coupling the project architecture to NRX?

### Independent Project Direction

NRX is treated as:

- A reference implementation
- A comparison baseline
- A possible optional backend requiring a separate compatibility decision

The project-specific compiler is a deliberate project choice because its contract includes
AI-fabric policies, expected state, endpoint configuration, provenance, and verification
artifacts. This decision does not imply that NRX is deficient for its own generic export goals.

---

# 4. Network Digital Twins

## 4.1 NetBox as a Network Source of Truth

- **Priority:** P0
- **Links:**
  - [https://netboxlabs.com/products/netbox/](https://netboxlabs.com/products/netbox/)
  - [https://netboxlabs.com/blog/navigating-network-automation-with-netbox-the-design-stage/](https://netboxlabs.com/blog/navigating-network-automation-with-netbox-the-design-stage/)

### Relevance

A digital twin should be generated from intended state rather than inferred only from runtime state.

This supports the following workflow:

```text
Intended state
→ Static validation
→ Generated configuration
→ Emulated deployment
→ Runtime validation
→ Change approval

```

## 4.2 Network Discovery and Assurance Integrations

- **Priority:** P1
- **Links:**
  - [https://netboxlabs.com/blog/our-network-discovery-and-assurance-partnerships/](https://netboxlabs.com/blog/our-network-discovery-and-assurance-partnerships/)
  - [https://netboxlabs.com/news/strategic-partnerships-reduce-adoption-barriers-for-network-automation/](https://netboxlabs.com/news/strategic-partnerships-reduce-adoption-barriers-for-network-automation/)

### Relevance

These references describe integrations between a network source of truth and network assurance or digital twin platforms.

### Lessons for This Project

The project should distinguish between:

- **Intended state:** NetBox
- **Compiled state:** Generated artifacts
- **Observed state:** Containerlab runtime
- **Validation result:** Difference between expected and observed state

## 4.3 Batfish

- **Project:** Batfish
- **Priority:** P1
- **Links:**
  - [https://www.batfish.org/](https://www.batfish.org/)
  - [https://github.com/batfish/batfish](https://github.com/batfish/batfish)
  - [https://pybatfish.readthedocs.io/](https://pybatfish.readthedocs.io/)

### Potential Uses

- Pre-deployment route analysis
- Reachability queries
- Loop detection
- Routing policy analysis
- Configuration comparison

### Open Question

Determine whether Batfish adds enough value beyond the initial custom policy engine and runtime verifier.

It should not be an MVP dependency unless it supports the selected FRR configuration reliably.

## 4.4 SuzieQ

- **Project:** SuzieQ
- **Priority:** P1
- **Links:**
  - [https://suzieq.readthedocs.io/](https://suzieq.readthedocs.io/)
  - [https://github.com/netenglabs/suzieq](https://github.com/netenglabs/suzieq)

### Potential Uses

- Operational state collection
- Topology inspection
- Routing state comparison
- Network-wide assertions
- Drift detection

---

# 5. AI Cluster Network Architecture

## 5.1 NVIDIA Spectrum-X

- **Priority:** P1
- **Links:**
  - [https://www.nvidia.com/en-us/networking/spectrum-x/](https://www.nvidia.com/en-us/networking/spectrum-x/)
  - [https://docs.nvidia.com/networking/](https://docs.nvidia.com/networking/)

### Research Topics

- Rail-optimized topology
- Adaptive routing
- RoCE congestion control
- ECN and PFC
- Spectrum switch architecture
- BlueField and ConnectX integration
- Telemetry and congestion visibility

### Project Boundary

Containerlab cannot accurately reproduce:

- Switch ASIC buffering
- NIC offload
- Packet spraying
- Adaptive routing hardware
- RDMA queue-pair processing
- Line-rate congestion behavior

These references should therefore guide topology and policy design, not performance claims.

## 5.2 NVIDIA DGX BasePOD and SuperPOD

- **Priority:** P1
- **Links:**
  - [https://docs.nvidia.com/dgx-basepod/](https://docs.nvidia.com/dgx-basepod/)
  - [https://docs.nvidia.com/dgx-superpod/](https://docs.nvidia.com/dgx-superpod/)

### Research Topics

- Management, compute, storage, and in-band networks
- GPU fabric redundancy
- Rack-level topology
- Leaf–spine sizing
- Storage connectivity
- Failure domains

### Potential Validation Rules

- Every compute node must have redundant fabric connectivity.
- Fabric planes must not share a single point of failure.
- Management interfaces must not be advertised into the compute fabric.
- Storage and collective communication paths should follow explicit policy.
- Leaf uplink capacity must satisfy a configured oversubscription target.

## 5.3 Rail-Optimized Topology

- **Priority:** P1
- **Status:** Further research required

### Research Questions

- How should GPU NICs be mapped to rails?
- Should `rail_id` belong to a NetBox interface or cable?
- How should a multi-NIC host be represented in Containerlab?
- Can rail isolation be verified using Linux VRFs?
- Which rail failures should preserve partial training connectivity?
- How should rail-aware collective traffic be approximated?

---

# 6. Distributed Training Communication

## 6.1 AllReduce

- **Priority:** P1

### Research Topics

- Ring AllReduce
- Tree AllReduce
- Recursive doubling
- ReduceScatter
- AllGather
- Communication-to-computation ratio
- Sensitivity to packet loss and latency
- Flow distribution across ECMP paths

### Potential MVP+ Traffic Model

A CPU-based workload can approximate collective communication using:

- PyTorch Distributed with the Gloo backend
- MPI collectives
- Custom TCP traffic generators
- `iperf3` flow matrices

This model should be described as a communication approximation rather than a GPU or NCCL benchmark.

## 6.2 Parameter Server

- **Priority:** P2

### Research Topics

- Centralized traffic concentration
- East–west bandwidth asymmetry
- Worker-to-server bottlenecks
- Failure and straggler behavior
- Comparison with collective communication

## 6.3 NCCL

- **Priority:** P1
- **Links:**
  - [https://github.com/NVIDIA/nccl](https://github.com/NVIDIA/nccl)
  - [https://docs.nvidia.com/deeplearning/nccl/](https://docs.nvidia.com/deeplearning/nccl/)

### Research Topics

- Topology-aware collective selection
- Ring and tree construction
- Multi-rail networking
- NCCL network plugins
- InfiniBand and RoCE transports
- Failure behavior

### Project Boundary

The project may model NCCL-like traffic patterns, but it must not claim to execute or reproduce real NCCL performance without suitable GPU and RDMA hardware.

---

# 7. RoCE and Congestion Control

## 7.1 RoCEv2

- **Priority:** P2

### Research Topics

- PFC
- ECN
- DCQCN
- RDMA queue pairs
- Head-of-line blocking
- Incast
- Elephant flows
- Entropy and ECMP polarization
- Lossless versus lossy fabrics

### Relevance

These concepts inform future policy checks and traffic scenarios.

### Emulation Limitations

Linux containers can approximate:

- Queue delay
- Packet loss
- Link rate limitation
- Latency
- Flow concentration

They cannot accurately reproduce:

- Hardware PFC behavior
- NIC congestion-control firmware
- Switch buffer allocation
- RDMA retransmission behavior
- Real 400G or 800G line-rate effects

## 7.2 Linux Traffic Control

- **Priority:** P1
- **Links:**
  - [https://man7.org/linux/man-pages/man8/tc.8.html](https://man7.org/linux/man-pages/man8/tc.8.html)
  - [https://man7.org/linux/man-pages/man8/tc-netem.8.html](https://man7.org/linux/man-pages/man8/tc-netem.8.html)

### Potential Uses

- Delay injection
- Packet loss
- Jitter
- Rate limiting
- Reordering
- Controlled failure scenarios

---

# 8. Failure Injection and Verification

## 8.1 Failure Scenarios

- **Priority:** P0

Initial scenarios:

1. Leaf–spine link failure
2. Single spine failure
3. Compute fabric interface failure
4. Entire fabric plane failure
5. Missing BGP adjacency
6. Incorrect ASN
7. Incorrect cable placement
8. Cross-plane link
9. Duplicate IP address
10. Missing endpoint redundancy

## 8.2 Metrics

Potential functional metrics:

- BGP session recovery time
- Route recovery time
- Packet-loss duration
- Endpoint reachability
- Available ECMP next-hop count
- Workload completion time
- Expected-versus-observed topology drift
- Number and severity of policy violations

## 8.3 Verification Tools

Candidate tools:

- FRR JSON CLI output
- Linux `ip -json`
- `ping`
- `fping`
- `traceroute`
- `iperf3`
- Nornir
- Batfish
- SuzieQ
- gNMIc

The MVP should begin with direct FRR and Linux JSON output to minimize dependencies.

---

# 9. Observability

## 9.1 gNMIc

- **Priority:** P1
- **Links:**
  - [https://gnmic.openconfig.net/](https://gnmic.openconfig.net/)
  - [https://github.com/openconfig/gnmic](https://github.com/openconfig/gnmic)

### Potential Uses

- Streaming telemetry collection
- Subscription management
- Prometheus export
- Runtime state verification

## 9.2 Prometheus and Grafana

- **Priority:** P2
- **Links:**
  - [https://prometheus.io/](https://prometheus.io/)
  - [https://grafana.com/](https://grafana.com/)

### Potential Dashboards

- BGP adjacency status
- Interface traffic
- Packet drops
- Route count
- ECMP path count
- Failure convergence
- Workload completion time
- Policy violations
- NetBox drift count

Observability should be added only after compile, deploy, and verification workflows are stable.

---

# 10. Related Open-Source Projects


| Project                     | Purpose                                 | Priority | Link                                                                                       |
| --------------------------- | --------------------------------------- | --------: | ------------------------------------------------------------------------------------------ |
| Containerlab                | Container-based network labs            | P0       | [https://github.com/srl-labs/containerlab](https://github.com/srl-labs/containerlab)       |
| NetBox                      | Network source of truth                 | P0       | [https://github.com/netbox-community/netbox](https://github.com/netbox-community/netbox)   |
| NetReplica NRX              | NetBox topology exporter                | P0       | [https://github.com/netreplica/nrx](https://github.com/netreplica/nrx)                     |
| NetBox–NRX–Containerlab Lab | Digital twin example                    | P0       | [https://github.com/srl-labs/netbox-nrx-clab](https://github.com/srl-labs/netbox-nrx-clab) |
| FRRouting                   | Open-source routing stack               | P0       | [https://github.com/FRRouting/frr](https://github.com/FRRouting/frr)                       |
| NetworkX                    | Graph validation and analysis           | P0       | [https://github.com/networkx/networkx](https://github.com/networkx/networkx)               |
| Batfish                     | Configuration and reachability analysis | P1       | [https://github.com/batfish/batfish](https://github.com/batfish/batfish)                   |
| SuzieQ                      | Network observability and assertions    | P1       | [https://github.com/netenglabs/suzieq](https://github.com/netenglabs/suzieq)               |
| gNMIc                       | gNMI client and collector               | P1       | [https://github.com/openconfig/gnmic](https://github.com/openconfig/gnmic)                 |
| NCCL                        | GPU collective communication            | P1       | [https://github.com/NVIDIA/nccl](https://github.com/NVIDIA/nccl)                           |


---

# 11. Project Hypotheses

The project should validate the following hypotheses.

## H1 — NetBox Can Represent the Required Fabric Intent

Native NetBox objects with a small number of custom fields are sufficient to represent a dual-plane AI cluster network.

### Validation Method

Create the `mini-dual-plane` fixture and verify that all required topology and addressing data can be derived without external spreadsheets.

## H2 — AI Fabric Errors Can Be Detected Before Deployment

Graph-based policies can detect structurally invalid designs such as:

- Missing fabric plane
- Shared failure domain
- Cross-plane connection
- Insufficient uplink redundancy
- Duplicate addressing
- Incomplete Clos connectivity

### Validation Method

Create deliberately invalid fixtures and assert stable policy rule IDs.

## H3 — Containerlab Is Sufficient for Functional Validation

Containerlab and FRR can validate:

- BGP adjacency
- Route propagation
- ECMP
- Failure recovery
- Endpoint reachability
- Plane isolation

### Validation Method

Deploy the golden topology and execute automated runtime assertions.

## H4 — Lightweight Traffic Can Reveal Topology Behavior

CPU-based collective-like traffic can expose path loss, congestion, and failure effects without physical GPUs.

### Validation Method

Compare flow completion time and packet loss before, during, and after controlled failures.

## H5 — Deterministic Compilation Improves Reviewability

The same NetBox input should produce byte-identical topology, configuration, and expected-state artifacts.

### Validation Method

Compile the same source snapshot multiple times and compare hashes.

---

# 12. Open Research Questions

## NetBox Modeling

- Should `fabric_plane` be assigned to devices, interfaces, or both?
- Should ASN assignment come entirely from NetBox?
- How should logical links be modeled when no physical cable exists?
- Should loopbacks use NetBox interfaces or custom fields?
- How should breakout ports be represented?
- How should multi-chassis or modular switches be represented?

## Containerlab Runtime

- Should FRR nodes use the generic Linux kind or a dedicated image convention?
- How should endpoint VRFs be initialized reliably?
- How should node readiness be detected?
- How should the verifier avoid depending on human-oriented CLI output?
- Which Containerlab version should be the minimum supported version?

## AI Fabric Policies

- What constitutes independent failure domains?
- Should two planes be allowed to share a rack?
- Should two planes be allowed to share a power domain?
- How should oversubscription be calculated?
- How should rail-aware host connectivity be validated?
- Which policies are universal and which are profile-specific?

## Traffic Modeling

- Is PyTorch Gloo sufficient for the first AllReduce approximation?
- Would MPI provide more deterministic traffic?
- How should ECMP entropy be generated?
- How many concurrent flows are needed to expose path imbalance?
- How should workload completion be measured reproducibly?

## Drift Detection

- Which observed state should be compared with NetBox?
- Can LLDP be collected consistently from FRR containers?
- Should runtime drift remain report-only?
- How should expected changes be distinguished from accidental drift?

---

# 13. Research Log

Use this section for chronological notes.

## YYYY-MM-DD — Topic

### Sources Reviewed

- Link
- Link

### Findings

- Finding
- Finding

### Decisions

- Decision
- Decision

### Questions

- Question
- Question

---

# 14. Source Entry Template

Use the following template when adding a new source.

```markdown
## Source Title

- **Type:** Paper | Documentation | Project | Presentation | Blog
- **Authors/Organization:**
- **Published:**
- **Priority:** P0 | P1 | P2 | Watch
- **Links:**
  - URL

### Summary

Brief summary of the source.

### Relevance

Why this source matters to the project.

### Applicable Ideas

- Idea
- Idea

### Limitations

- Limitation
- Limitation

### Follow-up Questions

- Question
- Question

```

---

# 15. Citation Policy

When adding a source:

1. Prefer papers, official documentation, and original project repositories.
2. Record the publication or last-updated date when available.
3. Distinguish experimental results from vendor claims.
4. Avoid presenting software emulation results as hardware performance.
5. Note whether source code or experiment artifacts are available.
6. Archive important findings in project notes rather than depending only on external URLs.
7. Record the date a source was reviewed.
8. Mark superseded or outdated material instead of deleting it.

---

# 16. Current Research Follow-ups

The remaining research tasks are intentionally separate from the implemented project baseline:

1. Reproduce the pinned NetBox–NRX–Containerlab example as an independent comparison exercise,
   not as an architecture or compatibility requirement.
2. Compare NRX and project-compiler output for the same sanitized NetBox fixture.
3. Determine whether a complete ScaleAcross experiment artifact is available from the authors;
   do not make paper reproduction a project milestone.
4. Decide whether workload-aware evidence adds value beyond the existing routing, isolation, and
   failure verifier.
5. If workload experiments are justified, compare PyTorch Gloo, MPI, and custom TCP flow matrices
   under a project-owned fidelity and measurement contract.

The earlier research on the minimal NetBox schema, FRR JSON collection, endpoint VRFs,
deterministic generation, stable policy IDs, and reversible link/spine failures has already been
translated into the current compiler, verifier, rule catalog, scenarios, and accepted ADRs.
