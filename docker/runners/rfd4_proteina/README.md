# RFD4 Proteina

Pinned source: `RosettaCommons/RFD4-Proteina` at `68058693cb88762a8aaf806571e13b291ce6318a` (BSD-3-Clause). The bounded Task uses the pinned Hydra CLI (`rfd4-generate inputs=... out_dir=... num_replicates=... seed=... generation.args.nsteps=...`) with a YAML/JSON condition specification plus its required CIF scaffold, or with an annotated CIF and no scaffold. It publishes the upstream `inference_samples/*/*_generated.cif` designs, requires the exact expected number of non-empty designs, and selects no inline metrics. Condition satisfaction is computational; it does not establish biochemical activity, binding, or function. The Task requires a GPU (`gpus: true`) because the pinned model runs on an accelerator.

## Input contract

A YAML/JSON specification is a mapping of named designs. Each design accepts the native `contig`, `conditions`, `input`, and `input_as_annotated_cif` fields; top-level `global_args` supplies defaults that a design may override. `contig` and `conditions` are optional and use the upstream token grammar, including unnamed expandable segments such as `10R`. Condition aliases are `C_CRD`, `C_SEQ`, `C_HOT`, `C_RAS`, `C_HB`, `C_PISTACK`, `C_PICATION`, `C_CATH`, `C_CENTROID`, `C_IDX`, `C_CRDGRP`, and `C_SEQ_PROB_<TOKEN>`. Full annotation names and two-body conditions are not accepted.

The `scaffold` input is conditionally required: supply exactly one CIF with a YAML/JSON specification, and omit it for an annotated CIF. The adapter rejects the wrong combination before dispatch to the upstream program.

`num_designs` is upstream `num_replicates`: it is the number of candidates per named design (or per annotated CIF). A specification with N named designs therefore produces N x `num_designs` candidate CIFs, and a run that produces any other count of valid designs fails. This Task deliberately changes two upstream defaults: 200 diffusion steps instead of 60, and seed 0 instead of a random seed.

## Model asset provenance (source identity verified; not downloaded)

The pinned code loads the Hugging Face bundle `nvidia/RFD4-Proteina` at revision `a06e2509c7033b010fc43614e9fd840303588502` through `hf_ckpt_path=/mnt/db/weights/rfd4-proteina` (public, not gated, licence `bsd-3-clause`). The pinned `Proteina.from_pretrained`/`load_pretrained_bundle` requires **both** files below in that directory; no other file is opened:

| Path | Size (bytes) | SHA-256 |
| --- | --- | --- |
| `config.json` | 7,270 | `154ea927ab8005b7eac2d047a792147fb4606ab4878e496aa8414b6b40dad368` |
| `model.safetensors` | 1,742,660,596 | `5b549dd61adb2f6c6b5cb95bda13f40f5e31556b4e6c755edc0ca6f011c68fb0` |

`5b549dd61adb2f6c6b5cb95bda13f40f5e31556b4e6c755edc0ca6f011c68fb0` is the `weights_sha256` recorded inside `config.json`. The adapter verifies both digests from `model-assets.sha256` and cross-checks that `config.json`'s `weights_sha256` equals the `model.safetensors` digest. The model weights were not downloaded; `config.json`'s digest was verified against the pinned release file, and the operator verifies both against the bytes actually copied.

### Native checkpoint path (`hf_ckpt_path=null`, not used by this Task)

The same release also publishes the native `.ckpt` pair below. This Task never opens it: the adapter always passes `hf_ckpt_path`, so `ckpt_path`, `ckpt_name`, `autoencoder_ckpt_path`, and `DATA_PATH` are unused. The values are recorded only as provenance for a future native-checkpoint mode, not as the identity of this Runner's assets.

| Path | Size (bytes) | SHA-256 |
| --- | --- | --- |
| `flow_checkpoints/rfd4_proteina_flow-ema.ckpt` | 1,751,488,703 | `c1c8b7068e87c41a334ec5b77e7d7cdda30bd31ed4504909d93bd72f7742afe4` |
| `ae_checkpoints/rfd4_proteina_ae-ema.ckpt` | 1,029,340,246 | `24536372f3fc9a5083b6b813baa80630d2287a5d61fbf2f126c9735802e1d21a` |

## Provisioning runbook (operator)

1. Create the read-only mount root `/mnt/db/weights/rfd4-proteina/` (directories 755, files 444).
2. Copy `config.json` and `model.safetensors` from the pinned revision — no runtime download, no write by the service account.
3. Verify both SHA-256 values above against the bytes actually copied.
4. `model-assets.sha256` already records the published digests. It ships in the Runtime Bundle overlay, not in the SIF; changing it after activation has no effect until a new Runtime Bundle is prepared and activated.
5. Keep the mount read-only.

## Native output evidence

The pinned release publishes an example generated design at `examples/enzyme_design/design.cif`. The fixture `tests/data/rfd4_proteina/upstream_enzyme_design_generated.cif` is that file, fetched from:

`https://huggingface.co/nvidia/RFD4-Proteina/resolve/a06e2509c7033b010fc43614e9fd840303588502/examples/enzyme_design/design.cif`

- SHA-256: `764ae8c83cf62df6da2f9b06848500c9b812269aae031165da817df435f488de`
- 61-column `_atom_site` loop with `Cartn_x/y/z`; 1,083 atom rows (1,071 `ATOM`, 12 `HETATM`)
- Upstream release licence: `bsd-3-clause`

The family parser accepts it and the `inference_samples/*/*_generated.cif` pattern matches the native output name. This is upstream example output, not a run of this Runner; live generation still requires the provisioned weights, a built SIF, and a GPU. The declared smoke specification uses the upstream token grammar and its preserved ranges fit the scaffold (a fast fixture-consistency test enforces this).

## Environment (CUDA 12 profile)

The pinned upstream selects its CUDA profile explicitly: `cu13 -> --extra all-cuda13 --torch-backend cu130`, `cu12 -> --extra all-cuda12 --torch-backend cu126`. This image uses the CUDA 12 profile so the base and compiled wheels share one CUDA minor: `nvidia/cuda:12.6.3-cudnn-runtime-ubuntu24.04` pinned by digest, with `requirements.lock` generated from `requirements.in` for `torch 2.14.1+cu126`, the fused `cuequivariance-ops-*-cu12` kernels, `tmol-ops-cu12`, and `atomworks 3.0.4`. The lock deliberately contains no `rfd4-proteina` distribution: the build installs the lock with `--require-hashes`, then installs the pinned upstream wheel from commit `68058693cb88762a8aaf806571e13b291ce6318a` with `--no-build-isolation --no-deps`, and runs `uv pip check`. `%test` imports the real chain (`torch`, `atomworks`, `rfproteina`, `cuequivariance_torch`, TMol's compiled LJ/LK operator, and OpenBabel) and asserts `torch.version.cuda == "12.6"` and the pinned torch version.

No SIF build was authorized for this branch, so the image, `%test`, lock installation, and upstream inference have not been executed. They remain the host gate.

## Activation status (source-only)

The family is discoverable from this tree, but it is not part of this deployment. `ENABLED_TASKRUNNERS` is an operator obligation: when it is empty, every discovered family is enabled. To keep this family unavailable, the deployment must set a non-empty list that omits `rfd4_proteina` (or must not discover this source tree). With the family excluded, readiness resolves to `NOT_CONFIGURED` / `RUNNER_UNKNOWN`; with it enabled but no SIF or receipt, readiness resolves to `NOT_BUILT` / `SIF_MISSING` with `next_action=build-sif`. No readiness attestation exists, so submission admission reports `RUNNER_UNAVAILABLE`. No READY or admission claim is made. `docker/runners/rfd4_proteina/tests/fast/test_contract.py` exercises these paths.

## ASSET_BLOCKED

The mount is absent today, so the family is not READY. Remaining gates: operator provisioning and hash verification above, candidate SIF build, target-host GPU smoke (`hardware.accelerator=gpu`), live acceptance with resource observations, then activation by the maintainer. Runtime downloads are disabled.
