# REvoCompute

REvoCompute is a Flask + Celery service for multi-user protein computation. It
runs scientific task types through shared runtime families, on either a local
Docker executor or a production SLURM + Apptainer executor. Task schemas,
runtime ownership, resource policy, and scientific result contracts are
server-owned and configuration-driven; adding a task type normally requires no
change to server routing code.

**The documentation site under [`docs/`](docs/index.md) is the single source of
truth.** This README only orients a new clone and points into it.

## What the server provides

- **Task catalog from manifests.** The server discovers TaskTypes and runtime
  families from family-owned `plugin.yaml` and `task.yaml` files. There is no
  hand-maintained central task registry.
- **Multi-user identity and access.** Bearer tokens for interactive use, API
  keys for scripts, and per-family entitlements for restricted scientific
  software and data.
- **Derived Runner readiness.** A family is READY only with current Doctor,
  image, and target-host live-acceptance evidence. Readiness is never a mutable
  flag an operator sets.
- **Immutable task storage and provenance.** Original inputs are preserved as a
  role-resolved, hash-addressed snapshot; runner-prepared files are separate
  provenance artifacts.
- **Manifest-first results.** Completed tasks publish `manifest.json`, from which
  authenticated downloads and scientific result views are composed.

## Repository layout

| Path | Contents |
| --- | --- |
| `revocompute/` | Server package: API, Core, worker, maintenance, result views |
| `docs/` | The documentation site (published with MkDocs Material) |
| `tests/` | Server, integration, and runner-owned behavior tests |
| `docker/runners/<family>/` | Self-contained runtime families and task manifests |
| `docker/tools/` | Typed, ephemeral Tool family definitions |
| `run/` | Deployment controller: `restart.sh` and `revocompute_ctl/` |
| `config/access_policies/` | Declarative restricted-resource policies |

## Quickstart

Development stack (Docker Engine 24+ with the Compose plugin):

```bash
cp .env.example .env.local
REVODESIGN_SERVER_ENV=.env.local bash run/restart.sh setup
REVODESIGN_SERVER_ENV=.env.local bash run/restart.sh restart --mode=dev
```

Server-owned test suite (Python 3.12+):

```bash
pip install -e ".[test]"
make test
```

A fresh installation has no accounts until `restart.sh` creates the bootstrap
administrators named by `ADMIN_USERS` and prints their one-time passwords. See
[Installation and Host Preparation](docs/operator-guide/installation.md) and
[Deployment Control Reference](docs/operator-guide/deployment-control.md) for a
real deployment.

## Documentation map

| I want to… | Start here |
| --- | --- |
| Submit a task and read results | [User Guide](docs/user-guide/index.md) |
| Install, deploy, and operate a server | [Operator Guide](docs/operator-guide/index.md) |
| Add or maintain a runner family | [Runner Guide](docs/runner-guide/index.md) |
| Change Core server behavior | [Developer Guide](docs/developer-guide/index.md) |
| Look up an API, format, or family stack | [Reference](docs/reference/index.md) |
| Follow the rules for AI coding agents | [Agents](docs/agents/index.md) |

Build the documentation locally:

```bash
python -m pip install "mkdocs>=1.6,<2" "mkdocs-material>=9,<10"
mkdocs build --strict
```

The build fails on a broken link, a broken section anchor, or a page missing
from the navigation. See
[Writing Documentation](docs/developer-guide/documentation.md) before adding a
page.

## Contributing

- Agent guidance lives in [`CLAUDE.md`](CLAUDE.md); [`AGENTS.md`](AGENTS.md) is a
  symlink to it.
- The maintainer backlog is [`TODO.md`](TODO.md) and the focused `TODO_*.md`
  files at the repository root. These are working notes, not published guidance.
- Long refactors follow the [long-task protocol](docs/agents/long-task-handling.md).
- Do not restate server-owned values in code, configuration, or documentation.
  See [Architecture Invariants](docs/agents/architecture-invariants.md).
