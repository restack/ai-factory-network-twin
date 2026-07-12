# AI Factory Network Twin

NetBox-driven AI cluster network digital twin and validation lab.

This repository currently contains the M0 project scaffold. It establishes the
Python package, CLI contract, settings, structured errors, and development checks.
Network compilation and runtime behavior are planned for later milestones in
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
