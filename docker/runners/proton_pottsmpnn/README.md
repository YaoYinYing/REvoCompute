# Proton PottsMPNN

Pinned source: `christian-creator/ProtonPottsMPNN` at `09682abfa7d20e0abcdeea0490b7a4b1c190aee3`. Authored upstream code is MIT; nested `foundry` code is BSD-3-Clause and its notice must be verified before building a redistributable image. Objective values are model proxies, never measured pKa, affinity, or pH-selective binding.

## ASSET_BLOCKED

The expected checkpoint is `/mnt/db/weights/proton-pottsmpnn/checkpoints/potts_v6_afdb_edge_his0.3_acid0.06/epoch-0125.ckpt` (21,494,143 bytes per the pinned TODO). It is absent and no SHA256 is available yet. Provision the exact checkpoint read-only and record its SHA256 and provenance. The adapter validates the pinned code's complete 30-token v6 vocabulary and constructs `PottsMPNNPHEngine` with `extended_vocab="v6"`; the selected CPU path does not require a GPU for a small binder.

The scientific smoke test and readiness receipt are pending. This family is not READY.
