# PR-3 — TODO

- [ ] Wait for #152 to merge and verify shared viewer contract; inventory current CAVER picker tests and Runner schema.
- [ ] Audit pinned CAVER 3.0.2 include/exclude syntax, precedence and actual generated configuration (negative evidence counts).
- [ ] Extend shared picker UI for point/atom/residue/group/ligand; disambiguate centroid vs COM; require explicit atom mass policy.
- [ ] Enforce topology digest/revision invalidation; derive dynamic residue-name choices only from source structure.
- [ ] Use existing seed control and start_group rules; eliminate stale start_residue_number dependence.
- [ ] Add only supported config keys; preserve pinned Runner output/provenance path.
- [ ] Prove generated config and origins.pdb correspond to UI-selected identity across complex fixtures.
- [ ] Browser/keyboard/responsive screenshots and negative cases; CHANGELOG.md [Unreleased].
- [ ] Adviser CLEAR, Examiner PASS, new Auditor PASS at exact head; maintainer-only merge/deploy.