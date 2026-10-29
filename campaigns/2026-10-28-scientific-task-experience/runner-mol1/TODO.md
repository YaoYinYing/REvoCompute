# TODO — feat(runner): Mol-1 biomolecular complex prediction

**Implemented on this branch; R1 and R2 findings are closed at head `64e44bb`.**
The final SIF passed the `minimal-mol1` smoke case on an A100-PCIE-40GB
(5,189 MiB GPU peak). Larger-system and default-parameter fit, `doctor
--strict` on a GPU host, browser smoke, and independent scientific validation
remain open.

## Goal
Integrate Mol-1 full structure prediction with validated biomolecular JSON and explicit MSA/template/network handling, while preparing separately testable stages for future `mol msa` and `mol prep` support.

## Verified starting points
- Official repo https://github.com/molence/Mol-1 (Apache-2.0; derivative and third-party notices), published ~2.2GB checkpoint and reference data.
- Mol-1 has `mol pred`, `mol msa` and `mol prep` commands; default protein MSA route can contact the public ColabFold MMseqs2 service.
- Results include confidence scales where `plddt` uses 0–100 while `chain_plddt` uses 0–1, and PAE is token-indexed; user-facing interpretation needs care.

## Implementation checklist
- [x] Pin official upstream commit/release, weight and reference DB hashes, licenses, data/source provenance, supported accelerator/driver and Python/CUDA configuration.
- [x] Implement dedicated Runner Family with reproducible SIF, read-only weight/reference mounts, no implicit checkpoint/download during allocation and health/doctor checks.
- [x] Declare Task identity Mol-1; accept validated JSON jobs with proteinChain/dnaSequence/rnaSequence/ligand/ion inputs, modifications and optional covalent bonds.
- [x] Validate and confine any file references in user JSON including paired/unpaired MSAs and templates; canonicalize paths into immutable server snapshots; deny external local paths/URL references.
- [x] Provide the user an explicit `MSA search / supply MSA / no MSA` and `template search / supply templates / none` choice only where upstream supports it, clearly describing network disclosure.
- [x] Default public MSA service calls to off or operator-gated unless explicit network policy authorizes sequence upload; enforce at scheduler and runtime boundaries.
- [x] Select bounded seed, sample count, recycles, molecular tokens, optional detailed confidence output and resource estimates; handle A100 VRAM uncertainty and no blind size promise.
- [x] Translate input to official upstream `mol pred` CLI without unsafe shell string concatenation; preserve native JSON semantics and error causes.
- [x] Expose optional template search dependencies (HMMER/Kalign) only when enabled; reject unsupported RNA MSA DB combinations if missing.
- [x] Publish ranked mmCIF candidates, per-seed ranking/confidence/full_data (when requested), sequence/chain mapping, MSA/template provenance, metadata and Task ResultManifest.
- [x] Implement Result Storyboard for monomers, multi-chain and ligand systems, preserving 0–100 vs 0–1 metric scaling and token PAE axes.
- [x] Document future `mol msa` / `mol prep` stages as separate follow-up depending on #118/#119; do not claim stage reuse available in this PR.
- [x] Add demo inputs, operator documentation and bounded artifacts. No citation is shipped because the upstream README has not published one yet (recorded in MODEL_ASSETS.md).

## Tests and acceptance
- [x] Build exact pinned SIF and run official supported small case on real GPU; record VRAM, versions and outputs (Smoke `minimal-mol1`, Slurm 406763, A100-PCIE-40GB, 5,189 MiB GPU peak).
- [ ] Verify no unapproved network when MSA missing; respect operator network permissions and user privacy. (Refusal paths are tested and the smoke ran with `msa_mode: none`; no packet capture was made.)
- [x] Reject malformed component JSON, inconsistent covalent bonds, malicious paths, oversized molecular systems and missing files before GPU reservation.
- [x] Validate non-empty CIF, per-seed ranks, confidence scale and residue-vs-token mapping, provenance and replay (live output checks passed).
- [ ] Run Runner fast tests, `doctor --strict`, browser creation/result smoke, security and resource admission tests, full CI. (Fast, input-validation, boundary and audit gates pass; `doctor --strict` on a GPU host, browser smoke and full CI remain.)

## Explicit non-goals
- No fine-tuning, model training, GPU memory benchmark claims, or full antibody product expansion.
- No bypass of public-service network policy and no implicit MSA externalization.
- No support claim for selectable stages until the Stage Contract implementation actually merges.

## Dependencies
Full inference independent. Standalone MSA/prep execution depends on #118/#119; do not cross-implement.

## Campaign protocol and review
- [x] Read CLAUDE.md, LONG_TASK_HANDLING.md, Single-PR Campaign Protocol and this file before coding.
- [x] Assign one accountable subagent owner and maintain an independent active Campaign Adviser.
- [x] Create IMPLEMENTATION_STATE.md when implementation starts; keep exact-head progress and tests durable.
- [x] Preserve Runner ownership of scientific specifics and Core authority for authorization, resource admission, immutable artifacts and GPU accounting.
- [x] Publish detailed technical review evidence in this PR; report merge/no-merge and blockers to Commander.
- [x] Keep PR draft until exact-head acceptance/CI and maintainer approval; maintainer retains squash-merge authority.
