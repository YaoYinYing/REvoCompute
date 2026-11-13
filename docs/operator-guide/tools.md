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
`ENABLED_TOOL_FAMILIES=...,mdconvert`, a `TOOL_REQUEST_MAX_BYTES` at least the
family's projected `limits.request_bytes`, a `TOOL_STORAGE_MAX_BYTES` above one
call's input plus output headroom, and a gateway `TOOL_CLIENT_MAX_BODY_SIZE` of
at least `TOOL_REQUEST_MAX_BYTES` plus the 1 MiB multipart headroom. Read the
family's per-role and aggregate decoded limits from
`GET /compute/api/tools/md_trajectory_convert`; they are the manifest-owned
`limits.input_bytes`/`limits.request_bytes` values, expressed in decimal bytes,
not MiB, and this page does not restate them. Ordinary Tools keep their 16 MiB
budget; a family whose declared tier exceeds `TOOL_REQUEST_MAX_BYTES` fails
discovery rather than starting with a silently smaller budget. Amber,
CHARMM/NAMD, LAMMPS and OpenMM pairs are not enabled until their unit, atom-order
and periodic-box contracts have an audited proof, and are refused rather than
guessed. The family's `requirements.lock` pins the parser and every wheel hash;
build its SIF directly with Apptainer and do not install that stack into the
Server image or a Runner SIF.

Build the family SIF from its own directory, because `%files` paths in the
definition are relative to the build working directory:

```bash
cd docker/tools/mdconvert
apptainer build mdconvert.sif mdconvert.def
apptainer test mdconvert.sif
apptainer exec mdconvert.sif python3 /opt/revocompute-tool/tool_cli.py health
```

The output is `docker/tools/mdconvert/mdconvert.sif`. Record its SHA-256 and copy
it to the target deployment's `TOOL_IMAGE_DIR` as `mdconvert.sif`; the
`requirements.lock` install remains the definition's only dependency source and
is verified with `--require-hashes` during the build. Building with the
repository-root path `apptainer build docker/tools/mdconvert/mdconvert.sif
docker/tools/mdconvert/mdconvert.def` does not work, because `%files` resolves
against the caller's working directory.

### mdconvert scientific contract

The released input pair is GROMACS **GRO + XTC**, read by the pinned
MDAnalysis 2.9.0 stack. Amber PRMTOP/NetCDF, CHARMM/NAMD PSF+DCD, LAMMPS
DATA+trajectory and OpenMM PDB/mmCIF+DCD remain disabled until their unit,
atom-order and periodic-box contracts have an audited proof; the Tool refuses
those pairs with `unsupported_format_pair` rather than guessing.

The conversion preserves source atom order and the topology's atom, residue
and frame identity, applies the GRO reader's nm-to-Angstrom contract exactly
once, and records original frame times and unit cells. It never reconstructs
periodic wrapping, changes chemistry, hydrogens, charges, protonation or
missing atoms, and it refuses unwrapping without bond evidence. Output is one
reference PDB plus at most 50 ordered single-model snapshots (51 total), each
with a member of the same stable atom map. GRO carries no chain or element
column, so every atom is written to PDB chain `X` with a blank element; the
manifest emits `chain_identity_synthetic` and `elements_not_representable`, and
selected atoms whose chain/residue/atom identity would collide are refused.
CAVER start-point and radius inference on that representation requires the
external CAVER JAR acceptance and is not claimed by synthetic fixtures.

The family's `conversion_manifest.json` records source SHA-256 and sizes,
parser versions, the atom-map digest, representation policy, selected frame
times and boxes, transitions, warnings and output hashes. Child refusals are
published as typed `error_class`/`error` values.

Accepted evidence for this release:

- SIF build, `%test` and health for the current mdconvert tree.
- The scientific and CAVER-parser contracts in the hashed-dependency CI lane.
- Historical host-local evidence at head `02c1b6ad`: an isolated local
  API-to-Tool call with a 100 MB-class GRO/XTC pair and 51 frames, verified
  digests, read-only binds, deterministic output and bounded RSS. Its mdconvert
  SIF (`2643194a…`) is superseded. `requirements.lock` and the family definition
  are byte-identical to the current tree; its `tool_cli.py` differs only in the
  `_selection_expression` comma-grammar fix, which that run's `selection: all`
  path does not reach. An exact-head 100 MB-class, 51-frame run has not been
  executed.
- Host-local Tool-output → Task → CAVER handoff: the pinned CAVER SIF/JAR was
  executed against the server-produced Task snapshot and produced 23 tunnels in
  8 clusters with deterministic output hashes. This is host-local Apptainer
  evidence, not Slurm or production.

Slurm-managed deployment calls, production live-test receipts and production
promotion remain separate acceptance gates and are not claimed here.

Use `revocompute-tool-status --json` inside the Tool worker to inspect image identity, COLD/WARM/UNAVAILABLE state, active calls, last use, recent startup failure, cold starts, warm hits, and idle shutdowns. This output contains no user filenames, parameters, sequences, structures, or molecules.

For deployment, pause admission, allow active calls at most the configured five-minute bound, stop the old Tool worker and its generation-specific instances, deploy definitions and SIFs together, then restart web, maintenance, and workers COLD. Do not pre-warm families. Use a shortened idle TTL for acceptance and prove cold start, warm reuse, concurrent single-flight startup, workspace isolation, timeout recovery, idle stop, and cold restart before production enablement.
