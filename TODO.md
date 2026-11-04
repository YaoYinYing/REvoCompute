# Molecular Selection and Scientific Input Interaction — Campaign TODO

> Successor to closed design PR #128; design record preserved on that branch at
> `docs/developer-guide/molecular-selection-capabilities.md` and in
> [#130's preserved-requirements record](https://github.com/YaoYinYing/REvoCompute/pull/130#issuecomment-6490641559).
> Base: `main` `6d726f54`. **Draft implementation. NO MERGE.** Remove this file before final review.

## Objective

Make molecular selection reusable Input Workspace infrastructure: a pick expresses authored molecular
identity, resolves to the owning Task's canonical parameters, survives submission immutably, and reaches
the Runner with provenance. Use CAVER (#125) as the first end-to-end scientific acceptance target.

**Invariant:** viewer limitations never constrain a Runner's scientific contract. Preserve native
CIF/mmCIF/PDB; fix viewer format coverage rather than converting on the Runner side.

## Grounded facts (verified on this base)

- `frontend/src/features/structure/MolecularViewer.ts` already returns `auth_seq_id`, `label_seq_id` and
  `insertion_code` per picked residue and offers `select`/`focus`; the viewer facade must stay that narrow.
- `frontend/src/features/create-task/input-workspace/InputWorkspace.ts` still carries
  `structureSelections` as `{chain, residue}` — auth/insertion/hetero/atom identity is lost at the
  submission boundary.
- `revocompute/workspace_contracts.py` invokes trusted runner-owned normalizers/validators; it is the
  correct place to widen the generic contract without Core scientific branching.
- CAVER (#125) declares required canonical `starting_point_*` parameters and resolves selector modes in
  the Runner; the UI must drive those controls, not own their values.
- Submission validates parameters before capability normalization merges (`revocompute/routes.py`), so a
  picker cannot inject a required parameter in a normalizer.

## M1 — selection identity at the submission boundary

- [ ] Widen the workspace selection payload to carry auth chain, auth residue number, insertion code,
      residue name, hetero flag, and atom name/altloc/serial for atom mode; keep label identity only as
      viewer-local data, never as Runner meaning.
- [ ] Normalize and validate through the owning capability; refuse mixed structures/frames, empty or
      ambiguous selectors, missing residues, unsupported altlocs, blank-chain mismatches, multi-model
      inputs, and out-of-range atoms.
- [ ] Preserve the raw selection as provenance beside the canonical parameters; the Runner reads
      parameters, not the workspace payload.
- [ ] Add `.ent` to viewer preview coverage and prove an accepted `.ent` keeps the viewer.

## M2 — viewer facade and canonical-parameter path

- [ ] Keep the facade to `select`, `focus`, `annotate`; no caller reaches viewer internals.
- [ ] Pair the existing parameter read with a write accessor so a pick drives the canonical control and an
      edit re-places the marker. Parameter vocabulary comes only from the projected `task.yaml` schema.
- [ ] Manual XYZ is authoritative only where the Runner does not resolve the point; elsewhere it is a
      labelled preview of the Runner's answer, and a difference is not a submission error.
- [ ] Do not build an inverse "include list": render the Runner's typed exclude parameters.

## M3 — CAVER picker and end-to-end acceptance

- [ ] Implement residue, multi-residue centroid, and ligand picks with a visible origin marker and editable
      Å coordinates, selected by CAVER's declared capability (not a generic framework).
- [ ] Preserve the Runner's centroid rule; the UI must not define its own centroid or origin.
- [ ] Browser evidence: immutable source identity -> canonical `starting_point_*` / selector parameters ->
      Runner config -> real CAVER output, both themes and keyboard operation.
- [ ] Atom mode is a separate P0-b increment; do not claim it in the first delivery.

## Acceptance

- [ ] Mutation-sensitive tests for each refusal rule and for auth-vs-label identity.
- [ ] Backend tests prove the submitted parameters, not just the stored provenance payload.
- [ ] Exact-head CI, independent Adviser, Campaign Acceptance Auditor PASS. CAVER live acceptance remains
      a Runner gate and is not inherited from #125.

## Non-goals

No second molecular viewer, no generic scientific-parameter authority, no Runner-specific selection
semantics duplicated in Core, no Runner-side format conversion for viewer convenience.
