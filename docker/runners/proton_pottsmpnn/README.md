# Proton PottsMPNN

Pinned source: `christian-creator/ProtonPottsMPNN` at `09682abfa7d20e0abcdeea0490b7a4b1c190aee3`. Authored upstream code is MIT; the bundled `foundry` tree is BSD-3-Clause and its notice must be verified before building a redistributable image. Objective values are model proxies, never measured pKa, affinity, or pH-selective binding. The selected CPU path does not require a GPU for a small binder.

The image installs the pinned `foundry` package plus the pinned runtime entries from
`requirements-extra.txt`. The v6 path is not import-only: every `PottsMPNNPHEngine.run_ph_redesign` call
featurises through `prepare_potts_input(..., extended_vocab="v6")`, which unconditionally runs
`CalculateHbondsPlus` and the EV6 FLAML labeller. HBPLUS is **not** bundled: the operator provisions the
executable under HBPLUS's own licence terms and exports `HBPLUS_PATH` in the runner environment. The adapter
fails closed before design if `HBPLUS_PATH` is unset, relative, missing, or not executable; it never falls
back to a bundled or default path. The image pins the labeller stack (`flaml`, `xgboost`, `lightgbm`,
`scikit-learn`). `%test` imports the design engine and loads the EV6 fold models, and asserts that no
PATH-resolvable HBPLUS binary and no known HBPLUS notice directory are present. The adapter validates the
pinned code's complete 30-token, three-letter v6 `token_atoms` vocabulary and constructs `PottsMPNNPHEngine`
with `extended_vocab="v6"`.

Licence: authored upstream code is MIT; the bundled `foundry` tree is BSD-3-Clause. Both notices ship in
`/opt/ProtonPottsMPNN`, and the image label declares only those shipped licences (`MIT AND BSD-3-Clause`).
HBPLUS (Copyright I K McDonald, D T Jones, D Naylor and J M Thornton) is not redistributed in any form and
is not covered by that label; the operator supplies it under its own academic-use terms. The 21 MB design
checkpoint and Git history are removed after installation; the EV6 labeller fold models that ship with
`foundry` remain in site-packages because the v6 featurisation path requires them.

## Access posture

The plugin declares `runtime.access_policy: proton_pottsmpnn_academic_only` in
`common/policy/proton_pottsmpnn_academic_only.yaml`. The policy requires operator approval, records that
HBPLUS is operator-provisioned rather than distributed, and enforces that only entitled users may use the
family. The family is usable only after the operator enables it and all three activation gates below are
satisfied.

## Model asset provenance

The pinned upstream tree ships the design checkpoint in-repo:

- Repository path: `checkpoints/potts_v6_afdb_edge_his0.3_acid0.06/epoch-0125.ckpt`
- Pinned Git revision: `09682abfa7d20e0abcdeea0490b7a4b1c190aee3`
- Git blob SHA: `13bf9a44d9b1843980edc11cd486a7ecc1d57df5` (a Git blob SHA is not a SHA-256)
- Size: 21,494,143 bytes
- SHA-256 (computed from the exact pinned blob; temporary copy deleted):
  `a39872250c0b8eb4c0b4cb6472a6edad0d6f6134a50c28b611386e83c592fe7b`
- Licence: MIT (authored code); nested `foundry` BSD-3-Clause

These values are recorded in `model-assets.sha256`.

## Provisioning runbook (operator)

1. Create the read-only mount root `/mnt/db/weights/proton-pottsmpnn/` (directories 755, files 444).
2. Copy `checkpoints/potts_v6_afdb_edge_his0.3_acid0.06/epoch-0125.ckpt` from the pinned revision into that root — no runtime download, no write by the service account.
3. Verify size is exactly 21,494,143 bytes and `sha256sum` matches the value above; record the verification with the deployment.
4. Keep the mount read-only. The adapter verifies the hash from `model-assets.sha256` and fails closed on absence or mismatch.
5. Provision an HBPLUS executable outside the image, under the operator's own HBPLUS licence terms. Do not bake it into the SIF. The checked-in `runner.yaml` binds `/mnt/db/tools/hbplus` read-only and sets `HBPLUS_PATH=/mnt/db/tools/hbplus/hbplus`; adjust those machine-specific values for the deployment. The adapter requires an absolute path, refuses to start if `HBPLUS_PATH` is unset, relative, missing, or not executable, and never falls back. It checks executability, not binary identity or version; the live-test receipt is the compatibility gate. The host directory must be operator/root-owned and must not be writable by the service or task users.

## Binder residue indexing

The pinned engine builds `chainA_all_idx` from the featurised token array, which follows the Biotite atom order supplied by `prepare_potts_input`; `_score_design` emits `canonical_sequence` and `extended_tokens` from that same index. Centres are matched by authored `res_id` through `_PHContext.res_id_to_pos`, which maps each token's `res_id` to its context position. The adapter therefore supports ascending, possibly nonconsecutive, zero, or negative binder numbering, and refuses insertion codes, duplicate numbering, and out-of-order authored numbering before design. Because Biotite preserves PDB atom order and the parser refuses any reordering it cannot map, the adapter's ascending authored order is the same binder order the engine featurises. The authored mapping is reused unchanged for output offset validation, which fails closed on a binder-length mismatch, on any canonical residue that disagrees with its protonation token's parent, or on a pinned centre that does not occupy the expected offset.

## Smoke fixture

`tests/data/proton_pottsmpnn/complex.pdb` is the pinned upstream `inference/examples/pdl1_seed_binder.pdb`
(MIT, revision `09682abf`): a two-chain PD-L1/binder complex, not a synthetic single chain. The smoke case
uses chain B as the binder and the ASP B9 protonation centre, so the fixture exercises real target/binder
chain identity and a real titratable residue.

## Activation status (source-only)

The family is discoverable from this tree, but enrollment is deployment configuration: an empty `ENABLED_TASKRUNNERS` enables every discovered family, so whether this instance omits it is an operator/Maintainer check, not a source guarantee. Excluded, readiness resolves to `NOT_CONFIGURED` / `RUNNER_UNKNOWN`; enabled but without a SIF or receipt, it resolves to `NOT_BUILT` / `SIF_MISSING` with `next_action=build-sif`. No readiness attestation exists, so submission admission reports `RUNNER_UNAVAILABLE` even when discovered. No READY or admission claim is made. `docker/runners/proton_pottsmpnn/tests/fast/test_contract.py` exercises these paths.

## Activation gates

Three gates stand between this source-only family and activation. They are independent: satisfying one neither
implies nor satisfies another, and each fails closed on its own.

1. **Checkpoint.** Provision the 21,494,143-byte
   `checkpoints/potts_v6_afdb_edge_his0.3_acid0.06/epoch-0125.ckpt` under `/mnt/db/weights/proton-pottsmpnn`
   with its reviewed SHA-256 recorded in `model-assets.sha256`. `verify_checkpoint()` raises `ASSET_BLOCKED`
   when the manifest is malformed, or the file is missing, the wrong size, or does not match the recorded
   digest.
2. **HBPLUS.** Provision the HBPLUS executable under its own terms and set an absolute `HBPLUS_PATH`; the
   image never bundles or redistributes it. `verify_hbplus()` raises `ASSET_BLOCKED` when the variable is
   unset, relative, missing, or not executable. Provisioning HBPLUS does not satisfy gate 1, and a verified
   checkpoint does not satisfy this gate.
3. **Live receipt.** Produce a real live-inference receipt on the target Slurm/Apptainer host; only then may
   the SIF be promoted and the family activated. The candidate live test must confirm the real engine's
   `to_metadata()['extended_tokens']` contract (the adapter assumes a space-joined string; a list fails
   closed). A green build or `%test` satisfies neither asset gate, and neither asset gate establishes a live
   receipt.

A candidate SIF may be built and `%test`-checked without gates 1 and 2; that is not activation. None of the
gates is satisfied in this change, so the family is not READY and is not admissible. `%test` verifies the
engine imports and EV6 fold models and asserts no PATH-resolvable HBPLUS binary or known notice directory;
because it binds upstream-private fold attributes and the `./foundry` install path, it is a fail-closed,
upstream-version-sensitive build gate rather than a scientific check. HBPLUS verification is
executability-only by design.
