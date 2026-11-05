# Proton PottsMPNN

Pinned source: `christian-creator/ProtonPottsMPNN` at `09682abfa7d20e0abcdeea0490b7a4b1c190aee3`. Authored upstream code is MIT; nested `foundry` code is BSD-3-Clause and its notice must be verified before building a redistributable image. Objective values are model proxies, never measured pKa, affinity, or pH-selective binding.

## ASSET_BLOCKED

The expected checkpoint is `/mnt/db/weights/proton-pottsmpnn/checkpoints/potts_v6_afdb_edge_his0.3_acid0.06/epoch-0125.ckpt` (21,494,143 bytes per the pinned TODO). It is absent and no SHA256 is available yet. Provision the exact checkpoint read-only and provide `/mnt/db/weights/proton-pottsmpnn/vocab.json` as verified checkpoint vocabulary metadata with its provenance; the adapter fails closed until both the checkpoint hash and 30-token vocabulary are verified. The adapter requires the HIS-P/HIS-S, ASP-P/ASP-D, and GLU-P/GLU-D entries; it does not claim the remaining special token names before they are verified.

The scientific smoke test and readiness receipt are pending. This family is not READY.
