# Docking Runner Suite

The docking families are independent Runner plugins. AutoDock Vina performs CPU
Vina searches, AutoDock-GPU builds AutoGrid affinity maps before accelerated
AutoDock4 searches, Gnina performs GPU Vina-derived searches with selectable CNN
scoring, and DiffDock generates confidence-ranked diffusion poses.

All four families require prepared structure files and run offline inside direct
Apptainer images. Their `task.yaml` files are the sole source of parameter
defaults and scientific descriptions. Receptor/ligand preparation, protonation,
box placement, and validation remain explicit user responsibilities.

## Contracts

| Runner | Hardware | Inputs | Principal outputs |
| --- | --- | --- | --- |
| AutoDock Vina | CPU | receptor PDB/PDBQT, then 1-32 ligand SDF/MOL2/PDBQT files | native PDBQT/logs plus Vina `scores.csv` and `summary.json` |
| AutoDock-GPU | NVIDIA GPU | receptor PDB, then 1-64 ligand SDF/MOL2/PDBQT files | native AutoGrid/DLG files plus AutoDock4 `scores.csv` and `summary.json` |
| Gnina | NVIDIA GPU | receptor PDB and one ligand SDF/MOL2 | native SDF/log plus Gnina `scores.csv` and `summary.json` |
| DiffDock | NVIDIA GPU | protein PDB and one ligand SDF/MOL2 | native ranked SDFs plus confidence `scores.csv` and `summary.json` |

Vina, AutoDock-GPU, and Gnina expose explicit Cartesian search boxes. The ligand
being docked is never reused implicitly as Gnina's pocket definition. DiffDock
searches against the supplied protein structure and does not define a classical box. The Task forms bound
search effort, output count, sampling steps, and batch size so the resulting
Slurm allocation remains finite.

## Preparation boundary

PDBQT conversion uses Meeko inside the classical docking images, and
AutoDock-GPU runs AutoGrid inside its own image. These mechanical steps do not
replace scientific preparation. Submitters must choose protonation and tautomer
states, add chemically appropriate hydrogens, remove or retain cofactors and
waters deliberately, and verify the binding-site coordinates.

DiffDock is deliberately structure-only: its accepted inputs are one PDB protein
structure and one SDF/MOL2 ligand. The wrapper rejects FASTA, sequence fields,
and any implicit ESMFold, OpenFold, or other structure-prediction step. Its plain
ESM-2 dependency embeds residues read from the submitted PDB; it cannot generate
a protein structure. Submit a predicted structure from a separate REvoCompute
task when needed.

## Images and assets

The direct definitions pin AutoDock Vina 1.2.7, AutoDock-GPU 1.6, Gnina 1.3.2,
and DiffDock 1.1.3 by immutable release commit. Python environments are created
with pinned `uv`; Gnina uses the release's checksummed standalone binary. Vina
is CPU-only, AutoDock-GPU targets CUDA 12.2, Gnina uses its CUDA 12.8 binary in a
CUDA 12.8 cuDNN runtime, and DiffDock preserves its validated CUDA 11.7/PyTorch
1.13 stack in an isolated SIF.

DiffDock model files are operator-owned, read-only assets at
`/mnt/db/weights/revocompute/diffdock`. The official v1.1 score and confidence
checkpoints must match `model-assets.sha256`. The shared ESM2-650M checkpoint at
`/mnt/db/weights/esm` must independently match `esm-assets.sha256`. Build-time
downloads use the deployment controller's `--use-proxy` option; every image
clears proxy variables at runtime, and DiffDock additionally enables the
library offline modes.

## Licensing

The recorded upstream licenses are Apache-2.0 for AutoDock Vina,
GPL-2.0-or-LGPL-2.1 for AutoDock-GPU, GPL-2.0-or-Apache-2.0 for Gnina, and MIT
for DiffDock. Operators remain responsible for reviewing upstream licenses and
model terms before distribution. Exact repositories, commits, releases, binary
checksums, and the DiffDock model archive checksum live in each family's
`upstream.json`.

## Production evidence

Upstream commits, licenses, runtime bases, and release identities are recorded in
each family's `upstream.json`; required smoke cases live in that family's
`test.yaml`. A family is production-ready only after Doctor, direct SIF `%test`,
and target-host Slurm live-test evidence pass with resource observations recorded.
Use `run/restart.sh runner-status --runner <family> --json` to inspect the active
artifact and receipt identity. Receipts are invalidated when source, image,
contract, resource policy, scheduler identity, or required smoke coverage
changes; a successful historical job is not sufficient for activation.

For this delivery, AutoDock Vina is the only docking family eligible for
production enablement after its final CPU live acceptance. AutoDock-GPU, Gnina,
and DiffDock remain disabled and not ready until each exact image completes an
independent target-host GPU Slurm acceptance test; a successful SIF build does
not substitute for that receipt.
