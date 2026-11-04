# Implementation State — Molecular Selection

Status: M1 identity widening delivered; M2/M3 and CAVER picker remain. Base `6d726f54` + local commits.

## Completed

- Successor scope restored from #128 and #130's preserved requirements.
- A picked residue now carries auth chain, auth residue number, insertion code, residue name and the
  HETATM/ATOM hetero flag beside the viewer-local label identity
  (`MolecularViewer.authoredResidue`, `SelectedResidue`).
- `structureSelections` in the workspace contract carries that full identity; the built-in structure
  plugin forwards it to `selected_residues`.
- `.ent` is accepted by the viewer and parsed as PDB instead of losing the viewer.
- Tests: auth-vs-label identity, insertion-code publication and HETATM classification; frontend
  typecheck passes.

## Next action

- Wire the CAVER picker to the canonical `starting_point_*` controls, add the parameter write accessor and
  the pre-submission refusal rules, then browser acceptance.

## Blockers

- Browser acceptance needs the local example stack; CAVER scientific roundtrip needs an authorized runner
  receipt. `select_chains` remains a no-op alias and must be implemented or removed with its manifests.
