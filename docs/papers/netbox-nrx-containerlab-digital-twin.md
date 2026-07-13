# NetBox, NRX, and Containerlab: An Adjacent Digital-Twin Implementation Pattern

## Source

- **Title:** Netbox + NetReplica + Containerlab
- **Organization:** srl-labs and the NetReplica ecosystem
- **Type:** Open-source lab and implementation reference
- **Reviewed revisions:**
  - [`srl-labs/netbox-nrx-clab@a2eec5a`](https://github.com/srl-labs/netbox-nrx-clab/tree/a2eec5a56fcf818583f3e68d0349ef92a5b7900f)
  - [`netreplica/nrx@95548cc`](https://github.com/netreplica/nrx/tree/95548cc1cb06974559d23279218b5b6c1312dd6a)
  - [`netreplica/templates@e6db169`](https://github.com/netreplica/templates/tree/e6db1696f7117e66c31a11507776f2f1d5e29e3f)
- **Reviewed:** 2026-07-13

## Relationship to This Project

The NetBox–NRX–Containerlab lab and AI Factory Network Twin are independent projects.

AI Factory Network Twin does not reproduce this lab, depend on NRX, or claim compatibility with
its generated artifacts. The lab is an adjacent implementation reference that demonstrates one
way to turn selected NetBox data into a runnable network replica.

This note separates what the reference actually implements from ideas that AI Factory Network
Twin adopts independently.

## One-Line Takeaway

The reference lab provides a concrete example of a NetBox-to-Containerlab workflow; its value to
AI Factory Network Twin is as a comparison point for source selection, platform mapping, artifact
generation, and change rehearsal—not as a prescribed compiler architecture.

## What the Reference Lab Implements

The lab provides scripts and data for the following flow:

```text
seeded NetBox
→ select the SYD1 site and demo-tagged devices
→ use NRX and a platform map to generate SYD1.clab.yaml
→ deploy an SR Linux topology with Containerlab
→ render and push configuration with a separate Python script
→ rehearse an IGP migration and inspect operational state
```

The generated example contains six SR Linux network nodes—two superspines, two spines, and two
leaves—plus a Graphite visualization container. The lab's documented environment was tested
with Ubuntu 22.04.4, Containerlab 0.51.2, Docker Engine 25.0.3, and Docker Compose 2.24.5.

Its configuration-management script queries NetBox independently of NRX. It selects templates
by device role, renders physical and logical interfaces, IP addressing, OSPF, IS-IS, and BGP,
shows a diff, and pushes the resulting configuration to SR Linux devices.

## The Demonstrated Change Rehearsal

The concrete operational example is an IGP migration rather than a failure-injection test:

1. Begin with a global OSPF underlay.
2. Add pod-local IS-IS configuration using NetBox device tags.
3. Confirm that IS-IS adjacencies form and both OSPF and IS-IS routes exist.
4. Change the NetBox tag to the final state and remove OSPF.
5. Confirm that IS-IS routes become active while BGP neighbor uptime remains stable.

The repository reports this transition as hitless for the pod's BGP-signaled overlay traffic.
That is evidence for the documented lab workflow; this note has not independently reproduced
the result.

## What NRX Contributes

NRX is broader than the one demonstration repository. At the reviewed revision, its documented
capabilities include:

- connecting to NetBox through its API,
- selecting devices by site, tags, and device roles,
- exporting direct cables and traced connections through patch panels and circuits,
- exporting device configurations when templates produce them,
- rendering Containerlab, Cisco Modeling Labs, NVIDIA Air, visualization, and custom formats,
- using NetBox device fields, tags, and custom fields in Jinja templates,
- mapping NetBox platform slugs to templates, images, and node parameters, and
- translating physical interface names into names supported by an emulated platform.

This matters when comparing reuse options: NRX is not merely a node-and-link YAML converter.
It already owns useful generic extraction and rendering behavior.

## Architecture of the Reference

The reference pattern can be summarized as:

```text
NetBox
  stores inventory, topology, interfaces, sites, tags, and configuration inputs

NRX
  selects a network subgraph and renders topology artifacts

Platform map and templates
  translate NetBox platform data into emulated node details

Containerlab
  runs the generated topology

Separate configuration script
  renders, diffs, and pushes SR Linux configuration

Operator
  changes NetBox tags and manually inspects the rehearsed migration
```

This is the implementation described by the source. It should not be confused with the
AI Factory Network Twin architecture.

## Limits of the Reference for This Project

The lab proves that its documented workflow can produce and operate a useful executable replica,
but it does not establish several contracts required by AI Factory Network Twin:

- AI-fabric-specific plane, rail, Clos, and failure-domain semantics,
- deterministic and byte-identical compilation,
- a machine-readable expected-state artifact,
- automated expected-versus-observed runtime verification,
- stable project policy findings,
- reversible failure scenarios with restoration evidence,
- the project's FRR and Linux endpoint backend, or
- workload-aware AI-fabric experiments.

The reference also uses SR Linux and example output with floating `latest` image tags, while AI
Factory Network Twin pins its runtime and images. The source's manual operational checks remain
useful, but they are not equivalent to this project's automated verification contract.

These differences do not make either implementation incomplete. They reflect different goals.

## Transferable Ideas

### Select an Executable Subgraph from the Source of Truth

The lab demonstrates that an executable twin does not need to export every object in NetBox. It
selects a site and tag-scoped subgraph appropriate for the experiment.

AI Factory Network Twin independently applies the same general idea through its own source
adapter and normalized domain model. The selection rules and required metadata are project-owned.

### Keep Platform Mapping Explicit

NRX makes the translation from NetBox platform values to runtime templates and images visible in
a mapping file. This is a useful generic pattern for any multi-platform twin.

AI Factory Network Twin independently defines a stricter mapping contract that also pins images
and associates renderers and supported capabilities with a backend. Its accepted contract is
recorded in [ADR-008](../adr/008-containerlab-platform-and-rendering.md).

### Treat Generated Runtime Files as Artifacts

The lab generates a Containerlab topology from NetBox instead of maintaining the lab topology as
the primary design input. That direction is useful even though the reference does not claim the
same deterministic-build guarantees as this project.

For AI Factory Network Twin, NetBox and Git-owned policy are inputs; topology, configuration,
expected state, inventory, and manifests are generated outputs. That is an independent project
contract, not a property inferred from NRX.

### Rehearse an Operational Change

The OSPF-to-IS-IS example shows why an executable replica can be more useful than a static
diagram: an operator can stage a transition and inspect control-plane continuity before changing
another environment.

AI Factory Network Twin adapts the broader rehearsal idea to project-specific validation and
failure scenarios. It does not copy the IGP migration or its tag-driven configuration process.

## Build-versus-Reuse Assessment

The source does not by itself imply that AI Factory Network Twin must wrap NRX or replace it with
a custom compiler. That decision follows from this project's requirements.

| Capability | NRX or reference lab | AI Factory Network Twin requirement | Current project direction |
| --- | --- | --- | --- |
| NetBox topology extraction | Supported for generic network graphs | Normalize AI-fabric-specific intent | Project-owned adapter; compare with NRX |
| Platform and interface mapping | Supported and customizable | Versioned mappings with strict image and backend contracts | Project-owned mapping inspired by the generic pattern |
| Topology and config rendering | Supported through Jinja templates and a separate lab script | Deterministic Containerlab, FRR, endpoint, and manifest artifacts | Project-owned compiler |
| Static AI-fabric policy | Not a stated NRX responsibility | Plane, Clos, addressing, and failure-domain findings | Project-owned policy engine |
| Expected runtime state | Not produced by the reference workflow | BGP, routes, ECMP, reachability, and isolation contracts | Project-owned expected-state model |
| Runtime verification | Manual checks in the demonstrated migration | Normalized, automated expected-versus-observed findings | Project-owned verifier |
| Reversible failure evidence | Not the demonstrated use case | Bounded injection, restoration, and recovery report | Project-owned scenario runner |

NRX therefore remains useful as a reference implementation and possible comparison baseline.
The project-specific compiler is a deliberate product decision, not a conclusion that the
reference lab is deficient.

## Independent AI Factory Network Twin Architecture

The project-owned workflow is:

```text
NetBox API response
→ normalized inventory snapshot
→ AI-fabric domain model
→ static policy findings
→ generated topology, configuration, and expected state
→ Containerlab runtime
→ normalized observations and verification report
→ optional reversible scenario report
```

The additional layers exist because this project is building a different digital twin with a
different validation contract.

### Stable Project Rules

Policy IDs are part of the project's public machine-readable contract. Examples should use the
actual catalog rather than conceptual IDs:

```text
PLN004: compute or storage node missing a required plane interface
PLN003: link and endpoint interface planes are inconsistent
GEN007: one ASN is assigned to multiple network devices
CLS001: spine inventory or leaf-to-spine neighbor set differs from policy
```

The complete list is maintained in the
[Static Policy Rule Catalog](../policy-rules.md).

### Expected State as a Project Artifact

The reference lab can be validated through operator checks. AI Factory Network Twin goes further
for its own use case by compiling machine-readable expectations before deployment:

- expected BGP adjacencies,
- expected route prefixes and ECMP next-hop counts,
- expected endpoint reachability,
- expected plane isolation, and
- evidence tied to a compiler build identity.

Deploying containers alone is not considered verification in this project, but this statement
does not diminish the source lab's separate manual validation workflow.

## Ideas Not Adopted from the Reference

The project does not inherit:

- NRX as a runtime or compiler dependency,
- the source lab's SR Linux topology,
- Graphite as a required service,
- its Python configuration-management script,
- NetBox tags as the IGP migration state machine,
- the OSPF-to-IS-IS scenario, or
- its exact templates, paths, credentials, and image choices.

Any future NRX integration would need an explicit compatibility contract and must not determine
AI-fabric policy semantics.

## Project Adoption Status

| Adjacent implementation idea | Status in this project | Project-owned reference |
| --- | --- | --- |
| NetBox-derived executable topology | Adopted independently | Project adapter and compiler |
| Explicit platform mapping | Adopted independently | [ADR-008](../adr/008-containerlab-platform-and-rendering.md) |
| Expected-versus-observed verification | Project-specific extension | [ADR-009](../adr/009-runtime-verification-boundary.md) |
| Reversible failure rehearsal | Project-specific extension | [ADR-010](../adr/010-reversible-failure-scenarios.md) |
| NRX output comparison | Follow-up research | No production dependency |
| NRX backend integration | Deferred and optional | Requires a separate decision |

## Open Questions for Follow-Up

- How does NRX output for the same NetBox fixture differ from the project compiler's topology?
- Which NRX extraction and interface-mapping behaviors could reduce duplicated generic work?
- Can a comparison be performed without making NRX part of the production architecture?
- Which source revision and runtime versions are needed for a repeatable lab reproduction?
- Are any project requirements better expressed as reusable NRX extensions rather than private
  rendering behavior?

## Bottom Line

The NetBox–NRX–Containerlab lab is a useful adjacent implementation of a source-of-truth-driven
executable network replica. It supplies concrete patterns and a comparison baseline, but it does
not define or validate AI Factory Network Twin.

AI Factory Network Twin independently owns its domain model, deterministic compiler, policy
rules, expected state, verifier, failure scenarios, and fidelity claims. Ideas from the reference
are adopted only where they help those project-specific goals.
