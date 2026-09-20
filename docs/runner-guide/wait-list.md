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

Boltz, Chai-1, ESMFold 2, SimpleFold, EvoSplit, PPIformer, Pallatom, and
RFdiffusion2 are supported in the production deployment. Foundry and GeoDock are
academic-only candidates with validated images and provisioned checkpoints.
Mu-Protein and Protenix were abandoned by operator decision and have no Runner
implementation.

## Candidates

| Project | Status | Pinned source and assets | Remaining action |
|---|---|---|---|
| [EvoSplit](https://github.com/YaoYinYing/EvoSplit) | Supported/enabled | Apache-2.0 commit `6eedfcd5a0551bd1fecf9c51818be19f9e730e19`; ESM-MSA assets provisioned read-only | Monitor production evidence |
| [RFdiffusion2](https://github.com/YaoYinYing/RFdiffusion2) | Academic-only; enabled | BSD-3-Clause commit `d365cbf4db3958814a9f8e4f6f94fa309dfebc2b`; checkpoint `RFD_173.pt` provisioned read-only; target-host smoke cases passed (Slurm jobs 20193 and 20201) | Monitor production evidence under `rfdiffusion2_academic_only` |
| [Foundry](https://github.com/RosettaCommons/foundry) | Academic-only; image validated | BSD-3-Clause commit `b02eed6a6bdf8f44d14a80cc36e3da13c9f2291c`; hash-locked source closure; all three checkpoints provisioned with recorded `sha256` | Run all three entitled live cases, then enable under `foundry_academic_only` |
| [PPIformer](https://github.com/anton-bushuiev/PPIformer) | Supported/enabled | MIT commit `e324f5f30dd0dae55d194ac6b4d18c772219c3ee`; CC BY 4.0 Zenodo weights provisioned read-only | Monitor production evidence |
| [Mu-Protein](https://github.com/YaoYinYing/Mu-Protein) | Rejected/deferred | MIT commit `c228769f635e066d592838018b14463720956455`; pinned runtime does not load the official checkpoints and no unambiguous published score could be reproduced | No implementation remains |
| [Protenix](https://github.com/bytedance/Protenix) | Rejected/deferred | Apache-2.0 commit `2475421477ab414b571149ad4a875c390ff8a35d`; official v2 checkpoint is inaccessible and [upstream reports an internal review with no timeline](https://github.com/bytedance/Protenix/issues/296#issuecomment-4213192193) | Reconsider only if ByteDance publishes an accessible official checkpoint; unofficial mirrors remain excluded |
| [Pallatom](https://github.com/levinthal/Pallatom) | Supported/enabled; restricted | CC BY-NC-SA 4.0 commit `b27d70054dec6ce2f5ceadf8977de3d3baf00663`; checkpoint provisioned read-only | Restrict to `pallatom_noncommercial` entitlement |
| [GeoDock](https://github.com/Graylab/GeoDock) | Academic-only; image validated | MIT commit `df8d1f4c24ae2946655f27e7411ba2ffabf3d350`; checkpoint and ESM2 assets provisioned read-only; SIF `sha256:756ce3a95c6796f896a2f31b562ae6a3dd9f39fa85c6d2529e7ed501cc8b7b89` | Run entitled live acceptance, then enable under `geodock_academic_only` |

Scientific similarity does not imply runtime compatibility. Dependency stacks,
accelerators, system ABI, model assets, and access terms are assessed per
family. Academic-only and other restricted runtimes use server-owned central
policies; policy files are not SIF build inputs.

## Future intake

A deferred candidate can be reopened only after the blocking condition changes.
A new or reopened candidate must cover its source and model revisions,
scientific contract, runtime and resource needs, external assets, access terms,
artifacts, tests, and family placement before implementation or enablement.
