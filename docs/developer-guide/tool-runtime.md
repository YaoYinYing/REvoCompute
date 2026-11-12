# Authenticated Tool runtime

Tools are typed scientific utilities for small file inspection, extraction, and neutral representation conversion. They are independent from durable Runner Tasks: Tool calls are ephemeral service work, use one CPU, have no GPU or network, and never enter Slurm.

Each enabled family under `docker/tools/` owns one immutable Apptainer image and multiple `tool.yaml` contracts. The Server discovers only explicitly enabled families, validates their named input/output roles and JSON Schemas, persists a separate `tool_calls` lifecycle row, materializes inputs, and enqueues a call on the `tools` queue. Gunicorn never starts Apptainer.

The dedicated Tool worker serializes family startup with a cross-process file lock. It starts one generation-specific instance, performs the family health command, and executes every call in a fresh child process with only these mounts:

```text
/tool/input    read-only
/tool/output   read-write
/tool/scratch  read-write
```

The executor caps scientific-library threads, passes argv arrays, enforces the Tool/deployment timeout, terminates the process group on expiry, and publishes only files named by the typed response manifest. Path escapes, symlinks, undeclared roles, formats, output files, cardinalities, or an output volume beyond the headroom the call reserved fail the call; an oversized output never reaches the workspace.

A Tool may declare its own input-byte tier in `tool.yaml`. `limits.request_bytes` is the aggregate decoded budget for one call and cannot exceed the deployment `TOOL_REQUEST_MAX_BYTES` ceiling; `limits.input_bytes` bounds each role separately, so a small topology and a large trajectory are admitted under independent caps while their sum stays within the aggregate. A Tool that declares no tier keeps the ordinary 16 MiB budget, and enabling a larger tier is an explicit operator decision rather than a change to every Tool or ordinary Task upload. Encoded and decoded bytes stay independent through the shared `upload_encoding` admission helper.

When a child refuses a request for a known scientific or format reason, it writes a bounded `{"code", "message"}` document to `/tool/output/.tool-error.json` and exits non-zero. The worker publishes that code as the call's `error_class` and the message as `error`, so clients see a stable typed diagnostic instead of only the executor's generic failure. An absent or malformed document keeps the generic `conversion_failed` class.

Runtime warmth is process state, not SQLite state. A COLD family remains available. Three recent startup failures open a short circuit-breaker cooldown. Maintenance removes expired calls and oldest terminal calls under storage pressure, while idle-runtime shutdown is sent to the Tool worker because only that service owns Apptainer access.

Task artifacts can be passed to a Tool as named inputs: the reference is authorized, verified, and copied into the ephemeral Tool workspace, and the Tool input manifest records its source. A finished Tool output can be bound as a Task input by named role, without a browser download and re-upload: submission resolves `@tool_call_<id>/<output path>` for the caller, verifies the output against its result manifest, and quarantines the bytes through the same decoded budget and Core validators as an upload. The role snapshot and `task.json` record the Tool call, output path and digest as the input source.

The result manifest separates server-owned from child-declared provenance: `runtime_family`/`runtime_identity` come from the discovered runtime and are authoritative, while the child's self-reported `backend` is nested under `provenance.declared` so it can never contradict them.

Tests must exercise parsed contracts, database transitions, HTTP authorization, execution, scientific outputs, isolation, timeouts, cleanup, or real SIF behavior. Do not test Tool YAML, definition, script, documentation, or dependency text as static repository content.
