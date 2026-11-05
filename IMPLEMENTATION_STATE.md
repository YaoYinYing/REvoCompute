# Implementation State — Molecular Selection

Status: residue/ligand/group CAVER picker delivered on authored identity. Base `6d726f54` plus this
branch. Draft / NO MERGE.

## Completed

- A picked residue carries auth chain, auth residue number, insertion code, residue name and the
  HETATM/ATOM hetero flag beside the viewer-local label identity
  (`MolecularViewer.authoredResidue`, `SelectedResidue`).
- `structureSelections` in the workspace contract carries that authored identity; the built-in structure
  plugin forwards it to `selected_residues`, and the CAVER picker maps residue, single-ligand and
  multi-residue group picks to the canonical `start_point_*` controls declared by the owning `task.yaml`.
- Editing a canonical start-point control re-places the viewer selection or manual point marker. Manual
  XYZ is authoritative only in `point` mode.
- Picks CAVER cannot address are refused before submission: empty, insertion-coded, chainless, mixed
  hetero and multi-chain selections write no partial parameters and block submission.
- The submission boundary validates authored selection shape and duplicate identity generically; empty
  selections ("no pick") and multichain provenance are accepted. The one-chain, hetero and
  insertion-code rules remain CAVER picker semantics.
- `.ent` is accepted by the viewer and parsed as PDB.
- Browser evidence on the shipped Mol* bundle covers a real residue pick, canonical parameter writes,
  reverse re-placement, the refused insertion-coded pick, and the submitted selection/parameters.

## Deferred

- Atom-level selection (atom name, altloc, serial) and its CAVER `start_atom_name` / `start_altloc`
  controls. Recorded in `docs/developer-guide/input-result-workspace.md`.
- `select_chains` disposition: implement it against an explicit owning-Task parameter or remove it from
  Task manifests; it must not remain a no-op alias.

## Remaining gates

- CAVER live scientific acceptance through SLURM/Apptainer remains a Runner gate and is not claimed by
  the browser or server coverage.
- Exact-head CI, independent Adviser and Campaign Acceptance Auditor sign-off.
