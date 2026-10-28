# TODO — feat(runner): RFD4-Proteina biomolecular design

**Planning PR; not implemented or merge-ready.**

## Goal
Integrate a scientifically validated initial RFD4-Proteina generation Task for motif/enzyme scaffolding and conditioned design, keeping reward-guided searches and optional oracles out of the first PR.

## Initial evidence
- Official source: https://github.com/RosettaCommons/RFD4-Proteina. BSD-3-Clause; RFD4 `rfd4-generate` CLI, YAML/annotated-CIF input; public weights on Hugging Face.
- Upstream supports CUDA 12/13, Python 3.12, native/BioIR backends and an optional AF-based scoring/search stack.
- Upstream capability breadth is not justification to create one Task Type per recipe.

## Work checklist
- [ ] Audit upstream source, pinned release/commit, container prerequisites, checkpoint/revision/digest, third-party notices, supported CUDA/driver A100 profile and data residency.
- [ ] Implement a separate Runner Family/Apptainer definition with immutable versioned source and read-only mounted weights; no task-time downloads or implicit token exposure.
- [ ] Choose one first supported research Task (conditioned backbone/sequence generation with motif/scaffold inputs) with a stable Task ID and concise label.
- [ ] Define safe typed input roles: conditioned YAML/JSON spec and optional input structure; validate structural selections, motifs, contigs, residue/chain mapping, desired length, chemistry and limits.
- [ ] Provide a guided form with structure viewer and target/motif selections when meaningful, with advanced source-spec editing and preview; never silently overwrite upstream scientific constraints.
- [ ] Translate accepted configuration to upstream CLI without shell interpolation or arbitrary Hydra/user code; explicitly reject unsupported directives.
- [ ] Declare resource policy/accelerator requirements and bounded replicates/diffusion steps/output sizes; fail closed for absent kernels, insufficient VRAM, missing weight or incompatible driver.
- [ ] Publish candidate structures/sequences, condition-satisfaction scores, per-sample metrics, seed, parameter snapshot, upstream/model provenance and normalized artifact collection.
- [ ] Distinguish computational validity from demonstrated biochemical activity; document reward-guided search and external oracle limitations as follow-up.
- [ ] Include citations, licensing, input validation receipts, expected_files contract, result Storyboard and operator setup instructions.

## Acceptance and regression
- [ ] Build Apptainer/SIF, doctor --strict, deterministic official-example smoke on authentic GPU; retain screenshot and scientific output receipts.
- [ ] Check version/digest/weight pin, no unapproved network, invalid YAML/contig/path/selector, input size and missing dependency errors.
- [ ] Verify generated structures with real format parser, chain/motif mapping, result manifest completeness and correct confidence/metric semantics.
- [ ] Run server security/contract tests, browser input/result testing and no regression to other Runner Families.

## Explicit non-goals
- No upstream training, arbitrary RL/search orchestration, biological success guarantees or automatic antibody workflows.
- No hidden network/downloads or Core changes specific to RFD4.

## Dependencies
Independent single-stage Runner; optional scoring/search may later reuse Stage Contract after #118/#119.

## Agent protocol
- [ ] Read current CLAUDE.md, LONG_TASK_HANDLING.md and Single-PR Campaign Protocol before implementation.
- [ ] Assign one owner and maintain an independently active Campaign Adviser. Maintainer retains final squash-merge authority.
- [ ] Keep IMPLEMENTATION_STATE.md current once implementation starts; evidence and exact head in PR thread are canonical.
- [ ] Add regression evidence, docs, scientific rationale and fail-path tests; perform independent exact-head merge-level review.
- [ ] Remain draft until all requirements are met; do not merge on a planning-only commit.
