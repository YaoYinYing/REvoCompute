# Proton-PottsMPNN Runner — Campaign TODO

> Successor to closed planning PR #123; requirements preserved in
> [#130's preserved-requirements record](https://github.com/YaoYinYing/REvoCompute/pull/130#issuecomment-6490641559).
> Base: `main` `6d726f54`. **Draft implementation. NO MERGE.** Remove this file before final review.

## Objective

One bounded pH-conditioned binder-design Task using the pinned 30-state (v6) protonation vocabulary, with
explicit score semantics and reproducible design artifacts. Optional HBPLUS, FLAML and RF3 workflows stay
out of the core inference path.

## Verified upstream evidence (2026-11-04)

| Fact | Evidence |
| --- | --- |
| Source | `christian-creator/ProtonPottsMPNN` default HEAD `09682abfa7d20e0abcdeea0490b7a4b1c190aee3` |
| License | MIT for authored code; bundled `foundry` is BSD-3-Clause (verify nested notices) |
| Checkpoint | `checkpoints/potts_v6_afdb_edge_his0.3_acid0.06/epoch-0125.ckpt`, 21,494,143 bytes, in-repo |
| Runtime | Python 3.12; design inference needs `mpnn`/torch only — **not** HBPLUS or FLAML |
| Vocabulary | 30-token v6: `HIS-P`/`HIS-S`, `ASP-P`/`ASP-D`, `GLU-P`/`GLU-D` |
| Entrypoint | `PottsMPNNPHEngine`, `PHDesignCriteria`, `run_ph_redesign` (`inference/design_ph.py` example) |

HBPLUS is required only by the labeller and fold scoring; RF3 folding needs separate external weights.
Design inference runs on CPU for the example but the Task must declare its real resource envelope.

## M0 — provenance and safe contract

- [ ] Pin the checkpoint SHA256 and full licence provenance; provision read-only under
      `/mnt/db/weights/proton-pottsmpnn/`; no runtime download.
- [ ] Define one Task: target/binder complex, binder chain, designable/locked residues, protonated centres,
      pH-state contrast and bounded optimiser settings (lambda, block size, temperature, neighbour count,
      mutation cap, seed).
- [ ] Validate `HIS-P`/`HIS-S`, `ASP-P`/`ASP-D`, `GLU-P`/`GLU-D` grammar, centre positions, input residue
      types, checkpoint vocabulary, binder chain and mutation locks before allocation.
- [ ] Reject arbitrary user code; expose only declared optimiser options.

## M1 — family implementation

- [ ] Add `docker/runners/proton_pottsmpnn/` with `plugin.yaml`, pinned `.def`, adapter, `runner.yaml`,
      asset validation, `test.yaml` and README.
- [ ] Publish canonical and protonation-annotated sequences, design table/JSON with objective terms,
      Pareto front, optimisation trajectories and centre mappings, plus seed/checkpoint provenance.
- [ ] Keep prediction scores distinct from measured affinity, pKa or demonstrated pH-selective binding in
      user-facing text and result metadata.
- [ ] Storyboard, if added, shows stability-vs-selectivity and centre state labels with score direction.

## M2 — acceptance

- [ ] Fast tests: invalid state names, wrong checkpoint vocab, missing binder chain, locked-residue
      mutation, inconsistent residue mapping, oversized batch.
- [ ] Real candidate-SIF run of the included design example; assert non-empty distinct candidates and
      score/sequence alignment; record resource observations and output digests.
- [ ] Exact-head CI, independent science/security review, Adviser, Campaign Acceptance Auditor PASS.

## Non-goals

No thermodynamic pKa/affinity claim, no mandatory FLAML/HBPLUS/RF3, no unreviewed bundled binaries, no
upstream training.

## ASSET_BLOCKED

`/mnt/db/weights/proton-pottsmpnn/checkpoints/potts_v6_afdb_edge_his0.3_acid0.06/epoch-0125.ckpt` is absent. The pinned TODO evidence records 21,494,143 bytes, but its SHA256 and the checkpoint's complete 30-token vocabulary are not available in this worktree. No weights were provisioned or downloaded. The adapter also requires a verified vocabulary metadata file at `/mnt/db/weights/proton-pottsmpnn/vocab.json`; confirm that path against the pinned code before provisioning. Next: obtain the exact checkpoint via operator provisioning, record its SHA256 and provenance, verify the full vocabulary against the pinned code, then run target-host acceptance.
