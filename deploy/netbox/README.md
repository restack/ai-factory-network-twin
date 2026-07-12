# Local NetBox

This development environment pins NetBox 4.6.4 with NetBox Docker 5.0.1. It is
for local fixtures only and uses intentionally public development credentials.

```bash
cp .env.example .env
just netbox-up
just seed
```

The default seed is `fixtures/mini-dual-plane.yaml`; run `just seed-smoke` for
the minimal development fixture. Both commands are idempotent, and the smoke
fixture is a strict subset of the golden fixture so they can be applied in
sequence.

Open <http://localhost:8000> and sign in with `admin` / `admin`.

The fixed API token is a v2 token used only by this local fixture environment.
Production environments must provision a separate token and must not reuse any
credential from this Compose file.

Stop the services while preserving data with `just netbox-down`. Delete all
local NetBox data with the explicit `just netbox-reset` command.
