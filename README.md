# AI Factory Network Twin

NetBox-driven AI cluster network digital twin and validation lab.

The repository currently contains the M1 NetBox foundation, M2 static policy
engine, and M3 deterministic compiler. It produces a Containerlab topology,
FRR configurations, Linux endpoint VRF setup, expected runtime state, inventory,
and a content-addressed manifest from validated NetBox intent. Deployment and
runtime verification are the next milestone in [`PLANNING.md`](PLANNING.md).

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
just test-netbox
just netbox-down
```

`just seed` loads the golden `mini-dual-plane` fixture. Use `just seed-smoke`
for the smaller one-spine/one-leaf development slice.

`just compile` writes deterministic artifacts to `build/aif-lab/`. Repeating
the command with unchanged source produces the same `manifest.json` build hash.
The local endpoint image required by the generated topology can be prepared
with `just endpoint-image`; it is not deployed until M4.

The Compose credentials are public development defaults and must never be used
outside the local fixture environment. See
[`deploy/netbox/README.md`](deploy/netbox/README.md) for lifecycle details.

This project validates network intent and functional control-plane behavior. It
does not simulate GPU, RDMA, switch ASIC, buffering, or line-rate performance.
