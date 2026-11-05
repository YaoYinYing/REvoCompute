# Proton PottsMPNN

Pinned source: `christian-creator/ProtonPottsMPNN` at `09682abfa7d20e0abcdeea0490b7a4b1c190aee3`. Authored upstream code is MIT; the bundled `foundry` tree is BSD-3-Clause and its notice must be verified before building a redistributable image. Objective values are model proxies, never measured pKa, affinity, or pH-selective binding. The selected CPU path does not require a GPU for a small binder.

The image installs the pinned `foundry` package plus the inference-relevant entries from the pinned `requirements-extra.txt` (`pandas>=2.1,<3`, `ipdb`, `propka>=3.5`), and `%test` imports the full runtime chain. The adapter validates the pinned code's complete 30-token v6 vocabulary and constructs `PottsMPNNPHEngine` with `extended_vocab="v6"`.

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

The pinned engine builds `chainA_all_idx` from the featurised token array, which follows the Biotite atom order supplied by `prepare_potts_input`; `_score_design` emits `canonical_sequence` and `extended_tokens` from that same index. Centres are matched by authored `res_id`. The adapter therefore supports ascending, possibly nonconsecutive binder numbering, and refuses insertion codes, duplicate numbering, and out-of-order authored numbering before design. The authored mapping is reused unchanged for output offset validation.

## Activation status (source-only)

The family is discoverable from this tree, but it is not in the deployment's `ENABLED_TASKRUNNERS` list. With the family excluded, readiness resolves to `NOT_CONFIGURED` / `RUNNER_UNKNOWN`; with it enabled but no SIF or receipt, readiness resolves to `NOT_BUILT` / `SIF_MISSING` with `next_action=build-sif`. No readiness attestation exists, so submission admission reports `RUNNER_UNAVAILABLE`. No READY or admission claim is made. `docker/runners/proton_pottsmpnn/tests/fast/test_contract.py` exercises these paths.

## ASSET_BLOCKED

The mount is absent today, so the family is not READY. A candidate SIF may be built and `%test`-checked without the checkpoint, but scientific execution and the live-test receipt require the provisioned, hash-verified checkpoint. Remaining gates: operator provisioning above, candidate SIF build and direct-API smoke, target-host live acceptance, then activation by the maintainer.
