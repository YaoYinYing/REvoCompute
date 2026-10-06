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
  deployment enables it (`MCP_ENABLED=true`), so the canonical rate limiter and
  application state are shared rather than replicated: mixing HTTP and MCP
  requests from one client address consumes one budget.

```bash
REVODESIGN_SERVER_ENV=<env-file> restart.sh up --with-mcp   # enables the MCP surface
```

A deployment without the optional `mcp` extra installs and runs exactly as
before; the endpoint is simply absent.

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
- a small text/JSON artifact is inlined (bounded, with explicit size metadata);
- a large artifact returns **metadata plus an authorized resource link**, never
  inline content, and never a host, container, or object-store path.

A bounded result always says it was truncated; content is never silently
dropped.

## Structured responses and errors

Tool results are machine-readable. Failures carry a stable class so an agent can
recover without parsing a traceback, Slurm stderr, or an HTTP error string:

`INVALID_PARAMETERS`, `AUTH_REQUIRED`, `ACCESS_DENIED`, `NOT_READY`,
`RESOURCE_LIMIT`, `TASK_NOT_FOUND`, `TASK_NOT_CANCELLABLE`, `RESULT_NOT_READY`,
`ARTIFACT_NOT_FOUND`, `CONTENT_TOO_LARGE`.

Human-readable messages travel beside the class as secondary detail.

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
status, results, artifact — plus the negative cases (unknown task type, cross-user
handle, traversal, missing artifact, anonymous access) over a real
streamable-HTTP client, printing a JSON receipt:

```bash
uv run --extra mcp python tests/mcp_live_acceptance.py --json
```
