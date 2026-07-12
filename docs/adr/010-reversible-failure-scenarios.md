# ADR-010: Reversible Failure Injection

- **Status:** Accepted
- **Date:** 2026-07-12

## Context

M5 must prove that fabric connectivity survives a single leaf-to-spine link
failure and a single spine failure, then restore the original state without
recreating the lab or affecting unrelated Containerlab environments.

## Decision

Inject both failures by changing only the administrative state of generated
fabric interfaces through the existing scoped Containerlab exec boundary.

- Link failure sets one leaf uplink down.
- Spine failure sets every topology-derived data interface on one spine down.
- Restoration attempts every targeted interface in reverse order from a
  `finally` path, even after partial injection or verification failure.

Do not stop or pause containers. Stopping changes container/network namespace
lifecycle, while pausing leaves veth carrier up and delays BGP failure detection
until the hold timer. Interface state changes preserve the namespace, bind
mounts, management interface, and configuration while FRR fast external
failover reacts immediately.

Each scenario records four deterministic phases: healthy baseline, active
failure with full endpoint connectivity/isolation checks, interface restoration,
and bounded full BGP/route/ECMP recovery. A scenario passes only if the fault was
observed, connectivity survived, all interfaces were restored, and the complete
runtime verifier recovered.

## Consequences

- Scenarios are reproducible YAML contracts in `scenarios/`.
- Reports retain actionable injection, survival, restoration, and recovery
  failures below the build report directory.
- The scenario affects only one generated lab and never invokes global destroy.
- This validates control-plane redundancy and functional reachability, not
  hardware failure timing or packet-loss performance.

## References

- [Containerlab exec](https://containerlab.dev/cmd/exec/)
- [FRRouting BGP fast external failover](https://docs.frrouting.org/en/latest/bgp.html)
- [Docker pause semantics](https://docs.docker.com/reference/cli/docker/container/pause/)
