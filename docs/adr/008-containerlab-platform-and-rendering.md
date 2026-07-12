# ADR-008: Containerlab Platform and Rendering Contract

- **Status:** Accepted
- **Date:** 2026-07-12

## Context

M3 must turn validated, normalized intent into a deterministic Containerlab
topology. Router and endpoint images, startup behavior, bind paths, and generated
file identities must remain reviewable and reproducible across builds.

## Decision

Use Containerlab 0.77.0 as the tested topology parser and runtime version.
Represent both FRR routers and Linux compute endpoints with Containerlab's
generic `linux` kind.

Routers use the official FRR 10.3.4 Quay image pinned by its multi-architecture
manifest digest. Each router receives read-only `daemons` and `frr.conf` binds.
The generated daemon file enables BGP and the generated FRR configuration
contains only explicit loopback and fabric advertisements; it does not use
`redistribute connected`.

Compute endpoints use the project-owned `aftwin-endpoint:0.1.0` image. Its
Dockerfile pins the Alpine 3.22 base digest and package versions. Containerlab
runs a read-only generated setup script after data links exist; that script
creates per-plane VRFs, assigns interfaces, and installs a static default route
for each plane.

The Git-owned mapping is versioned in `config/platform-map.yaml`. Generated
topology, configuration, expected state, inventory, and manifest files use
stable ordering and final newlines. The build hash covers compiler pipeline
outputs and excludes Containerlab runtime working directories.

## Consequences

- Router startup does not need a custom wrapper or mutable configuration bind.
- Configuration changes require recompilation and redeployment.
- The endpoint image must be built locally before the first M4 deployment.
- Runtime privileges remain Containerlab's concern; generated nodes declare
  only the forwarding and reverse-path-filter sysctls required by the lab.
- Image or package upgrades require an intentional platform-map, Dockerfile,
  golden-output, and integration-test update.

## References

- [Containerlab Linux kind](https://containerlab.dev/manual/kinds/linux/)
- [Containerlab node configuration](https://containerlab.dev/manual/nodes/)
- [FRRouting 10.3.4 release](https://github.com/FRRouting/frr/releases/tag/frr-10.3.4)
- [FRRouting container startup](https://github.com/FRRouting/frr/blob/frr-10.3.4/docker/alpine/docker-start)
- [Linux VRF documentation](https://docs.kernel.org/networking/vrf.html)
