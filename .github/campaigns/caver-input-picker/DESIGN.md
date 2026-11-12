# PR-3 — CAVER 3.0.2 input form, typed start selection and exact scientific config

**Status:** READY FOR FINAL REVIEW; base `21b62a2c7fd6ce4862d05cf88fbdd111ac0af6d4`. **Hard prerequisite:** merged and verified shared Mol* scene contract in #152. **Owner:** CAVER Runner + its frontend input-workspace plugin; Core retains input-validation authority.

## Existing evidence
`docker/runners/caver302/tasks/caver/task.yaml` declares start modes `point`, `atom`, `residue`, `group`, `ligand` with JSON Schema conditional fields; group requires `start_group`, **not** `start_residue_number`. `docker/runners/caver302/pdb_selection.py` resolves authored atom/residue identities; `caver_config.py` only authorizes `exclude_residue_ids`, `exclude_residue_names`, and `exclude_atom_numbers` as list-like exclusion directives. `frontend/src/features/create-task/input-workspace/builtins.ts` and existing CAVER selection tests already cover parts of residue/group selection. **Never duplicate existing working selection logic**.

## Scientific interaction model
The unified picker has explicit modes:
- **XYZ point:** editable Angstrom XYZ with one crosshair in the active reference structure; source `manual` or `viewer-crosshair`, recorded in provenance.
- **Atom:** pick a stable authored atom identity (chain, residue number/insertion code, atom name, serial, altloc) and map it to the exact pinned Runner parameters. A UI click without an unambiguous author numbering/serial mapping must refuse with a useful message.
- **Residue / ligand:** select by exact authored chain/residue identity; expose *geometric centroid* and *mass-weighted COM* as **different** ways to write an explicit XYZ point only where atom masses/selection are scientifically well defined. Do not call the existing CAVER residue/group calculation COM.
- **Group:** select several supported residues/chains and write `start_point_mode=group` plus canonical `start_group`; do not keep or require a stale `start_residue_number`. Group's existing geometric center stays labeled as such. If the user explicitly converts a group to a COM or centroid XYZ, use `start_point_mode=point`, record all selected atoms and method, and never imply CAVER's internal group semantics are unchanged.

Selection is bound to the currently loaded reference topology revision/digest from #152; changing the reference invalidates names, XYZ-derived provenance, selected atom identifiers and preview overlays. Keep bidirectional UI/form sync idempotent and avoid stale-selection races.

## Residue names and include/exclude directives
Derive residue_name choices only from the actual PDB reference atoms (with ligand aliases and exact case), not a hard-coded amino-acid list. Form can render every currently present residue, but emitted values must map to **upstream accepted syntax**. Parse comma/range syntax consistently with the Runner. Verify against the pinned CAVER 3.0.2 JAR, its documentation and observed generated config which **include** counterpart directives exist and whether they are mutually exclusive with exclusions. Add `include_residue_ids`, `include_residue_names`, `include_atom_numbers` **only if proven in the pinned executable**, with an explicit compatibility matrix and negative tests. If not supported, document omission rather than quietly generating invented config keys.

Use only the existing `seed` parameter and the shared x-ui seed widget; no new `random_seed` alias. Test permitted 32-bit signed range and determinism. Validate other CAVER numerical fields within `task.yaml` and `caver_config.py` without introducing a second schema. Preserve existing `start_group` structure and negative validation for insertion codes, chainless entries and altloc ambiguity.

## Exact provenance and results
Ensure the input workspace preview, immutable Task snapshot, generated CAVER config and `data/origins.pdb` agree on the chosen position. Record source type (`manual`, `atom`, `residue`, `ligand`, `group`, `com`, `centroid`), reference topology SHA, original authored IDs, selected atom serials, coordinate method and units. Provenance must never claim COM if the Runner used geometric centroid. Keep existing `run_caver.py` reference + <=50 snapshot mapping, output publication contract and normalized CAVER results unchanged.

## UI and accessibility
Use the shared viewer for crosshair and selection; one concise panel with mode, picked source label, active XYZ and status. Support reset/reselect, keyboard-driven manual XYZ fallback, clear error on ambiguous selections, light/dark and desktop/tablet/mobile responsive controls. Source name refresh should be async-cancelled on topology changes.

## Tests and stop conditions
Headless tests compare typed selection `->` normalized schema `->` `pdb_selection.resolve_start_point` `->` `caver_config.render_config` `->` published provenance, for single/multi-chain structures, hetero ligands, groups, insertion/altloc ambiguity and out-of-range serials. Replay existing CAVER fleet fixtures and browser interactions; screen capture before/after. Test group-without-residue-number, COM vs centroid numeric difference, empty/incomplete selection and deterministic seed. Do not claim include grammar without an actual pinned-JAR run. Unreleased notes for user-visible behavior only.

## Non-goals
No CAVER engine replacement, no new generic structural viewer, no MD conversion or trajectory ingester in this PR. #156 will provide topology+trajectory -> ordered CAVER-compatible PDB snapshots after its own scientific proof. No deployment or merge without maintainer.
## Pinned directive audit (2026-11-13)

Evidence is from the pinned distribution (`distribution_sha256 2d819541…`, `caver.jar` SHA-256 `6ed4d88f…`), its shipped `user_guide`, the constants in `caver/CalculationSettings.class`, and an observed run of that JAR on `tests/data/3fap_hf3_A_short.pdb` with all six filter directives in one config (exit 0; host JDK 17, same JAR bytes the SIF pins, not a SIF/JRE 8 execution).

| Directive | Present in pinned build | Combinable with the other family |
| --- | --- | --- |
| `include_residue_names` | yes | yes |
| `include_residue_ids` | yes | yes |
| `include_atom_numbers` | yes | yes |
| `exclude_residue_names` / `exclude_residue_ids` / `exclude_atom_numbers` | yes | yes |

The upstream guide states that CAVER first selects the union of every include directive (or all atoms when no include is present, the automatic `include *`), then removes the exclude set, and that file order does not matter. The observed run demonstrates that the pinned JAR accepts all six directives together in one config (host JDK 17, exit 0); it is an acceptance check, not a formal precedence proof. Both families are therefore offered; the Task validates every include token against the reference structure exactly as it already validates exclusions, so a typo fails instead of silently narrowing the calculation.

`20_AA` is an upstream alias, not a residue actually present in a structure. It is not offered or accepted: every emitted residue name comes from the loaded reference atoms, and the Task's own validation requires the name to exist.
