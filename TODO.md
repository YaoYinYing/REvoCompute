# RFD4-Proteina Runner — Campaign TODO

> Successor to closed planning PR #122; requirements preserved in
> [#130's preserved-requirements record](https://github.com/YaoYinYing/REvoCompute/pull/130#issuecomment-6490641559).
> Base: `main` `6d726f54`. **Draft implementation. NO MERGE.** Remove this file before final review.

## Objective

One bounded, scientifically meaningful RFD4-Proteina Task: conditioned backbone/sequence generation with
motif/scaffold inputs. Reward-guided search, oracles, partial diffusion and antibody workflows are out of
the first delivery.

## Verified upstream evidence (2026-11-04)

| Fact | Evidence |
| --- | --- |
| Source | `RosettaCommons/RFD4-Proteina` default HEAD `68058693cb88762a8aaf806571e13b291ce6318a` |
| License | BSD-3-Clause (Institute for Protein Design, UW) |
| Runtime | Linux x86_64, Python 3.12, NVIDIA GPU; CUDA 13-compatible driver preferred, CUDA 12 and CPU containers available |
| Weights | `nvidia/RFD4-Proteina` on Hugging Face, ~1.7 GB bundle including autoencoder; cache follows `HF_HOME` |
| CLI/API | `rfd4-generate`, `rfd4-evaluate`, Python API; YAML or annotated-CIF conditioning |
| Install | `make setup` (or pinned wheel `rfd4-proteina`); optional BioIR backend and metrics extras |

Re-verify the immutable commit, checkpoint file hashes and licence text inside the built SIF before claiming
the upgrade.

## M0 — asset and contract closure

- [ ] Provision the model bundle under `/mnt/db/weights/rfd4-proteina/` (read-only) with per-file SHA256,
      licence text and provenance; no runtime download and no implicit token use.
- [ ] Define one Task with typed named roles: a conditioned YAML/JSON specification and an optional input
      structure. Validate motif/contig/chain/residue mapping, lengths, chemistry and size bounds.
- [ ] Translate only declared fields to the upstream API; reject unsupported directives, shell
      interpolation and arbitrary user code.
- [ ] Declare accelerator/resource policy and bounded replicates/steps/output size; fail closed on missing
      weights, VRAM or driver mismatch.

## M1 — family implementation

- [ ] Add `docker/runners/rfd4_proteina/` with `plugin.yaml`, direct `.def` pinned to the immutable source
      commit, `run.sh`/adapter, `runner.yaml`, asset validation, `test.yaml` and family README.
- [ ] Publish native generated structures/sequences, condition-satisfaction metrics, seed, parameter
      snapshot and upstream/checkpoint provenance.
- [ ] Keep computational validity distinct from demonstrated biochemical activity in the result contract.
- [ ] Add expected-files/Storyboard only where they describe real outputs.

## M2 — acceptance

- [ ] Family fast tests for command construction, input refusal and output normalization.
- [ ] Real candidate-SIF `rfd4-generate` smoke on the target GPU with a minimal official-example input;
      record walltime, CPU/RSS, GPU memory/utilization and output digests.
- [ ] Negative cases: invalid YAML/contig/selector, missing weights, oversized input, unsupported mode.
- [ ] Exact-head CI, independent science/security review, Adviser, Campaign Acceptance Auditor PASS.

## Non-goals

No upstream training, RL/search orchestration, biological success claim, hidden network access, or
RFD4-specific Core branch.

## ASSET_BLOCKED

`/mnt/db/weights/rfd4-proteina/` is absent. The pinned TODO evidence describes a roughly 1.7 GB Hugging Face bundle including the autoencoder, but individual required paths and SHA256 values have not been verified. No files were provisioned or downloaded. Next: inspect the pinned revision's loader, acquire the licensed bundle through operator provisioning, record every file hash and provenance, then run target-host acceptance.
