# Proton PottsMPNN

Pinned source: `christian-creator/ProtonPottsMPNN` at `09682abfa7d20e0abcdeea0490b7a4b1c190aee3`. Authored upstream code is MIT; the bundled `foundry` tree is BSD-3-Clause and its notice must be verified before building a redistributable image. Objective values are model proxies, never measured pKa, affinity, or pH-selective binding. The selected CPU path does not require a GPU for a small binder.

The image installs the pinned `foundry` package plus the pinned runtime entries from
`requirements-extra.txt`. The v6 path is not import-only: every `PottsMPNNPHEngine.run_ph_redesign` call
featurises through `prepare_potts_input(..., extended_vocab="v6")`, which unconditionally runs
`CalculateHbondsPlus` and the EV6 FLAML labeller. The image therefore builds HBPLUS 3.06 from the pinned
`RomanLas/HBPLUS` commit, exports `HBPLUS_PATH`, and pins the labeller stack (`flaml`, `xgboost`,
`lightgbm`, `scikit-learn`). `%test` executes `prepare_potts_input` on the pinned upstream example PDB and
runs `EV6Predictor.predict()`, so a missing HBPLUS binary or unpicklable fold model fails the build instead
of the first design. The adapter validates the pinned code's complete 30-token, three-letter v6
`token_atoms` vocabulary and constructs `PottsMPNNPHEngine` with `extended_vocab="v6"`.

Licence: authored upstream code is MIT; the bundled `foundry` tree is BSD-3-Clause. Both notices ship in
`/opt/ProtonPottsMPNN`, and the image label declares `MIT AND BSD-3-Clause`. HBPLUS is a separate program
(Copyright I K McDonald, D T Jones, D Naylor and J M Thornton; free to academic users under its own terms,
not an OSI licence); its source notice is retained at `/usr/local/share/doc/hbplus/`. The design checkpoint
and Git history are removed after installation, so no model weights are baked into the image.

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

## Binder residue indexing

The pinned engine builds `chainA_all_idx` from the featurised token array, which follows the Biotite atom order supplied by `prepare_potts_input`; `_score_design` emits `canonical_sequence` and `extended_tokens` from that same index. Centres are matched by authored `res_id`. The adapter therefore supports ascending, possibly nonconsecutive, zero, or negative binder numbering, and refuses insertion codes, duplicate numbering, and out-of-order authored numbering before design. The authored mapping is reused unchanged for output offset validation, which checks that every canonical residue matches its protonation token's parent.

## Smoke fixture

`tests/data/proton_pottsmpnn/complex.pdb` is the pinned upstream `inference/examples/pdl1_seed_binder.pdb`
(MIT, revision `09682abf`): a two-chain PD-L1/binder complex, not a synthetic single chain. The smoke case
uses chain B as the binder and the ASP B9 protonation centre, so the fixture exercises real target/binder
chain identity and a real titratable residue.

## Activation status (source-only)

The family is discoverable from this tree, but it is not in the deployment's `ENABLED_TASKRUNNERS` list. With the family excluded, readiness resolves to `NOT_CONFIGURED` / `RUNNER_UNKNOWN`; with it enabled but no SIF or receipt, readiness resolves to `NOT_BUILT` / `SIF_MISSING` with `next_action=build-sif`. No readiness attestation exists, so submission admission reports `RUNNER_UNAVAILABLE`. No READY or admission claim is made. `docker/runners/proton_pottsmpnn/tests/fast/test_contract.py` exercises these paths.

## ASSET_BLOCKED

The mount is absent today, so the family is not READY. A candidate SIF may be built and `%test`-checked without the checkpoint; `%test` already exercises the v6 featurisation and EV6 fold ensembles at build time. No SIF build or model-backed design run has been executed in this change, so scientific execution and the live-test receipt require the provisioned, hash-verified checkpoint. Remaining gates: operator provisioning above, candidate SIF build and direct-API smoke, target-host live acceptance, then activation by the maintainer.
