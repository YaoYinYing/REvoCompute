# PSSM-GREMLIN Runner

CPU-only REvoCompute family that turns one protein sequence into sequence-search
evidence: a PSI-BLAST position-specific scoring matrix (PSSM) and a
GREMLIN/EVcouplings co-evolutionary model fitted to the homologous alignment
found by HHblits.

Scientific semantics are owned by the upstream GREMLIN release that
`scripts/GREMLIN_TFv1.py` transcribes; the platform owns the Runner contract,
not the method. The owning `tasks/gremlin/task.yaml` is the sole authoritative
source of user-facing parameter vocabulary, defaults, and help, projected
through the server API. This page does not restate those values.

## Workflow stages

```text
query FASTA
     ↘ hhblits            search UniRef30, emit an A3M alignment
     ↘ hhfilter           redundancy filter at 90% id / 75% coverage
     ↘ remove insertions  strip lowercase insertion columns
     ↘ gremlin            fit fields + pairwise couplings
     ↘ blast (PSI-BLAST)  search UniRef90, emit a PSSM checkpoint and ASCII matrix
```

`run.sh` emits `REVODESIGN_STAGE:{hhblits,hhfilter,gremlin,blast}` around the
stages and writes `log/task_finished` only after both searches complete.

## Result artifact tree

`expected_files.yaml` is the authoritative declaration. `run.sh` writes a single
per-task output directory:

```text
log/                                     stage logs and the completion marker
gremlin_msa/
  <instance>.a3m                         raw HHblits alignment
  <instance>.i90c75.a3m                  HHfilter output
  <instance>.i90c75_aln.fas              insertion-stripped alignment
gremlin_res/
  <instance>.i90c75_aln.GREMLIN.mrf.pkl  fitted GREMLIN model
pssm_msa/
  <instance>.ckp                         PSI-BLAST checkpoint
  <instance>_ascii_mtx_file              ASCII PSSM
  <instance>_output_file                 PSI-BLAST text output
```

## What lives where

The Runner needs two large reference databases that are **not** shipped in the
image. They are deployment-owned, mounted read-only, and shared by every task of
this family. Keeping that boundary explicit matters:

| Layer | Contents | Owner |
| --- | --- | --- |
| Container image (`gremlin.def`) | Conda environment (HH-suite, BLAST+, Python scientific stack), `run.sh`, `scripts/` | this Runner |
| Deployment mounts | UniRef30 and UniRef90 reference databases | the operator, read-only |
| Task-local files | `gremlin_msa/`, `gremlin_res/`, `pssm_msa/`, `log/` under the task output directory | one task run, discarded or archived with the result |

Databases are never copied into the image, the task workspace, or the result
tree. The Runner performs no downloads at run time: if the mounted databases are
missing or malformed it fails closed.

## Required databases

| Database | Used by | What the Runner expects |
| --- | --- | --- |
| UniRef90 | `psiblast` (PSSM stage) | A BLAST+ protein database whose prefix is `uniref90`, i.e. `uniref90.fasta` plus its `makeblastdb` index files (`.phr`, `.pin`, `.psq`, …) |
| UniRef30 | `hhblits` (MSA stage) | A UniClust HH-suite database whose prefix is `UniRef30_2022_02`, i.e. `_a3m.ffdata`/`_a3m.ffindex` and `_cs219.ffdata`/`_cs219.ffindex` |

Upstream projects:

- UniRef90 and UniRef30 are distributed by UniProt and the UniClust project.
  - UniRef90: <https://ftp.ebi.ac.uk/pub/databases/uniprot/uniref/uniref90/>
  - UniClust archive: <https://wwwuser.gwdg.de/~compbiol/uniclust/>
- HH-suite (`hhblits`, `hhfilter`) and BLAST+ (`makeblastdb`, `psiblast`) are
  already installed inside the image; only the data is operator-provisioned.

## Prepare the databases

Run the following on the deployment host, not inside a container. `aria2c` and
`makeblastdb` are host prerequisites of a server that enables this Runner; the
commands below mirror the production layout used by the checked-in
`runner.yaml`.

### 1. UniRef90 (PSI-BLAST)

```bash
DOWNLOAD_DIR=/mnt/db
ROOT_DIR="${DOWNLOAD_DIR}/uniref90"
SOURCE_URL="https://ftp.ebi.ac.uk/pub/databases/uniprot/uniref/uniref90/uniref90.fasta.gz"

mkdir -p "${ROOT_DIR}"
aria2c "${SOURCE_URL}" --dir="${ROOT_DIR}"
gunzip "${ROOT_DIR}/$(basename "${SOURCE_URL}")"

cd "${ROOT_DIR}"
makeblastdb -in uniref90.fasta -dbtype prot -parse_seqids -out uniref90
```

The prefix `.../uniref90` is what the Runner passes to `psiblast -db`. The
`makeblastdb` step is the expensive part and only needs to run once per release.

### 2. UniRef30 (HH-suite)

```bash
DOWNLOAD_DIR=/mnt/db
VERSION=2022_02
ROOT_DIR="${DOWNLOAD_DIR}/uniref30_uc30/UniRef30_${VERSION}"
SOURCE_URL="https://wwwuser.gwdg.de/~compbiol/uniclust/${VERSION}/UniRef30_${VERSION}_hhsuite.tar.gz"

mkdir -p "${ROOT_DIR}"
aria2c "${SOURCE_URL}" --dir="${ROOT_DIR}"
tar -xf "${ROOT_DIR}/$(basename "${SOURCE_URL}")" -C "${ROOT_DIR}"
rm -f "${ROOT_DIR}/$(basename "${SOURCE_URL}")"
```

The HH-suite archive is already indexed; extraction is the only preparation
step. The Runner's `hhblits -d` prefix is the `<dir>/UniRef30_<version>` path
under the mount, for example `/opt/db/uniref30/UniRef30_2022_02`.

> The pinned `runner.yaml` example uses UniRef30 `2022_02`. A different UniClust
> release is fine, but the mount and the `uniref30_db` prefix in `runner.yaml`
> must be updated together so the documented prefix matches the files on disk.

### Expected final directory layout

The checked-in mount contract in `runner.yaml` is authoritative:

```yaml
mounts:
  - host_path: "/mnt/db/uniref30_uc30/UniRef30_2022_02"
    container_path: "/opt/db/uniref30"
    mode: "ro"
  - host_path: "/mnt/db/uniref90"
    container_path: "/opt/db/uniref90"
    mode: "ro"
env:
  uniref30_db: "/opt/db/uniref30/UniRef30_2022_02"
  uniref90_db: "/opt/db/uniref90/uniref90"
```

Which resolves, inside the container, to:

```text
/opt/db/uniref30/                              <- host /mnt/db/uniref30_uc30/UniRef30_2022_02
  UniRef30_2022_02_a3m.ffdata
  UniRef30_2022_02_a3m.ffindex
  UniRef30_2022_02_cs219.ffdata
  UniRef30_2022_02_cs219.ffindex
/opt/db/uniref90/                              <- host /mnt/db/uniref90
  uniref90.fasta
  uniref90.phr
  uniref90.pin
  uniref90.psq
  ...
```

If you keep the databases on another host path, edit `host_path` in the deployed
`runner.yaml` and leave the container paths and `uniref30_db`/`uniref90_db`
prefixes unchanged.

## Configuration and mount points

| Setting | Owner | Meaning |
| --- | --- | --- |
| `host_path` | deployed `runner.yaml` | Where the database lives on the host |
| `container_path` | deployed `runner.yaml` | Read-only mount target inside the task container |
| `uniref30_db` | deployed `runner.yaml` (`env`) | Prefix passed to `hhblits -d` |
| `uniref90_db` | deployed `runner.yaml` (`env`) | Prefix passed to `psiblast -db` |
| `MAXMEM` | deployment env file | Global HHblits memory cap in GiB (`MAXMEM=64` in `.env.example`) |

`runner.yaml` is family-owned and machine-local; it contains no user-facing
parameter defaults. Parameter vocabulary lives only in `tasks/gremlin/task.yaml`.

## Validate the databases

HH-suite is installed only inside the runner image, so validate the databases
through that image with the same read-only mounts the family uses. This
exercises the real mount contract instead of host tooling that the Runner may
not share.

Set `SIF` to the active `gremlin_v1.sif` built from `gremlin.def`, and `QUERY`
to an absolute path for a FASTA you intend to submit. The bind targets must stay
`/opt/db/uniref90` and `/opt/db/uniref30` so the database prefixes match
`runner.yaml`; substitute your deployed host paths for the sources. Every bind
is `:ro`, matching the read-only mounts `runner.yaml` declares.

```bash
SIF=/path/to/gremlin_v1.sif
QUERY=/absolute/path/to/query.fasta

apptainer exec \
  --bind /mnt/db/uniref90:/opt/db/uniref90:ro \
  --bind /mnt/db/uniref30_uc30/UniRef30_2022_02:/opt/db/uniref30:ro \
  --bind "${QUERY}":/query.fasta:ro \
  "${SIF}" /bin/bash -c '
    set -euo pipefail
    bin=/opt/conda/envs/GREMLIN/bin
    # UniRef90: BLAST+ index present, readable, and searchable.
    "$bin/blastdbcmd" -db /opt/db/uniref90/uniref90 -info
    "$bin/psiblast" -query /query.fasta -db /opt/db/uniref90/uniref90 \
      -num_iterations 1 -out /tmp/pssm.check
    # UniRef30: HH-suite index present and searchable.
    ls /opt/db/uniref30/UniRef30_2022_02_a3m.ffdata
    "$bin/hhblits" -i /query.fasta -d /opt/db/uniref30/UniRef30_2022_02 \
      -oa3m /tmp/msa.check.a3m -n 1
  '
```

Each command must exit `0` and print a result. The image's `%environment`
already puts the Conda environment on `PATH`, so bare `blastdbcmd`, `psiblast`,
and `hhblits` resolve inside the image as well.

The Runner itself also fail-closes on a missing database: `run.sh` exits with
`<prefix>.fasta not found, exit.` when the UniRef90 FASTA and index are absent,
and `hhblits`/`psiblast` report their own errors for an unreadable UniRef30.

## Runtime and resource envelope

- CPU-only; no GPU requirement and no accelerator accounting.
- Databases are mounted read-only; the Runner never writes to them.
- Run the family under the deployment's non-root runner identity
  (`RUNNER_UID`/`RUNNER_GID` or `RUNNER_USERNAME`/`RUNNER_GROUP`); the mounted
  databases must be readable by that identity.
- `runner.yaml` sets `max_runtime_seconds: 7200`. Per-task SLURM CPU, memory,
  and time are resolved from the server-side resource policy, not this file.
- The SIF is built directly with Apptainer from `gremlin.def`; the Conda
  environment is pinned in `GREMLIN.yml`.

## Testing this family

```bash
# Runner-owned unit logic and the tiny mock databases in tests/data/msa.
python -m pytest tests/runners/gremlin -q

# Generic family contract (Doctor) against this family.
python -m revocompute doctor --config-root docker/runners --runner gremlin --strict
```

Real end-to-end acceptance (`run/restart.sh live-test --runner gremlin`) needs
the mounted UniRef databases; see the platform
[Adding a Runner](../../../docs/runner-guide/adding-a-runner.md) guide.
