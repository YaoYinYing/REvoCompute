# REvoCompute

REvoCompute is a Flask and Celery service for multi-user protein computation.
Task schemas, runtime ownership, resource policy, and scientific result
contracts are server-owned and configuration-driven.

## Where to start

| I want to… | Go to |
| --- | --- |
| Submit a task and read results | [User Guide](user-guide/index.md) |
| Install, deploy, and operate a server | [Operator Guide](operator-guide/index.md) |
| Add or maintain a scientific runner family | [Runner Guide](runner-guide/index.md) |
| Work on the Core server code | [Developer Guide](developer-guide/index.md) |
| Look up an API, format, or constant | [Reference](reference/server-api.md) |
| Understand the rules for AI coding agents | [Agents](agents/index.md) |

## How this documentation is organized

This site is the single published source of truth. Every page has exactly one
normative owner, selected by audience:

- `user-guide/` — people submitting and reading scientific tasks.
- `operator-guide/` — people installing, deploying, and running a server.
- `runner-guide/` — people authoring or maintaining a runtime family.
- `developer-guide/` — people changing Core server behavior.
- `reference/` — stable lookup material: APIs, formats, policies, families.
- `agents/` — invariants and protocols for automated contributors.

Content lives here and nowhere else. Repository-root files are entry points and
working notes only: [`README.md`](https://github.com/YaoYinYing/REvoCompute/blob/main/README.md)
orients a new clone, `CLAUDE.md` carries agent guidance, and `TODO*.md` files are
the maintainer backlog. None of them is a second documentation hierarchy.

See [Writing documentation](developer-guide/documentation.md) for the ownership
rule, the page conventions, and how to add a page to the navigation.
