# AI Factory Network Twin

NetBox-driven AI cluster network digital twin and validation lab.

The repository currently contains the M1 NetBox foundation: the Python package
and CLI contract, a pinned local NetBox environment, versioned smoke and
`mini-dual-plane` fixtures, an idempotent seeder, a read-only adapter, and typed
fabric domain models.
Network policy, compilation, and runtime verification are planned in
[`PLANNING.md`](PLANNING.md).

## Requirements

- Python 3.12 or newer
- [uv](https://docs.astral.sh/uv/)
- [just](https://just.systems/)

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
just test-netbox
just netbox-down
```

`just seed` loads the golden `mini-dual-plane` fixture. Use `just seed-smoke`
for the smaller one-spine/one-leaf development slice.

The Compose credentials are public development defaults and must never be used
outside the local fixture environment. See
[`deploy/netbox/README.md`](deploy/netbox/README.md) for lifecycle details.

This project validates network intent and functional control-plane behavior. It
does not simulate GPU, RDMA, switch ASIC, buffering, or line-rate performance.
