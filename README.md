# AI Factory Network Twin

NetBox-driven AI cluster network digital twin and validation lab.

The repository currently contains the M1 NetBox foundation, M2 static policy
engine, M3 deterministic compiler, M4 deployment/runtime verification, and M5
reversible failure scenarios. It produces and deploys a Containerlab topology,
then verifies FRR BGP sessions,
routes and ECMP, Linux endpoint reachability, and cross-plane isolation against
generated expected state. The current implementation covers the functional MVP
in [`PLANNING.md`](PLANNING.md).

## Requirements

- Python 3.12 or newer
- [uv](https://docs.astral.sh/uv/)
- [just](https://just.systems/)
- Docker (for the local NetBox environment and endpoint image)
- Containerlab 0.77.0 (to validate or later deploy the generated topology)

## Start

```bash
just bootstrap
uv run aftwin --help
just check
```

Copy `.env.example` to `.env` before using commands that connect to NetBox.

## Local NetBox fixture workflow

```bash
cp .env.example .env
just netbox-up
just seed
just seed  # creates no duplicates
just validate
just compile
just graph  # open http://127.0.0.1:50080; stop with Ctrl+C
just endpoint-image
just lab-up
just verify
just scenario-link
just scenario-spine
just lab-down
just test-netbox
just netbox-down
```

`just seed` loads the golden `mini-dual-plane` fixture. Use `just seed-smoke`
for the smaller one-spine/one-leaf development slice. Seeding refuses a
non-loopback `NETBOX_URL` unless the operator explicitly passes
`aftwin seed --allow-nonlocal`; the bundled Compose service itself listens only
on `127.0.0.1:8000`.

When `--site` is omitted, source and lifecycle commands use `AFTWIN_SITE` from
the environment. `validate`, `compile`, and `lab up` can narrow that site's
devices with `--tag <slug>`. Source snapshots are explicit allowlists of fields
required for normalization, so unrelated NetBox fields are not persisted.

`just compile` writes deterministic artifacts to `build/aif-lab/`. Repeating
the command with unchanged source produces the same `manifest.json` build hash.
`just graph` serves the generated topology at <http://127.0.0.1:50080>. It uses
the topology file before deployment and enriches the same Spine–Leaf–Server
data with running Containerlab metadata after deployment. The project graph
template starts in a labeled Spine–Leaf–Server horizontal layout; use the
layout buttons to switch direction. The graph is a structural snapshot and
does not display the interface/BGP health changed by failure scenarios. Restart
`just graph` after recompiling so it reads the new topology snapshot. The graph
server runs in the foreground and stops with `Ctrl+C`.

If port `50080` is already occupied, pass an alternate loopback address:

```bash
just graph aif-lab 127.0.0.1:50081
```

The local endpoint image required by the generated topology can be prepared
with `just endpoint-image`. Local and remote runtime images use explicit
version tags, and the platform-map validator rejects unversioned or `latest`
references. Compatibility is proven by the Containerlab and NetBox integration
tests. `just lab-up` deploys only a statically validated, manifest-consistent
build. `just verify` writes
`build/aif-lab/reports/runtime-verification.json`, and `just lab-down` removes
only the matching lab and its runtime directory.

`just scenario-link` disables one Plane A leaf-to-spine interface and proves
that endpoint connectivity survives through the alternate spine.
`just scenario-spine` disables every data interface on one Plane A spine and
proves the plane remains reachable. Both commands restore every interface in a
`finally` path and require the full BGP/route/ECMP verifier to pass afterward.
Scenario evidence is written below `build/aif-lab/reports/scenarios/`.
Each report identifies its scenario revision, source revision, and build hash.
Recompilation clears reports from an older build so stale evidence cannot be
mistaken for current results.

Run the privileged local Containerlab integration suite with
`just test-containerlab`. The test always destroys its ephemeral lab in a
`finally` cleanup path.

## One-command demo

With Docker, Containerlab 0.77.0, `uv`, and `just` installed, run:

```bash
just demo
```

The demo starts the versioned local NetBox environment, builds the endpoint image,
seeds and validates the fixture, compiles and deploys the lab, runs baseline
verification and both failure scenarios, verifies recovery, then destroys the
lab and stops NetBox. A trap performs scoped cleanup if any step fails. The
development token used by the Compose fixture is local-only and is never
printed.

The Compose credentials are public development defaults and must never be used
outside the local fixture environment. See
[`deploy/netbox/README.md`](deploy/netbox/README.md) for lifecycle details.

This project validates network intent and functional control-plane behavior. It
does not simulate GPU, RDMA, switch ASIC, buffering, or line-rate performance.
