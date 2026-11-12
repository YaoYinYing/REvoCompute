# REvoCompute Runtime Families

The current runtime families and the stacks they pin, used to match a new
task type to an existing runner before creating a new family. Versions are
what the pinned `docker/runners/<family>/<family>.def` installs — re-read the
file when matching; do not trust this table after a bump. GPU flags are the
registry's `gpus:` declarations.

| Family | Tasks | Base image / CUDA | Python | Frameworks | GPU |
| --- | --- | --- | --- | --- | --- |
| `gremlin` | gremlin | condaforge/mambaforge (legacy conda env) | 3.6 (legacy conda env) | GREMLIN conda env | no |
| `pythia_ddg` | pythia_ddg | python:3.12-slim | 3.12 | torch (CPU wheels), pytorch-lightning | no |
| `esm` | esm_msa, esm_extract, esm_1v, esm_if1 | nvidia/cuda:12.1.1-cudnn8 | 3.11 | torch 2.2.0+cu121, fair-esm | yes |
| `esmdynamic` | esmdynamic | nvidia/cuda:12.6.3-cudnn | 3.11 | torch 2.7.1+cu126, fair-esm, OpenFold | yes |
| `opendde` | opendde | python:3.11-slim | 3.11 | OpenDDE 1.2.0 source (`9d0d9c97`), torch 2.7.1, cuequivariance 0.10.0 | yes |
| `mpnn` | hypermpnn, proteinmpnn, solublempnn, ligandmpnn, lasermpnn, thermompnn | python:3.11-slim | 3.11 | torch 2.2.1 (CPU), ProteinMPNN-derived models | no |
| `dynamicmpnn` | dynamicmpnn | python:3.11-slim | 3.11 | torch 2.2.1 (CPU), ProteinMPNN-derived model | no |
| `frustrampnn` | frustrampnn | python:3.12-slim | 3.12 | current CPU torch, NumPy 1.24+, pandas 2+ | no |
| `fampnn` | fampnn_design, fampnn_pack, fampnn_score | nvidia/cuda:12.1.1-cudnn8 | 3.10 | torch 2.4.1+cu121, Hydra, Gemmi, RDKit | yes |
| `prime` | prime, prime_dms | python:3.10-slim | 3.10 | torch 2.3.1, transformers 4.36.2 | yes |
| `placer-rfdiffusion` | rfdiffusion, placer | nvidia/cuda:12.1.1-cudnn8 | 3.10 | torch 2.3.1, DGL 2.4.0, e3nn 0.5.4 (+ bool-override patch) | yes |
| `bioemu` | bioemu | python:3.11-slim | 3.11 | torch 2.7.1, jax[cuda12] 0.5.3, bioemu 1.4.1 | yes |
| `easifa` | easifa | debian:bookworm-slim (builder builds torchdrug CUDA ext) | 3.11 | torch + torchdrug CUDA extension | yes |
| `alphafold` | alphafold | python:3.11-slim | 3.11 | official AlphaFold2, jax 0.4.26 CUDA 12, dm-haiku 0.0.12, hh-suite + hmmer + kalign, OpenMM | yes |
| `alphafold3` | alphafold3 | nvidia/cuda:12.9.1-base-ubuntu24.04 | 3.12 | official AlphaFold 3 at `37e3c57fe123fc51f6d96236320b8b657afb11ac` (v3.0.5+), locked JAX 0.10.2 / CUDA 12.9 stack, patched HMMER 3.4, MessagePack CCD | yes |
| `colabfold_af2` | colabfold_af2 | python:3.12-slim-trixie | 3.12 | ColabFold 1.6.3 (commit `84c27d9c`), alphafold-colabfold 2.3.20, AlphaFold2, JAX CUDA 12, OpenMM 8.5.2; public MMseqs2 MSA service | yes |
| `freebindcraft` | freebindcraft | nvidia/cuda:12.9.1-base-ubuntu24.04 | 3.12 | FreeBindCraft 1.0.7 source (`8a10b93a`), jax[cuda12] 0.11.2, ColabDesign, OpenMM 8.6.1 CUDA, FASPR, sc-rs | yes |
| `bioemu2` | bioemu2 (BioEmu2; legacy equilibrium, structure-prediction and propagation descriptors retained for history) | nvidia/cuda:12.6.3-cudnn | 3.12 | BioEmu2 source `6d1ca744` (version 0.1.0rc0), torch 2.13.0+cu126, cuEquivariance 0.11.1 | yes |
| `esmfold2` | esmfold2_predict | nvidia/cuda:12.8.1-cudnn | 3.12 | ESM 3.4.2 source (`8f0834cb`), torch 2.11.0+cu128, Triton 3.6 fused/fast kernels | yes |
| `foundry` | foundry_rfd3_design, foundry_rfd3na_design, foundry_rf3_fold | nvidia/cuda:12.8.1-cudnn | 3.12 | Foundry source `d078b24d` (retained pin), AtomWorks 3, torch 2.11 | yes |

Sharing a family deduplicates SIF storage; it must not force CPU tasks
to inherit a large GPU stack or allow incompatible package upgrades. A new
family is justified only when dependencies, accelerator needs, system ABI, or
license make sharing unsafe — see the adapter guide's §11/§12.

If a family contains software, weights, databases, or resources that are not available to every REvoCompute user, attach
a declarative policy under `config/access_policies/`. Do not infer
a restriction from a Runner name or hardcode entitlement checks in Python or JavaScript.
