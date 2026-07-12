# ADR-007: Explicit Policy Profiles and Address Intent

- **Status:** Accepted
- **Date:** 2026-07-12

## Context

The `smoke` fixture intentionally contains only Plane A, while the golden
profile requires Planes A and B. Inferring required planes from observed data
would allow a broken dual-plane source to pass after an entire plane vanished.

NetBox interface addresses expose assigned networks, but do not by themselves
express which prefixes a future compiler will advertise.

## Decision

Store explicit policy profiles in Git. A profile defines required planes,
supported platforms, the required inclusion tag, expected spine count per
plane, point-to-point prefix length, and allowed address pools per plane.

M2 validates assigned interface addresses against these pools and rejects
overlapping configured plane pools. M3 must separately ensure that management
addresses are excluded when it generates expected advertisements and routing
configuration.

## Consequences

- Missing Plane B cannot weaken the golden profile by changing observed input.
- The smoke slice remains valid under its explicit single-plane profile.
- Address-pool ownership is reviewable in Git and independent of renderer code.
- M2 does not claim that assigned-address checks prove routing advertisement
  behavior; that guarantee belongs to compiler expected-state tests in M3.
