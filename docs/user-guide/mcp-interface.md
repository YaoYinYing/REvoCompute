# Agent MCP Interface

REvoCompute exposes a first-class [Model Context Protocol](https://modelcontextprotocol.io)
(MCP) surface so agent hosts can discover, validate, submit, and track
scientific work through the protocol they already speak. This page documents the
endpoint, credentials, primitives, and limits of that surface.

The governing rule is the reason this page is short:

> **MCP is a protocol projection, not a new execution plane.**

MCP owns protocol adaptation, scoped opaque handles, structured presentation,
and transport interoperability. It does **not** own scientific truth,
execution, authorization, or operator control. Every operation terminates in the
same application the HTTP API and the Web application run, so the canonical
Task/Tool contracts, entitlement, readiness, admission, lifecycle,
ResultManifest, and artifact rules are the ones that apply.

## Endpoint and transport

- Transport: MCP **streamable HTTP** (the official SDK transport). There is no
  stdio wrapper in a deployment.
- Endpoint: `<base-url>/k/mcp` (the surface is mounted at `/k`).
- The MCP endpoint is served from the **same process** as the HTTP API when a
  deployment enables it, so the canonical rate limiter and application state are
  shared rather than replicated: mixing HTTP and MCP requests from one client
  address consumes one budget.

### Enabling the surface

Enabling MCP is a **deployment-owned opt-in** and is disabled by default: a
deployment that never sets `MCP_ENABLED` runs exactly as it did before this
setting existed, with no route, no overlay, and no listener. One switch,
`MCP_ENABLED`, decides the whole opt-in, so "is MCP deployed?" cannot be
answered two different ways. Turn it on by all three of

1. building the server image with the transport stack —
   `REVOCOMPUTE_EXTRAS=resend,mcp` in the deployment env file (the shipped
   default is `resend` alone); the transport is an image dependency, so the
   image must be rebuilt, not merely re-flagged;
2. setting `MCP_ENABLED=true` (and, if the default is unsuitable, `MCP_PORT`,
   default `8081`) in the deployment env file; and
3. running `bash run/restart.sh restart`, which layers
   `docker-compose.mcp.yml`, reconciles the gateway `location /k/` route from
   `MCP_ENABLED`, and starts the in-process listener.

If the web process can reach the deployment's own public base URL, also set
`MCP_GATEWAY_PROBE=true` so the capability verifies the endpoint through the
gateway rather than leaving it unverified (see below).

`bash run/restart.sh mcp-status` reports the switch, whether the route is
present, and whether the surface is really reachable. Reachability is not read
from the switch, and it is not read from the route file either: `GET
/compute/api/mcp` reports its facts separately — whether the companion listener
answered a real MCP `initialize` handshake in this process (`listener_ready`),
whether the gateway route state on disk declares a `/k/` route
(`route_configured`), and whether the deployment's own public endpoint answered
the same handshake through the gateway (`gateway_verified`). The surface is
`operational` — and the endpoint is advertised, and Home offers "Connect an AI
agent" — only when `gateway_verified` is `true`, that is, when the deployment's
own endpoint really answered. A healthy internal listener plus a route file is
**not** sufficient: a route file is a file fact, never proof the gateway serves
the route. `mcp-status` separately drives the same handshake through the gateway
route an agent host will use, so the operator's receipt does not rest on the web
process agreeing with itself.

`gateway_verified` is `null` when the deployment does not probe its own edge
(`MCP_GATEWAY_PROBE` unset), so a deployment that cannot reach its own public
base URL — air-gapped, or split DNS — reports reachability *unverified* rather
than asserting it, and advertises nothing. The destination is fixed by
`SERVER_BASE_URL`, never a caller-supplied URL, and the probe is a single
bounded request. The verdict it returns is held only briefly: a gateway answer
older than the freshness window is re-probed, so a gateway that goes down stops
being advertised and a gateway that is fixed starts being advertised again —
both without restarting the web process. The window is short enough for an
outage to be noticed and long enough that ordinary capability reads are answered
from memory; while one read is re-probing, another read reports the reach as
unverified rather than reusing the expired answer or starting a second probe. A
listener that bound while the gateway route is missing or
stale, a gateway that never reloaded after the route was written, or an upstream
that is down is therefore reported not operational — the endpoint a client is
given is reached through the gateway, not through the listener directly. A switch
set in the env file while the process serves nothing (a missing `mcp` extra, a
port that would not bind, a `restart` that has not run) is reported as an operator
problem, with the reason, rather than silently as "disabled" or happily as
"enabled". To roll back, set `MCP_ENABLED=false` and run
`bash run/restart.sh restart`: the route is removed and the process returns to its
pre-MCP shape.

Because the capability is a claim about *public* reachability, the Web
application shows the "Connect an AI agent" entry — and names the endpoint — only
when the capability says the endpoint really answers through the gateway. The
entry is never offered on the strength of the switch, of a healthy listener alone,
of a route file, or of MCP code existing in the repository.

While `MCP_ENABLED` is unset, `revocompute.app` logs `MCP surface disabled`, the
gateway's `include` of the route mask is empty, and the endpoint is absent rather
than pointed at a dead port.

#### Route and transport boundary

- Listener: a thread in the **canonical** web process on a container-internal
  port (`MCP_PORT`, default `8081`). That port is never published to the host, so
  nothing outside the compose network can reach the listener directly.
- Route: the gateway exposes exactly one location, `/k/`, over the compose
  network. The canonical per-route rate limiter, admission path, and application
  state are the ones that apply — there is no second service, no shadow limiter,
  and no second execution plane.

## Authentication

MCP v1 is a **scientific-user surface**. It accepts the credentials the HTTP API
already accepts and verifies them against the canonical user database:

- `Authorization: Bearer <token>` — a time-limited session token, or
- `X-API-Key: <key>` — a long-lived API key created through the Profile workflow.

Account state, token version, and every existing block rule are enforced exactly
as they are for HTTP. There is no MCP-specific account or role.

### Trust boundary

The scientific MCP surface can never reach operator control. It exposes no SIF
build/promote/repair, host Operator Job, service restart, admin log, readiness
repair, user or GPU-credit administration, secret, or bootstrap capability. An
administrator's ordinary credential does **not** turn this surface into an
operator interface. Operator MCP, if it is ever wanted, requires its own threat
model and design.

## Primitives

Progressive discovery instead of a static one-tool-per-Runner catalog.

### Tasks

| Tool | Purpose |
| --- | --- |
| `discover_tasks` | Compact catalog of the enabled TaskTypes. |
| `inspect_task` | One TaskType's input roles, parameter vocabulary, and parameter JSON Schema (bounded). |
| `preflight_task` | Validate a prospective submission against the canonical security, contract, and admission rules without creating a Task. |
| `submit_task` | Submit a Task; returns an opaque `task_handle`. |
| `get_task_status` | Lifecycle state for one owned handle. |
| `cancel_task` | Cancel one owned Task through the canonical cancellation path. |
| `get_task_results` | The finalized ResultManifest projection: logical files and bounded artifact metadata. |
| `retrieve_artifact` | One published artifact by its ResultManifest path, bounded. |

### Tools

| Tool | Purpose |
| --- | --- |
| `discover_tools` | The authenticated Tool catalog. |
| `inspect_tool` | One Tool's contract and parameter JSON Schema (bounded). |
| `call_tool` | Invoke one Tool; returns an opaque `tool_handle`. |
| `get_tool_call_status` | Lifecycle state for one owned Tool handle. |
| `get_tool_results` | A finished ToolCall's bounded output manifest. |
| `retrieve_tool_output` | One ToolCall output file, bounded. |

### Resources

- `revocompute://skills` — the canonical agent workflow guide
  ([`/skills.md`](../user-guide/submitting-tasks.md) is the same document over
  HTTP; there is one maintained source).
- `revocompute://task/{task_type}/schema` — one TaskType's canonical parameter
  JSON Schema.
- `revocompute://result/{task_handle}/manifest` — the owner-scoped
  ResultManifest summary for one handle.

## Long-running work and opaque handles

Scientific Tasks run for minutes to hours, so submission returns immediately
with an **opaque handle** rather than blocking the call:

```text
opaque MCP task handle  ->  owned REvoCompute Task
```

The handle is high-entropy, unpredictable, scoped to the authenticated user, and
expires (`MCP_HANDLE_TTL_SECONDS`, default one day). It is deliberately **not**
the REvoCompute Task ID: the Task ID is derived from submitted content, so it is
guessable and leaks scientific identity.

Every handle, result, and artifact access is re-authorized. A handle that
belongs to somebody else resolves to nothing — the same answer as a handle that
never existed — so one user cannot probe another user's work.

The server does not currently advertise the MCP protocol's own task objects: the
SDK used here does not implement that handler, and the surface must not
hand-roll protocol framing. The equivalent bounded interaction is
`submit_task` → `get_task_status` (poll to a terminal state) →
`get_task_results`.

## Context and resource limits

Large trajectories, tensors, and archives must not flood a model context:

- catalogs, schemas, result listings, and error detail are bounded;
- a small artifact or Tool output is inlined (bounded, with explicit size metadata);
- a large artifact returns **metadata only** — never inline content, and never a
  host, container, or object-store path.

A bounded result always says it was truncated; content is never silently
dropped.

## Structured responses and errors

Tool results are machine-readable. Failures carry a stable class so an agent can
recover without parsing a traceback, Slurm stderr, or an HTTP error string:

`INVALID_PARAMETERS`, `AUTH_REQUIRED`, `ACCESS_DENIED`, `NOT_READY`,
`RESOURCE_LIMIT`, `TASK_NOT_FOUND`, `TASK_NOT_CANCELLABLE`, `RESULT_NOT_READY`,
`ARTIFACT_NOT_FOUND`, `CONTENT_TOO_LARGE`.

Human-readable messages travel beside the class as secondary detail. The class
is derived from the canonical decision — the admission reason the submission
boundary produced, never a second local rule — so a resource or readiness reason
the server can emit maps to an actionable class (`RESOURCE_LIMIT`, `NOT_READY`)
rather than a bare `ACCESS_DENIED`.

## Publication and quarantined results

A finished Task is not automatically a readable result. Serving a result is a
publication decision the canonical Server owns: only a manifest the server
anchored at finalization — and can still verify — is a publication. `MCP` never
decides this itself, and it never serves a result the canonical surface refuses.

- `get_task_status` reports `results_available` from the canonical publication
  read, so a quarantined result is not advertised as available;
- `get_task_results` and `retrieve_artifact` refuse a quarantined or unanchored
  result with `RESULT_NOT_READY` and the canonical reason as detail — never with
  a manifest, cached archive bytes, or an empty payload that looks like data;
- a Task that simply has not finished keeps the ordinary not-ready answer.

This is the same gate the results page, the archive request, and the download
route use, so there is no MCP-specific path to a result.

## Retries and idempotency

MCP hosts retry after a disconnect or an ambiguous response. A repeated
`submit_task` for identical content resolves to the same canonical Task — the
existing content-derived Task identity and preparation claim — so a retry cannot
duplicate scientific work. `call_tool` accepts an `idempotency_key` that maps to
the canonical ToolCall identity. A retry never bypasses current authorization or
readiness checks.

## What MCP does not expose

By design, and permanently for this scientific surface: operator/admin
capability, arbitrary shell, arbitrary filesystem access, arbitrary URL fetch or
HTTP proxy, direct Slurm or container invocation, agent memory or preference
state, MCP Sampling and Elicitation, and any workflow engine. There is one
surface with one job: projecting REvoCompute's scientific contracts to agent
hosts.

## Interoperability testing

`tests/mcp_live_acceptance.py` starts the canonical web process with the MCP
surface enabled and drives the complete workflow — connect, discover, inspect,
preflight, submit, track, results, artifact — plus the negative cases (unknown
task type, invalid parameters, unentitled Runner, cross-user handle, cross-user
artifact, traversal, missing artifact, oversized artifact, quarantined result,
cancel, retried submission, invalid credentials, anonymous access) over a real
streamable-HTTP client. It **asserts** those expectations and exits non-zero on
any mismatch, printing a JSON receipt:

```bash
uv run --extra mcp python tests/mcp_live_acceptance.py
```

`tests/mcp_host_receipt.py` produces a JSON receipt per host:

```bash
uv run --extra mcp python tests/mcp_host_receipt.py
```

- the **MCP Inspector CLI** (`npx @modelcontextprotocol/inspector --cli`), and
- **Claude Code** as the primary intended agent host (`--mcp-config`).

The Inspector CLI receipt is a real, reproducing listing. The Claude Code receipt
records an honest outcome: when the host's non-interactive route is unavailable
(as on a dev host whose CLI resolves to a non-MCP harness model) it records
`exercised: false` with the raw cause rather than asserting success, so it must
not be read as "Claude Code fully accepted".

A second, genuinely independent MCP host and a rendered MCP Inspector Web UI were
**unavailable in this environment** and are an openly acknowledged gap: they must
be demonstrated against the final head before the MCP surface is considered fully
interoperability-accepted. See the PR description for the exact matrix of what
was and was not exercised.
