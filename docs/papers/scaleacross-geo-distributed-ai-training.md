# ScaleAcross: Transferable Experiment Patterns for a Network Digital Twin

## Source

- **Title:** ScaleAcross: Designing Multi-Data-Center Infrastructure for Geo-Distributed AI Training
- **Authors:** Naved Inam, Aryan Alpesh Bhavsar, Masabattula Teja Nikhil, Sidharth Sharma
- **Submitted:** 11 June 2026
- **Version:** arXiv:2606.12963v1
- **Type:** arXiv preprint; peer-review status not confirmed
- **Links:**
  - [arXiv abstract](https://arxiv.org/abs/2606.12963v1)
  - [arXiv HTML](https://arxiv.org/html/2606.12963v1)
- **Reviewed:** 2026-07-13

## Relationship to This Project

ScaleAcross and AI Factory Network Twin are independent projects.

AI Factory Network Twin is not an implementation or reproduction of ScaleAcross, and
ScaleAcross is not its architecture blueprint. This note uses the paper only as an adjacent
research reference from which a few experiment patterns can be adapted to an independently
designed network digital twin.

In particular, this project does not inherit the paper's geo-distributed topology, EVPN/VXLAN
overlay, Soft-RoCE modification, workload implementation, or measured performance results.

## One-Line Takeaway

ScaleAcross describes a useful experiment pattern—deploy a software network, run a real but
small-scale distributed workload, inject controlled network conditions, and measure the
outcome—that can inform selected tests in an otherwise independent network digital twin.

## What the Paper Studies

The paper investigates an EVPN/VXLAN infrastructure for geo-distributed AI training across two
emulated data centers. Its goal is to evaluate overlay connectivity, path distribution,
failure recovery, tenant isolation, and distributed-training behavior under controlled WAN
conditions.

The environment combines:

- Containerlab and Docker for topology deployment,
- FRRouting for BGP, EVPN, ECMP, and BFD,
- two virtual data centers, each with two spine and three leaf routers,
- VXLAN VNIs and MP-BGP EVPN for cross-site Layer 2 connectivity,
- Linux network emulation for delay and jitter,
- QEMU virtual machines inside containers for independent guest kernels,
- a modified Soft-RoCE implementation for queue-pair experiments,
- Prometheus with SNMP and Ping Exporters for monitoring,
- PyTorch DistributedDataParallel for AllReduce training, and
- Ray with PyTorch for Parameter Server training.

The distributed-training experiments are not merely synthetic flow generation. Both jobs
fine-tune DistilGPT2 on WikiText-2. The environment is nevertheless a software emulation, so
the results do not establish physical GPU, NIC, switch ASIC, or production RoCE performance.

## Experiment Flow

The paper's experiment flow can be summarized as:

```text
Containerlab topology
→ FRR and EVPN/VXLAN configuration
→ emulated hosts and Soft-RoCE endpoints
→ distributed-training workload
→ delay, path distribution, or failure condition
→ monitoring and measured result
```

This flow belongs to ScaleAcross. AI Factory Network Twin uses a separate workflow derived
from its own source-of-truth and verification model:

```text
NetBox intended state
→ project domain model and static policy
→ generated Containerlab, FRR, and expected-state artifacts
→ runtime deployment
→ expected-versus-observed verification
→ optional reversible failure scenario
```

The similarity is at the level of repeatable experimentation, not shared architecture.

## Reported Results

The following values are results reported by the paper for its own emulated environment. They
must not be treated as targets or predictions for AI Factory Network Twin.

| Experiment | Paper setup | Reported result |
| --- | --- | --- |
| WAN reachability | 5 ms delay and 1 ms jitter on each inter-DC link | Approximately 22 ms end-to-end RTT |
| Queue-pair-aware ECMP | Four source-port bins with 4, 8, 16, and 32 QPs | Peak load-factor improvement of 13.7% at a leaf and 9.9% at a spine |
| Link failure with default BGP timers | 60-second keepalive and 180-second hold timer | Approximately 180 seconds to recover |
| Link failure with BFD | 10 ms BFD interval with three retries | Approximately 110 ms to restore connectivity |
| AllReduce training | Four PyTorch DDP workers, about 312 MB of gradients per batch | Approximately 5–11 seconds per batch |
| Parameter Server training | One server and four workers, about 459 MB per batch | Approximately 9–18 seconds per batch |

The AllReduce and Parameter Server measurements use different communication volumes and
architectures, so their timing difference should not be read as a controlled comparison of the
two algorithms alone.

## The Most Transferable Idea: Observe Path Use

ScaleAcross examines queue-pair-aware UDP source-port allocation as a way to improve ECMP path
diversity. That mechanism depends on its modified Soft-RoCE environment and is not a component
of AI Factory Network Twin.

The transferable idea is narrower:

> A network experiment should distinguish configured path diversity from path diversity that
> is actually installed and exercised.

For an independent digital twin, this can motivate two different checks:

1. Verify that the runtime routing table contains the expected ECMP next-hop count.
2. In a future workload experiment, generate enough independent flows to observe whether the
   available paths are exercised or persistently imbalanced.

The first is a control-plane and runtime-state assertion. The second is an optional workload
experiment and does not require reproducing the paper's queue-pair mechanism.

## Other Transferable Experiment Patterns

### Treat Failures as Repeatable Scenarios

ScaleAcross measures behavior before and after a controlled path failure. The useful pattern is
to make a fault reproducible and attach explicit observations to it:

```text
healthy baseline
→ bounded failure injection
→ observation during the fault
→ restoration
→ recovery verification
```

AI Factory Network Twin independently implements this pattern through its own scenario schema
and runtime boundary, as recorded in
[ADR-010](../adr/010-reversible-failure-scenarios.md). It does not reproduce the paper's fault
mechanism or adopt its 110 ms result as a convergence requirement.

### Compare Expected and Observed Routing State

The paper's ECMP and failure experiments reinforce the value of collecting routing evidence
rather than assuming that configuration implies behavior. In this project, that idea is adapted
as vendor-neutral expected state compared with normalized FRR observations. The project's
runtime contract is defined independently in
[ADR-009](../adr/009-runtime-verification-boundary.md).

### Keep the Fidelity Boundary Explicit

Both the paper and this project operate in software, but they answer different questions. For
AI Factory Network Twin, the relevant fidelity contract is:

```text
Can validate:
- topology and addressing intent
- BGP adjacencies and route propagation
- installed ECMP next hops
- software endpoint reachability and plane isolation
- functional recovery in the recorded lab environment

Cannot validate:
- switch ASIC buffering or scheduling
- hardware PFC, ECN, or congestion-control behavior
- NIC offload and physical RDMA performance
- real 400G or 800G throughput
- NCCL or GPU job performance
```

ScaleAcross motivates care around this boundary; it does not define the boundary for this
project.

### Keep Workloads Optional

The paper demonstrates that a network experiment can run a real distributed-training workload
inside an emulated environment. AI Factory Network Twin may later use CPU-based collectives or
synthetic flow matrices to study functional path and failure effects. Such a plugin would be a
new project feature, not a port of the ScaleAcross workload.

A future experiment could describe concepts such as worker count, flow count, duration, fault
timing, and functional assertions. Any example in this note is conceptual and is not the
current scenario-file schema.

## Ideas Not Adopted from the Paper

The following ScaleAcross design choices are outside the current project's baseline:

- multi-data-center topology,
- WAN latency and jitter as a core requirement,
- EVPN/VXLAN tenant extension,
- QEMU-per-endpoint deployment,
- modified Soft-RoCE source-port allocation,
- the paper's BFD timer values,
- Parameter Server as a baseline workload, and
- the paper's throughput, convergence, or training-time results as acceptance criteria.

They can be revisited as independent research topics if a future project requirement calls for
them.

## Reproducibility and Evidence Limits

The paper describes its framework as open and reproducible, but the arXiv record and paper do
not link a complete experiment repository. As of the review date, this note has not independently
reproduced the topology, modified Soft-RoCE module, training setup, or reported measurements.

Additional limits to keep in view:

- the paper is an arXiv v1 preprint and its peer-review status is not confirmed,
- the reported values come from one small emulated topology,
- the host hardware and full environment manifest are not documented sufficiently here to
  claim byte-for-byte or performance reproducibility,
- aggressive BFD timers are environment-specific and should not become a default policy, and
- software RoCE behavior does not establish physical NIC or lossless-fabric behavior.

For these reasons, the paper offers ideas and reported observations, not independently verified
acceptance evidence for AI Factory Network Twin.

## Project Adoption Status

| Idea inspired by adjacent work | Status in this project | Project-owned reference |
| --- | --- | --- |
| Container-based executable experiment | Adopted independently | [ADR-008](../adr/008-containerlab-platform-and-rendering.md) |
| Expected-versus-observed routing checks | Adopted independently | [ADR-009](../adr/009-runtime-verification-boundary.md) |
| Reversible failure scenarios | Adopted independently | [ADR-010](../adr/010-reversible-failure-scenarios.md) |
| Explicit software-versus-hardware fidelity contract | Adopted independently | [Digital Twin Architecture](../DIGITAL_TWIN_ARCHITECTURE.md#4-fidelity-and-claim-contract) |
| Workload-aware traffic experiments | Deferred research | Project-specific design required |
| Geo-distributed EVPN/VXLAN and Soft-RoCE | Not part of the baseline | No dependency on the paper |

## Open Questions for Follow-Up

- Is a complete ScaleAcross experiment repository available from the authors?
- Which reported experiments can be independently reproduced from the published material?
- Would a project-specific CPU collective or TCP flow matrix reveal useful path behavior without
  importing the paper's topology or transport design?
- Which workload observations would add value beyond the existing routing and reachability
  verifier?
- What evidence would be required before making any CI or convergence claim about a future
  workload scenario?

## Bottom Line

ScaleAcross does not validate AI Factory Network Twin and is not a target for reproduction. It
is an adjacent example of combining a software network, controlled failures, path observations,
and a distributed workload in one experiment.

The useful contribution to this project is the experiment mindset. The topology, source of
truth, compiler, policy model, verifier, failure contracts, and fidelity claims remain owned and
defined independently by AI Factory Network Twin.
