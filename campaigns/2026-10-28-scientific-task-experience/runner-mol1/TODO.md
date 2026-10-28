# TODO — feat(runner): Mol-1 biomolecular complex prediction

**Planning-only DRAFT. No implementation yet.**

## Goal
Integrate Mol-1 full structure prediction with validated biomolecular JSON and explicit MSA/template/network handling, while preparing separately testable stages for future `mol msa` and `mol prep` support.

## Verified starting points
- Official repo https://github.com/molence/Mol-1 (Apache-2.0; derivative and third-party notices), published ~2.2GB checkpoint and reference data.
- Mol-1 has `mol pred`, `mol msa` and `mol prep` commands; default protein MSA route can contact the public ColabFold MMseqs2 service.
- Results include confidence scales where `plddt` uses 0–100 while `chain_plddt` uses 0–1, and PAE is token-indexed; user-facing interpretation needs care.

## Implementation checklist
- [ ] Pin official upstream commit/release, weight and reference DB hashes, licenses, data/source provenance, supported accelerator/driver and Python/CUDA configuration.
- [ ] Implement dedicated Runner Family with reproducible SIF, read-only weight/reference mounts, no implicit checkpoint/download during allocation and health/doctor checks.
- [ ] Declare Task identity Mol-1; accept validated JSON jobs with proteinChain/dnaSequence/rnaSequence/ligand/ion inputs, modifications and optional covalent bonds.
- [ ] Validate and confine any file references in user JSON including paired/unpaired MSAs and templates; canonicalize paths into immutable server snapshots; deny external local paths/URL references.
- [ ] Provide the user an explicit `MSA search / supply MSA / no MSA` and `template search / supply templates / none` choice only where upstream supports it, clearly describing network disclosure.
- [ ] Default public MSA service calls to off or operator-gated unless explicit network policy authorizes sequence upload; enforce at scheduler and runtime boundaries.
- [ ] Select bounded seed, sample count, recycles, molecular tokens, optional detailed confidence output and resource estimates; handle A100 VRAM uncertainty and no blind size promise.
- [ ] Translate input to official upstream `mol pred` CLI without unsafe shell string concatenation; preserve native JSON semantics and error causes.
- [ ] Expose optional template search dependencies (HMMER/Kalign) only when enabled; reject unsupported RNA MSA DB combinations if missing.
- [ ] Publish ranked mmCIF candidates, per-seed ranking/confidence/full_data (when requested), sequence/chain mapping, MSA/template provenance, metadata and Task ResultManifest.
- [ ] Implement Result Storyboard for monomers, multi-chain and ligand systems, preserving 0–100 vs 0–1 metric scaling and token PAE axes.
- [ ] Document future `mol msa` / `mol prep` stages as separate follow-up depending on #118/#119; do not claim stage reuse available in this PR.
- [ ] Add demo inputs, citations, validation receipts, operator documentation and bounded artifacts.

## Tests and acceptance
- [ ] Build exact pinned SIF and run official supported example/small case on real GPU; record VRAM, scientific outputs and versions.
- [ ] Verify no unapproved network when MSA missing; respect operator network permissions and user privacy.
- [ ] Reject malformed component JSON, inconsistent covalent bonds, malicious paths, oversized molecular systems and missing files before GPU reservation.
- [ ] Validate non-empty CIF, per-seed ranks, confidence scale and residue-vs-token mapping, provenance and replay.
- [ ] Run Runner fast tests, doctor --strict, browser creation/result smoke, security and resource admission tests, full CI.

## Explicit non-goals
- No fine-tuning, model training, GPU memory benchmark claims, or full antibody product expansion.
- No bypass of public-service network policy and no implicit MSA externalization.
- No support claim for selectable stages until the Stage Contract implementation actually merges.

## Dependencies
Full inference independent. Standalone MSA/prep execution depends on #118/#119; do not cross-implement.

## Campaign protocol and review
- [ ] Read CLAUDE.md, LONG_TASK_HANDLING.md, Single-PR Campaign Protocol and this file before coding.
- [ ] Assign one accountable subagent owner and maintain an independent active Campaign Adviser.
- [ ] Create IMPLEMENTATION_STATE.md when implementation starts; keep exact-head progress and tests durable.
- [ ] Preserve Runner ownership of scientific specifics and Core authority for authorization, resource admission, immutable artifacts and GPU accounting.
- [ ] Publish detailed technical review evidence in this PR; report merge/no-merge and blockers to Commander.
- [ ] Keep PR draft until exact-head acceptance/CI and maintainer approval; maintainer retains squash-merge authority.
