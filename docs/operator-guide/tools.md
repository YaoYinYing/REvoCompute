# Tool runtime operations

Tool families are disabled unless listed in `ENABLED_TOOL_FAMILIES`. Build each enabled family definition into the immutable `TOOL_IMAGE_DIR` as `<family>.sif`, then run `revocompute doctor --strict --probe`. A family can be healthy while COLD; the first call starts it and later calls reuse its environment through fresh processes.

The dedicated `tool-worker` receives only the Tool definitions, Tool SIFs, deployment state, Redis, and the Apptainer client. It does not receive the Docker socket, GPUs, Slurm clients, or MUNGE. The web and maintenance services do not receive Apptainer execution privileges.

| Variable | Default | Meaning |
| --- | ---: | --- |
| `ENABLED_TOOL_FAMILIES` | empty | Comma-separated family IDs, initially `bioio,chemio`. |
| `TOOL_REQUEST_MAX_BYTES` | `16777216` | Deployment ceiling for one call's aggregate decoded input bytes; a Tool's own `limits.request_bytes` cannot exceed it. |
| `TOOL_IMAGE_DIR` | `${SERVER_DIR}/../images/tools` | Immutable candidate SIF directory. |
| `TOOL_MAX_ACTIVE_PER_USER` | `3` | Maximum nonterminal calls for one user. |
| `TOOL_MAX_ACTIVE_GLOBAL` | `8` | Maximum nonterminal calls across users. |
| `TOOL_WORKER_CONCURRENCY` | `2` | Dedicated Celery worker child count. |
| `TOOL_CALL_TIMEOUT_SECONDS` | `300` | Deployment maximum; a Tool may declare less. |
| `TOOL_CALL_TTL_SECONDS` | `86400` | Retention after a terminal state. |
| `TOOL_RUNTIME_IDLE_TTL_SECONDS` | `1800` | Warm-family idle lifetime. |
| `TOOL_STORAGE_MAX_BYTES` | `104857600` | Hard cap on accounted bytes: actual usage plus each active call's reserved output headroom. |
| `TOOL_OUTPUT_MAX_BYTES` | `33554432` | Maximum declared output bytes per call. |
| `TOOL_DRAIN_TIMEOUT_SECONDS` | call timeout + 10 | Maximum bounded redeploy drain wait. |

Decoded uploads and verified Task-artifact references are charged to the
selected Tool's aggregate budget during admission. A Tool that declares
`limits.input_bytes` also bounds each role separately.

A Task that binds a finished Tool output receives the bytes under a separate
server-owned quota equal to `TOOL_OUTPUT_MAX_BYTES` (32 MiB by default) per file
and in aggregate. This is deliberately independent of the 16 MiB browser-upload
budget, because the Tool already bounded its complete output under the same
ceiling. The reference count, role cardinality and file count are checked from
metadata before any output bytes are hashed.

The `mdconvert` family is an opt-in large-input Tool: it turns one GROMACS GRO
topology and one XTC trajectory into CAVER PDB snapshots. Enabling it requires
`ENABLED_TOOL_FAMILIES=...,mdconvert`, `TOOL_REQUEST_MAX_BYTES=108000000` (the
family's own `limits.request_bytes`), `TOOL_STORAGE_MAX_BYTES=268435456`
(256 MiB, above one call's input plus output headroom), and a gateway
`TOOL_CLIENT_MAX_BODY_SIZE` of at least `TOOL_REQUEST_MAX_BYTES` plus the 1 MiB
multipart headroom. Its decoded limits are 100,000,000 bytes for the trajectory,
8,000,000 bytes for the topology and 108,000,000 bytes in aggregate; these are
decimal bytes, not MiB. Ordinary Tools keep their 16 MiB budget; a family whose
declared tier exceeds `TOOL_REQUEST_MAX_BYTES` fails discovery rather than
starting with a silently smaller budget. Amber,
CHARMM/NAMD, LAMMPS and OpenMM pairs are not enabled until their unit, atom-order
and periodic-box contracts have an audited proof, and are refused rather than
guessed. The family's `requirements.lock` pins the parser and every wheel hash;
build its SIF directly with Apptainer and do not install that stack into the
Server image or a Runner SIF.

Use `revocompute-tool-status --json` inside the Tool worker to inspect image identity, COLD/WARM/UNAVAILABLE state, active calls, last use, recent startup failure, cold starts, warm hits, and idle shutdowns. This output contains no user filenames, parameters, sequences, structures, or molecules.

For deployment, pause admission, allow active calls at most the configured five-minute bound, stop the old Tool worker and its generation-specific instances, deploy definitions and SIFs together, then restart web, maintenance, and workers COLD. Do not pre-warm families. Use a shortened idle TTL for acceptance and prove cold start, warm reuse, concurrent single-flight startup, workspace isolation, timeout recovery, idle stop, and cold restart before production enablement.
