# Runner Adaptation Wait List

This is the authoritative planning record for candidate and recently promoted
Runner families. A wait-list entry is not a support commitment.

## Status

REvoCompute keeps these states distinct:

- **Supported/enabled:** present in the production Runner inventory.
- **Academic-only:** implemented, but available only after target-host acceptance
  and an explicit family entitlement.
- **Rejected/deferred:** not pursued unless the recorded blocking condition
  materially changes and the operator reopens intake.

RFdiffusion2, Boltz, Chai-1, ESMFold 2, SimpleFold, EvoSplit, PPIformer, and
Pallatom are in the production Runner inventory. RFdiffusion2 and Foundry are
enabled but entitlement-gated. GeoDock is enabled behind an academic-only
entitlement. P2Rank, fpocket, MolProbity, FRODOCK, and DeepPocket are implemented
with their read-only resources provisioned and their target-host smoke cases
accepted; they await enablement. BoltzGen and Pallatom-Ligand were deferred at
intake with their blockers recorded. Mu-Protein and Protenix were abandoned by
operator decision and have no Runner implementation.

## Candidates

| Project | Status | Pinned source and assets | Remaining action |
|---|---|---|---|
| [EvoSplit](https://github.com/YaoYinYing/EvoSplit) | Supported/enabled | Apache-2.0 commit `6eedfcd5a0551bd1fecf9c51818be19f9e730e19`; ESM-MSA assets provisioned read-only | Monitor production evidence |
| [RFdiffusion2](https://github.com/YaoYinYing/RFdiffusion2) | Academic-only; enabled | BSD-3-Clause commit `d365cbf4db3958814a9f8e4f6f94fa309dfebc2b`; checkpoint `RFD_173.pt` provisioned read-only; target-host smoke cases passed (Slurm jobs 20193 and 20201) | Monitor production evidence under `rfdiffusion2_academic_only`; enabled in the deployment env |
| [Foundry](https://github.com/RosettaCommons/foundry) | Academic-only; image validated | BSD-3-Clause commit `b02eed6a6bdf8f44d14a80cc36e3da13c9f2291c`; hash-locked source closure; all three checkpoints provisioned with recorded `sha256` | Run all three entitled live cases, then enable under `foundry_academic_only` |
| [PPIformer](https://github.com/anton-bushuiev/PPIformer) | Supported/enabled | MIT commit `e324f5f30dd0dae55d194ac6b4d18c772219c3ee`; CC BY 4.0 Zenodo weights provisioned read-only | Monitor production evidence |
| [Mu-Protein](https://github.com/YaoYinYing/Mu-Protein) | Rejected/deferred | MIT commit `c228769f635e066d592838018b14463720956455`; pinned runtime does not load the official checkpoints and no unambiguous published score could be reproduced | No implementation remains |
| [Protenix](https://github.com/bytedance/Protenix) | Rejected/deferred | Apache-2.0 commit `2475421477ab414b571149ad4a875c390ff8a35d`; official v2 checkpoint is inaccessible and [upstream reports an internal review with no timeline](https://github.com/bytedance/Protenix/issues/296#issuecomment-4213192193) | Reconsider only if ByteDance publishes an accessible official checkpoint; unofficial mirrors remain excluded |
| [Pallatom](https://github.com/levinthal/Pallatom) | Supported/enabled; restricted | CC BY-NC-SA 4.0 commit `b27d70054dec6ce2f5ceadf8977de3d3baf00663`; checkpoint provisioned read-only | Restrict to `pallatom_noncommercial` entitlement |
| [GeoDock](https://github.com/Graylab/GeoDock) | Academic-only; enabled | MIT commit `df8d1f4c24ae2946655f27e7411ba2ffabf3d350`; checkpoint and ESM2 assets provisioned read-only; SIF `sha256:756ce3a95c6796f896a2f31b562ae6a3dd9f39fa85c6d2529e7ed501cc8b7b89` | Monitor production evidence under `geodock_academic_only` |
| [P2Rank](https://github.com/rdk/p2rank) | Implemented; smoke case accepted | MIT tag `2.5.1`, commit `9808a7723be9a94e2ffc21ab5f724cb6ae4ba01e`; default ligandability model and four score-transform JSONs provisioned read-only from the pinned release archive; `1SUO` smoke case passed (253 s) | Enable, then monitor production evidence |
| [fpocket](https://github.com/Discngine/fpocket) | Implemented; smoke case accepted | MIT tag `4.2.3`, commit `4bb0d8447f62fee77e2c3c29f54b5fcaf5e2c066`; no provisioned assets — detection is purely algorithmic, with bundled qhull and molfile notices recorded; `1SUO` smoke case passed (250 s) | Enable, then monitor production evidence |
| [MolProbity](https://github.com/phenix-project/cctbx_project) | Implemented; smoke case accepted | cctbx `v2026.8` commit `a978d97aad5efd33b594591fb1cfb0f7fa4f5b24` with runtime `cctbx-base==2025.11`; Top8000 rotarama grids, the generated rotarama cache, and the GeoStd restraint dictionary provisioned read-only; `1SUO` smoke case passed (204 s) | Enable, then monitor production evidence |
| [FRODOCK](https://chaconlab.org/modeling/frodock/frodock-donwload) | Implemented; smoke case accepted | BSD-3-Clause release archive `frodock3_linux64.tgz` v3.12, built from the shipped sources; `soap.bin` pairwise potential provisioned read-only; two-peptide smoke case passed (116 s) | Enable, then monitor production evidence |
| [DeepPocket](https://github.com/devalab/DeepPocket) | Implemented; smoke case accepted | MIT commit `04ba9f564a81dbf35c6afbb1db5fb9ca255cedc0`; one classifier and one segmentation checkpoint extracted read-only from the published archive. fpocket `4.2.3` is compiled in as DeepPocket's own candidate generator rather than chained as a separate Task; `1SUO` smoke case passed (598 s) | Enable, then monitor production evidence |
| [BoltzGen](https://github.com/HannesStark/boltzgen) | Deferred; intake blocked | MIT commit `a3149cf18eeb58648d1abbb27539bd73f746cdda` (2026-05-28), upstream HEAD; two design checkpoints plus inverse-folding, folding, affinity, and moldir artifacts fetched from the Hugging Face `boltzgen/*` namespaces (~6 GB) | No license, model-terms, or integration contract is published for the weights, and the license file covers only the MIT repository. Provision the artifacts, record their sizes and SHA-256, and settle the model terms before implementing |
| [Pallatom-Ligand](https://github.com/levinthal/Pallatom-Ligand) | Deferred; intake blocked | Commit `d5beea9b4a3c92972ee9cb8452b01982203cc9f1` (2026-03-19), upstream HEAD; no license file in the repository | The repository publishes no license at all and its checkpoints (`model.npz` 228.6 MB and `ref_feature.npz` 497 KB) are Google Drive links with unstated terms, so redistribution and hosted-service rights cannot be established. The provisioned `params_Pallatom.npz` belongs to the separately licensed `levinthal/Pallatom` family and does not satisfy these loaders |

Scientific similarity does not imply runtime compatibility. Dependency stacks,
accelerators, system ABI, model assets, and access terms are assessed per
family. Academic-only and other restricted runtimes use server-owned central
policies; policy files are not SIF build inputs.

## Future intake

A deferred candidate can be reopened only after the blocking condition changes.
A new or reopened candidate must cover its source and model revisions,
scientific contract, runtime and resource needs, external assets, access terms,
artifacts, tests, and family placement before implementation or enablement.
