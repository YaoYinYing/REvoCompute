# GeoDock model assets

Provision these three files directly from their official sources beneath
`/mnt/db/weights/revocompute/geodock`. The directory is mounted read-only at
the identical container path. Runtime network access is disabled.

| Relative path | Bytes | SHA-256 | Official source |
| --- | ---: | --- | --- |
| `dips_0.3.ckpt` | 51,771,953 | `4a323ebaba152285a2444dcbf68de2dba7ec77f7d61a6d8b693c75169900d162` | GeoDock revision `df8d1f4c24ae2946655f27e7411ba2ffabf3d350`, `geodock/weights/dips_0.3.ckpt` |
| `esm2_t33_650M_UR50D.pt` | 2,604,537,549 | `ea9d0522b335a8778dea6535a65301f10208dece28cd5865482b0b1fc446168c` | `https://dl.fbaipublicfiles.com/fair-esm/models/esm2_t33_650M_UR50D.pt` |
| `esm2_t33_650M_UR50D-contact-regression.pt` | 3,687 | `8ffe6edbd4173dc8d45c2cd5cb27d43aad77ec26b4c768200c58ae1f96693575` | `https://dl.fbaipublicfiles.com/fair-esm/regression/esm2_t33_650M_UR50D-contact-regression.pt` |

The official projects do not publish SHA-256 manifests for these files. The
digests above are independently computed from the pinned Git blob and official
Meta downloads. `fair-esm` requires the contact-regression file to be adjacent
to the ESM checkpoint even though GeoDock only consumes final-layer embeddings.
The build verifies and removes the checkpoint bundled in the Git checkout, so
the final SIF cannot silently fall back to an embedded model copy.

## Refinement decision

OpenMM refinement belongs in this runtime as an optional postprocessing stage:
the pinned GeoDock `geodock/utils/docking.py` calls
`geodock/refine/openmm_ref.py` directly on its predicted PDB, and the upstream
environment pins conda-only OpenMM 7.7.0. The direct runtime uses the earliest
official PyPI release available for Python 3.10, OpenMM 8.1.1; the API used by
GeoDock is unchanged. That implementation uses PDBFixer, Amber14
`protein.ff14SB.xml`, and positional restraints on N/CA/C/CB. The adapter selects
CPU because no official CUDA 11 pip plugin accompanies this release; using the
model GPU for an unverified OpenMM plugin would violate the matched-ABI contract.
Keeping it in one image preserves the upstream operation and avoids passing an
intermediate structure between incompatible runtimes.

The upstream notebook nevertheless sets `do_refine=False` and states that
refinement is not yet supported there. For that reason refinement is disabled
by default, described as experimental, applied to a copy, and never overwrites
`geodock_raw.pdb`. PyRosetta refinement is intentionally excluded because it is
not freely installable under the same reproducible runtime contract.

## Smoke-case provenance

The pinned upstream notebook defines the runnable interface as two uploaded PDB
partners, one deterministic output name, and `do_refine=False`. Its referenced
`data/test` partner files are absent from the pinned repository. The living smoke
case therefore preserves that exact two-file/no-refinement path with two tiny,
synthetic three-residue PDB fixtures. It is a runtime-contract check, not a
scientific accuracy benchmark; production validation still needs a real
unbound-complex pair through SLURM and the public API.
