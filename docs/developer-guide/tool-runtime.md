# Authenticated Tool runtime

Tools are typed scientific utilities for small file inspection, extraction, and neutral representation conversion. They are independent from durable Runner Tasks: Tool calls are ephemeral service work, use one CPU, have no GPU or network, and never enter Slurm.

Each enabled family under `docker/tools/` owns one immutable Apptainer image and multiple `tool.yaml` contracts. The Server discovers only explicitly enabled families, validates their named input/output roles and JSON Schemas, persists a separate `tool_calls` lifecycle row, materializes inputs, and enqueues a call on the `tools` queue. Gunicorn never starts Apptainer.

The dedicated Tool worker serializes family startup with a cross-process file lock. It starts one generation-specific instance, performs the family health command, and executes every call in a fresh child process with only these mounts:

```text
/tool/input    read-only
/tool/output   read-write
/tool/scratch  read-write
```

The executor caps scientific-library threads, passes argv arrays, enforces the Tool/deployment timeout, terminates the process group on expiry, and publishes only files named by the typed response manifest. Path escapes, symlinks, undeclared roles, formats, output files, or cardinalities fail the call.

Runtime warmth is process state, not SQLite state. A COLD family remains available. Three recent startup failures open a short circuit-breaker cooldown. Maintenance removes expired calls and oldest terminal calls under storage pressure, while idle-runtime shutdown is sent to the Tool worker because only that service owns Apptainer access.

Task artifacts can be passed to a Tool as named inputs: the reference is authorized, verified, and copied into the ephemeral Tool workspace, and the Tool input manifest records its source. Task submission does not accept Tool output references: a Tool output is downloaded from the Tool call, not promoted into a Task snapshot.

Tests must exercise parsed contracts, database transitions, HTTP authorization, execution, scientific outputs, isolation, timeouts, cleanup, or real SIF behavior. Do not test Tool YAML, definition, script, documentation, or dependency text as static repository content.
