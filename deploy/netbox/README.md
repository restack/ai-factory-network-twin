# Local NetBox

This development environment pins NetBox 4.6.4 with NetBox Docker 5.0.1. It is
for local fixtures only and uses intentionally well-known development
credentials. The NetBox HTTP port is bound exclusively to the host loopback
interface (`127.0.0.1:8000`) and is not exposed on LAN or other host interfaces.
Do not change that binding or deploy this Compose stack on a shared or public
host; it is not a production configuration.

```bash
cp .env.example .env
just netbox-up
just seed
```

The default seed is `fixtures/mini-dual-plane.yaml`; run `just seed-smoke` for
the minimal development fixture. Both commands are idempotent, and the smoke
fixture is a strict subset of the golden fixture so they can be applied in
sequence. The CLI refuses to seed a non-loopback `NETBOX_URL` unless the
operator explicitly supplies `--allow-nonlocal`.

Open <http://localhost:8000> and sign in with `admin` / `admin`.

The fixed API token is a v2 token used only by this local fixture environment.
Production environments must provision a separate token and must not reuse any
credential from this Compose file. Production deployment also requires its own
network exposure, CORS, secret-management, and authentication configuration.

Stop the services while preserving data with `just netbox-down`. Delete all
local NetBox data with the explicit `just netbox-reset` command.
