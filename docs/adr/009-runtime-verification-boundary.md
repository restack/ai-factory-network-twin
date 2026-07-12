# ADR-009: Runtime Execution and Verification Boundary

- **Status:** Accepted
- **Date:** 2026-07-12

## Context

M4 needs privileged local subprocesses and volatile FRR runtime data without
coupling verification logic to shell output, leaking unrelated labs, or
mistaking command transport success for a successful in-container check.

## Decision

All runtime commands pass through one argv-only subprocess executor with
captured output and bounded timeouts. A Containerlab adapter owns only scoped
deploy, inspect, exec, and destroy commands for one generated topology. It
never uses `destroy --all`.

Deployment requires a successful static-validation report, refuses an existing
lab unless reconfiguration is explicit, and inspects the lab after deployment.
Destroy is idempotent, requests Containerlab cleanup, and inspects again to
prove that matching resources are absent.

Runtime verification treats generated `expected-state.json` as its contract.
It polls BGP adjacency and route/ECMP convergence under a fixed deadline, then
runs all same-plane positive pings and cross-plane negative pings from the
appropriate Linux VRF. BGP and route JSON are normalized before comparison;
volatile counters, timestamps, and interface indexes are ignored.

Containerlab 0.77 returns exec transport status separately from each command's
inner `return-code`. The verifier always evaluates the inner code. FRR may emit
non-fatal `vtysh` warnings on stderr while returning valid JSON and code zero,
so stderr alone is retained as evidence but is not a failure condition.

## Consequences

- Unit tests inject executor and runtime fakes without shelling out.
- Privileged end-to-end validation is opt-in and local/self-hosted.
- Verification failures have stable BGP, route, reachability, or isolation rule
  IDs with a target, cause, and remediation hint.
- Parallel ping collection keeps the complete positive and negative matrices
  bounded while preserving deterministic report ordering.

## References

- [Containerlab deploy](https://containerlab.dev/cmd/deploy/)
- [Containerlab inspect](https://containerlab.dev/cmd/inspect/)
- [Containerlab exec](https://containerlab.dev/cmd/exec/)
- [Containerlab destroy](https://containerlab.dev/cmd/destroy/)
- [FRRouting BGP](https://docs.frrouting.org/en/stable-10.3/bgp.html)
- [FRRouting Zebra](https://docs.frrouting.org/en/stable-10.3/zebra.html)
- [Linux VRF](https://www.kernel.org/doc/html/next/networking/vrf.html)
