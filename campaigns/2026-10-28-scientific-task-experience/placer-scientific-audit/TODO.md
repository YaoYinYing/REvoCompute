# TODO — fix(runner): audit PLACER scientific semantics and input mapping

> **Status:** planning-only draft; no implementation is claimed.
> **Initial main:** 17e80ed1dbd00f1389f3ec7047e5661b85ed52eb. Re-check exact main and PR head before any coding/review.

## Goal
Audit PLACER's task type, ligand/sidechain ensemble semantics, input mapping and missing upstream options; make bounded science-backed corrections with genuine upstream evidence.

## Grounded context
- Existing `docker/runners/placer-rfdiffusion/tasks/placer/task.yaml` describes protein-ligand complex ensemble modeling; output is structures and metrics tables.
- Existing shell adapter invokes `python3 .../run_PLACER.py`, accepts ligand, mutation, crop and corruption center parameters and emits a single generic stage marker.
- Original PLACER paper: Anishchenko et al., Modeling protein-small molecule conformational ensembles with PLACER, bioRxiv 2024.09.25.614868. It does not imply docking blind-search or experimentally measured binding affinity.
- The current input workspace has a primary structure selector while Runner uses an input directory; test whether the primary selection is semantically honored.

## Implementation checklist
- [ ] Read exact pinned upstream PLACER source, CLI flags, options, tests and preprint methods; distinguish claims from actual scientific data and model confidence.
- [ ] Determine canonical scientific task category: local protein-small-molecule conformational ensemble modeling/reconstruction, ligand coordinate refinement and possible sidechain remodeling; do not rebrand as global docking or binding free energy.
- [ ] Build an upstream feature-to-Task mapping for `predict_ligand`, `fixed_ligand`, `target_res`, `mutate`, `crop_centers`, `corruption_centers`, `fixed_ligand_noise`, `predict_multi`, `rerank` and expected behaviors.
- [ ] Investigate documented `--ligand_file` and `--residue_json` upstream options; add typed input roles and safe confinement only when needed, supported and verified.
- [ ] Verify whether a multi-file input directory is intended as batch input and whether the browser's selected primary structure controls computation or only visualization. Correct mapping or UI claims accordingly.
- [ ] Ensure structure builder and region selection preserve chain id, residue number, insertion code, ligand instance/residue name, modified residues and atom-level bonding semantics.
- [ ] Check the selected ligand representation, explicit vs inferred bond topology and hydrogens; reject ambiguous ligand identifiers before scheduling where possible.
- [ ] Audit metrics (`fape`, `lddt`, `rmsd`, `prmsd`, `plddt`, `plddt_pde`) against upstream definitions; preserve reference-dependent vs predicted-confidence distinctions and value direction in Storyboard.
- [ ] Update summary/use_when/input_summary/output_summary/considerations, guided form control labels and result help texts to reflect accurate model purpose.
- [ ] Keep Task id `placer`, Runner family, result schemas and stable APIs unless scientifically compelled by a documented migration; no unnecessary special-case Core changes.
- [ ] Preserve citations, license, input validation and immutable artifact publication; prefer focused adaptation rather than new parallel task.
- [ ] Produce a scientific contract audit table (upstream semantics, current behavior, action, test, evidence) in this PR and note deliberately unsupported upstream functionality.

## Acceptance / tests
- [ ] Run upstream official example or validated sample and confirm input intent matches actual invocation and output artifacts.
- [ ] Test selected primary structure vs multi-file behavior, residue/ligand selection specificity and nonstandard ligand handling.
- [ ] Upstream-option roundtrip from form to safe CLI argv with conflicting flags and malformed residue specification rejected.
- [ ] Reference vs model-predicted metrics displayed correctly; no score relabeling without evidence.
- [ ] Regression for Runner image, expected_files and storyboard result mapping; exact-head CI and independent scientific reviewer.

## Non-goals
- No fresh PLACER framework rewrite or model retraining.
- Do not expose options absent from pinned upstream or imply PLACER computes binding energies.
- No new global stage architecture within this scientific semantics PR.

## Dependencies
Independent. Coordinate with #117 naming cleanup, but scientific review remains canonical here.

## Campaign protocol
- [ ] Read CLAUDE.md, LONG_TASK_HANDLING.md and Single-PR Campaign Protocol, then this complete TODO, before editing.
- [ ] Commander appoints one PR owner. Independent Campaign Adviser checks science, architecture and merge-readiness without becoming worker.
- [ ] Maintain an IMPLEMENTATION_STATE.md when implementation begins, preserving milestone status, exact-head tests and blockers.
- [ ] Detailed findings, CI and scientific evidence belong in the PR thread; chat report is short merge/no-merge, blockers and owner.
- [ ] Before ready-for-review, prove scientific behavior in authentic execution, security boundaries, input/result contract and browser UX.
- [ ] Maintainer alone decides squash-merge; no agent merges automatically.
