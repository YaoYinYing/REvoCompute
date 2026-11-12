# PR-3 — TODO

- [x] Wait for #152 to merge and verify shared viewer contract; inventory current CAVER picker tests and Runner schema. (#152 is stacked at `c1099eb5`; the typed scene contract is consumed without editing it.)
- [x] Audit pinned CAVER 3.0.2 include/exclude syntax, precedence and actual generated configuration (negative evidence counts). Verified in the pinned JAR and by an observed run; see DESIGN.md.
- [x] Extend shared picker UI for point/atom/residue/group/ligand; disambiguate centroid vs COM; require explicit atom mass policy.
- [x] Enforce topology digest/revision invalidation; derive dynamic residue-name choices only from source structure.
- [x] Use existing seed control and start_group rules; eliminate stale start_residue_number dependence.
- [x] Add only supported config keys; preserve pinned Runner output/provenance path.
- [x] Prove generated config and origins.pdb correspond to UI-selected identity across complex fixtures (unit/fixture evidence; no live run in this PR).
- [ ] Browser/keyboard/responsive screenshots and negative cases (Examiner); CHANGELOG.md [Unreleased] updated.
- [ ] Adviser CLEAR, Examiner PASS, new Auditor PASS at exact head; maintainer-only merge/deploy.