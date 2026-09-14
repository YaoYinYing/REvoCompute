# Tool runtime operations

Tool families are disabled unless listed in `ENABLED_TOOL_FAMILIES`. Build each enabled family definition into the immutable `TOOL_IMAGE_DIR` as `<family>.sif`, then run `revocompute doctor --strict --probe`. A family can be healthy while COLD; the first call starts it and later calls reuse its environment through fresh processes.

The dedicated `tool-worker` receives only the Tool definitions, Tool SIFs, deployment state, Redis, and the Apptainer client. It does not receive the Docker socket, GPUs, Slurm clients, or MUNGE. The web and maintenance services do not receive Apptainer execution privileges.

| Variable | Default | Meaning |
| --- | ---: | --- |
| `ENABLED_TOOL_FAMILIES` | empty | Comma-separated family IDs, initially `bioio,chemio`. |
| `TOOL_IMAGE_DIR` | `${SERVER_DIR}/../images/tools` | Immutable candidate SIF directory. |
| `TOOL_MAX_ACTIVE_PER_USER` | `3` | Maximum nonterminal calls for one user. |
| `TOOL_MAX_ACTIVE_GLOBAL` | `8` | Maximum nonterminal calls across users. |
| `TOOL_WORKER_CONCURRENCY` | `2` | Dedicated Celery worker child count. |
| `TOOL_CALL_TIMEOUT_SECONDS` | `300` | Deployment maximum; a Tool may declare less. |
| `TOOL_CALL_TTL_SECONDS` | `86400` | Retention after a terminal state. |
| `TOOL_RUNTIME_IDLE_TTL_SECONDS` | `1800` | Warm-family idle lifetime. |
| `TOOL_STORAGE_MAX_BYTES` | `104857600` | Total managed ephemeral workspace accounting budget. |
| `TOOL_REQUEST_MAX_BYTES` | `16777216` | Maximum total materialized input bytes per call. |
| `TOOL_OUTPUT_MAX_BYTES` | `33554432` | Maximum declared output bytes per call. |
| `TOOL_DRAIN_TIMEOUT_SECONDS` | call timeout + 10 | Maximum bounded redeploy drain wait. |

Use `revocompute-tool-status --json` inside the Tool worker to inspect image identity, COLD/WARM/UNAVAILABLE state, active calls, last use, recent startup failure, cold starts, warm hits, and idle shutdowns. This output contains no user filenames, parameters, sequences, structures, or molecules.

For deployment, pause admission, allow active calls at most the configured five-minute bound, stop the old Tool worker and its generation-specific instances, deploy definitions and SIFs together, then restart web, maintenance, and workers COLD. Do not pre-warm families. Use a shortened idle TTL for acceptance and prove cold start, warm reuse, concurrent single-flight startup, workspace isolation, timeout recovery, idle stop, and cold restart before production enablement.
