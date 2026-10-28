# TODO — feat(runner): Proton-PottsMPNN pH-conditioned protein design

**Planning-only DRAFT. No implementation yet.**

## Goal
Implement pH-conditional binder redesign with protonation-aware model contracts and ranked Pareto/trajectory output; explicitly distinguish algorithmic pH selectivity predictions from measured affinity.

## Verified starting points
- Official repo https://github.com/christian-creator/ProtonPottsMPNN. MIT for authored components, bundled rc-foundry BSD-3-Clause; verify nested licenses and checkpoint distribution.
- Model uses v6 protonation-state sequence alphabet (30 tokens), `PottsMPNNPHEngine` and PHDesignCriteria; ordinary amino-acid FASTA is not a complete score representation.
- Labelling/scoring may need HBPLUS/FLAML but design inference alone does not; RF3 folding requires optional external weights.

## Implementation checklist
- [ ] Pin source revision, checkpoint SHA256, complete license provenance and optional dependencies; confirm available weights are redistributable.
- [ ] Implement isolated Runner Family with pinned environment, source, read-only checkpoint, predictable CPU/GPU footprint, bounded execution and no network access at run time.
- [ ] Define scientific Task `pH-conditioned binder redesign` with required complex/target structure, binder chain, locked/designable residues, titratable/protonation centers and pH-state contrast.
- [ ] Provide structure/region input workspace with chain and residue selectors, center state mappings, sequence identity checks and explicit scientific validation; preserve advanced text controls for precise selection.
- [ ] Validate HIS-P/HIS-S, ASP-P/ASP-D, GLU-P/GLU-D state grammar, center positions, input residue types, checkpoint vocab, mutation constraints and objective settings before allocating resources.
- [ ] Support bounded design-count sweep, lambda/stability/selectivity tradeoff, neighborhood size, temperature, seed and mutations; use predeclared options only, no arbitrary user Python.
- [ ] Call upstream PottsMPNNPHEngine safely and deterministically from immutable Task snapshot; avoid obligatory FLAML, HBPLUS and RF3 environments for first implementation.
- [ ] Preserve both canonical FASTA and protonation-annotated sequence, include state mapping and pinned centers in artifact provenance.
- [ ] Publish designs.fasta, designs_states.fasta, table/JSON of objective scores, Pareto front, optimisation trajectories and optional reference folding outputs when genuinely computed.
- [ ] Offer Result Storyboard showing predicted stability-versus-selectivity and center state labels with score direction and evidence warnings.
- [ ] Document upstream claims and validity limits; no assertion that computational pH-switching proves experimentally observed pH binding.
- [ ] Add access policy/credit behavior, expected_files, citations, documentation and batch-safe restraints.

## Tests and acceptance
- [ ] Run included design example with pinned published checkpoint and verify non-empty distinct candidates plus score/sequence alignment.
- [ ] Reject incompatible v6 checkpoint, invalid state names, nonexistent binder chain, mutationally locked residues, inconsistent atom-to-residue mapping and excessive batch counts.
- [ ] Verify correct provenance for protonation state and scoring; do not conflate labeler output with model-design state.
- [ ] Build SIF + doctor --strict, real scientific smoke if appropriate hardware exists, result/browser tests, error/cancel/admission and CI.

## Explicit non-goals
- No implied thermodynamic pKa/pH affinity calculation; labels are discrete states and scores are model proxies.
- No required upstream training or HBPLUS for core inference; do not bundle unreviewed third-party binaries.
- No dependency on RF3 for basic design or invented refolding results.

## Dependencies
Independent Runner PR; optional future Stage Contract support can be separate.

## Campaign protocol and review
- [ ] Read CLAUDE.md, LONG_TASK_HANDLING.md, Single-PR Campaign Protocol and this file before coding.
- [ ] Assign one accountable subagent owner and maintain an independent active Campaign Adviser.
- [ ] Create IMPLEMENTATION_STATE.md when implementation starts; keep exact-head progress and tests durable.
- [ ] Preserve Runner ownership of scientific specifics and Core authority for authorization, resource admission, immutable artifacts and GPU accounting.
- [ ] Publish detailed technical review evidence in this PR; report merge/no-merge and blockers to Commander.
- [ ] Keep PR draft until exact-head acceptance/CI and maintainer approval; maintainer retains squash-merge authority.
