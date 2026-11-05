# RFD4 Proteina

Pinned source: `RosettaCommons/RFD4-Proteina` at `68058693cb88762a8aaf806571e13b291ce6318a` (BSD-3-Clause). The bounded Task uses the pinned Hydra CLI (`rfd4-generate inputs=... out_dir=... num_replicates=... seed=... generation.args.nsteps=...`) with a native YAML/JSON condition specification plus scaffold, or a native annotated CIF. It publishes the upstream `inference_samples/*/*_generated.cif` designs and selects no inline metrics. Condition satisfaction is computational; it does not establish biochemical activity, binding, or function. The Task requires a GPU (`gpus: true`) because the pinned model runs on an accelerator.

## Model asset provenance (source identity verified; not downloaded)

The pinned code's default checkpoint source is the Hugging Face bundle `nvidia/RFD4-Proteina`, and the pinned `configs/inference.yaml` composes it at revision `a06e2509c7033b010fc43614e9fd840303588502` (public, not gated, licence `bsd-3-clause`). That release publishes per-file SHA-256 values in `release-checkpoints.json`, `provenance.json`, and per-file `.sha256` sidecars. The files the generation Task needs:

| Path | Size (bytes) | SHA-256 (published by upstream) |
| --- | --- | --- |
| `flow_checkpoints/rfd4_proteina_flow-ema.ckpt` | 1,751,488,703 | `c1c8b7068e87c41a334ec5b77e7d7cdda30bd31ed4504909d93bd72f7742afe4` |
| `ae_checkpoints/rfd4_proteina_ae-ema.ckpt` | 1,029,340,246 | `24536372f3fc9a5083b6b813baa80630d2287a5d61fbf2f126c9735802e1d21a` |
| `config.json` | 7,270 | `154ea927ab8005b7eac2d047a792147fb4606ab4878e496aa8414b6b40dad368` (bundle_config_sha256) |
| `inference.yaml` | — | verify at provisioning |
| `release-checkpoints.json` | — | verify at provisioning |

The flow model and autoencoder are matched and must be used together; this release changes latent dimension (16 to 32) and residue vocabulary (33 to 147 classes), so its components are not interchangeable with the previous release's. The bundle was not downloaded; the operator verifies these hashes against the bytes actually copied.

## Provisioning runbook (operator)

1. Create the read-only mount root `/mnt/db/weights/rfd4-proteina/` (directories 755, files 444).
2. Copy at minimum `flow_checkpoints/rfd4_proteina_flow-ema.ckpt`, `ae_checkpoints/rfd4_proteina_ae-ema.ckpt`, `config.json`, `inference.yaml`, and `release-checkpoints.json` from the pinned revision — no runtime download, no write by the service account.
3. Verify each file's SHA-256 against the published values above (and the `.sha256` sidecars for any additional copied file); record the verification with the deployment.
4. Fill `model-assets.sha256` with the verified per-file digests. The adapter fails closed while that manifest has no verified rows, even if the directory exists.
5. Keep the mount read-only.

## Native output evidence

The pinned release publishes an example generated design at `examples/enzyme_design/design.cif`. The fixture `tests/data/rfd4_proteina/upstream_enzyme_design_generated.cif` is that file, fetched from:

`https://huggingface.co/nvidia/RFD4-Proteina/resolve/a06e2509c7033b010fc43614e9fd840303588502/examples/enzyme_design/design.cif`

- SHA-256: `764ae8c83cf62df6da2f9b06848500c9b812269aae031165da817df435f488de`
- 1,071 `ATOM` records; 47-column `_atom_site` loop with `Cartn_x/y/z`
- Upstream release licence: `bsd-3-clause`

The family parser accepts it and the `inference_samples/*/*_generated.cif` pattern matches the native output name. This is upstream example output, not a run of this Runner; live generation still requires the provisioned weights, a built SIF, and a GPU.

## Activation status (source-only)

The family is discoverable from this tree, but it is not in the deployment's `ENABLED_TASKRUNNERS` list. With the family excluded, readiness resolves to `NOT_CONFIGURED` / `RUNNER_UNKNOWN`; with it enabled but no SIF or receipt, readiness resolves to `NOT_BUILT` / `SIF_MISSING` with `next_action=build-sif`. No readiness attestation exists, so submission admission reports `RUNNER_UNAVAILABLE`. No READY or admission claim is made. `docker/runners/rfd4_proteina/tests/fast/test_contract.py` exercises these paths.

## ASSET_BLOCKED

The mount is absent today, so the family is not READY. Remaining gates: operator provisioning and hash verification above, candidate SIF build, target-host GPU smoke (`hardware.accelerator=gpu`), live acceptance with resource observations, then activation by the maintainer. Runtime downloads are disabled.
