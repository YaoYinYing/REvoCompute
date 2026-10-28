# PLACER scientific contract audit

## Canonical category

PLACER is a local all-atom **protein–small-molecule conformational ensemble
resolver**: it reconstructs coordinates from a partially corrupted input
structure, refines ligand placement and conformation given approximate knowledge
of the binding site, and can rebuild nearby protein side chains. It is not a
blind global docking search, and it does not compute binding free energy or
affinity. The pinned README states that global sampling is only technically
possible through `--corruption_centers` and that PLACER "was not explicitly
developed for this task".

Task vocabulary and UI copy now follow that category. The Task id (`placer`),
Runner family, result view ids, and result schemas are unchanged.

## Pinned provenance

- Upstream: `baker-laboratory/PLACER` at commit
  `7dc5563300e7143582d85636bdd413d4c7688e9a` ("updated Mac support",
  2025-11-05). The SIF fetches the same SHA through
  `YaoYinYing/PLACER.git`; the commit SHA is identical in the official
  repository.
- Preprint: Anishchenko et al., *Modeling protein-small molecule conformational
  ensembles with PLACER*, bioRxiv 2024.09.25.614868.
- Read for this audit: `README.md`, `run_PLACER.py`, `PLACER.py`,
  `modules/placer_input.py`, `modules/protocol.py`, `modules/losses.py`,
  `modules/utils.py`, `modules/pdbparser.py`, `examples/commandline_examples.sh`,
  `examples/API_examples.py`, `examples/ligands/75I.json`.
- Built image `placer-rfdiffusion_v1.sif` contains the same source bytes:
  `sha256(run_PLACER.py) = 0df5a7eb…`, `sha256(PLACER.py) = 76007524…`,
  `sha256(modules/protocol.py) = 053e0f0d…`,
  `sha256(modules/losses.py) = cc99abca…`,
  `sha256(modules/utils.py) = 6a0a37a6…`,
  `sha256(modules/placer_input.py) = fd83b365…` in both the pinned checkout and
  `/opt/PLACER` inside the SIF.
- `run_PLACER.py --help` inside the SIF (CPU only) lists every flag emitted by
  the new adapter, including `-f`, `--predict_ligand`, `--fixed_ligand`,
  `--target_res`, `--fixed_ligand_noise`, `--rerank`, `--bonds`, `--mutate`,
  `--crop_centers`, `--corruption_centers`, `--residue_json`,
  `--exclude_common_ligands`, `--predict_multi`, `--use_sm`, `--no-use_sm`.
- Real-output replay: `tests/data/placer-rfdiffusion_replay/3fap_complex_6a55b7e4.json`
  contains a captured run whose CSV columns are
  `label,model_idx,fape,lddt,rmsd,kabsch,prmsd,plddt,plddt_pde` and whose model
  file preserves the input chain and residue numbering.

## Audit table

| Upstream semantics | Current behavior before this change | Action | Test | Evidence |
| --- | --- | --- | --- | --- |
| Resolves a local corrupted complex around a ligand or residue; not global docking and not affinity prediction. | `summary`/`use_when` said "all-atom modeling … from an input structure", open to docking/affinity readings. | Rewrote summary, use_when, input_summary, output_summary, considerations around local conformational reconstruction. | Manifest prose inspected through `isolated_discovery`; fleet contract tests. | README lines 9, 201-202, 218-219; FAQ 9. |
| `-i/--idir` globs only `*.pdb`; `-f/--ifile` accepts one PDB/mmCIF file or a list file. | Adapter passed `-i /workspace/inputs/structures`, so uploaded `.cif`/`.mmcif` files were silently ignored and a CIF-only input failed. | Adapter now passes the single manifest-named structure through `-f`; `.mmcif` is symlinked to a `.cif` name for PLACER's extension dispatch only. | `test_mmcif_records_are_read_and_mmcif_path_is_normalized`, `test_manifest_print_argv_uses_the_named_input_roles`. | `run_PLACER.py` 36-48, 189-192. |
| Multi-file `-i` is a batch convenience; the Task result contract is one CSV and one model file. | Task accepted 1..64 structures, processed every file, then the one-cardinality CSV result would keep only the first input's scores while the model view held all inputs. | Input role `structures` is now cardinality 1; multi-file batch is deliberately outside this Task. | Schema/role load; `test_fleet_result_contract_audit.py`, `test_replay_bundle.py`. | `revocompute/result_storyboard.py` 190-192; `protocol.dump_output` 236-266. |
| The primary-structure radio orders uploads; nothing in the Runner uses it. | UI implied the selected primary controls computation; the Runner processed the whole directory. | Removed the multi-file selection; the single uploaded complex is the scientific input shown in the viewer. | Manifest workspace load; browser result test still opens the replay. | `frontend/src/features/create-task/input-workspace/InputWorkspace.ts` 142-150; old `run.sh` `-i`. |
| `--cautious` skips an input when its output CSV already exists. | Manifest described it as conservative input checks; in a fresh immutable result directory it can never trigger. | Removed from the Task and adapter. | Schema/parameter load; adapter argument-vector tests. | README line 83; `run_PLACER.py` 180-183. |
| `--nsamples` defaults to 10; the README recommends 50–100 for most cases. | Task default was already 50 with no guidance. | Kept 50 and stated the recommendation. | Schema/parameter load. | README 79-80; FAQ 1. |
| `--use_sm` (holo, default) keeps ligand atoms; `--no-use_sm` is an apo run that omits HETATM entities. | Description said it toggles small-molecule features for ligand atoms. | Description now describes holo/apo and notes rmsd and kabsch report zero. | `test_apo_run_emits_no_use_sm`. | README 128-129; `modules/placer_input.py` 256-266; `PLACER.py` 264-270, 279-300. |
| `--predict_ligand` selects ligands to predict and fixes the rest; `--fixed_ligand` fixes selected ligands; the two are alternatives. | Two generic space-separated strings, no conflict or syntax check; upstream silently gives `predict_ligand` precedence. | Added identifier patterns, a server-side conflict rule, and a Runner-side match check. | `test_malformed_or_conflicting_parameters_are_rejected`, `test_ligand_and_center_identifiers_must_exist`. | README 89-92; `modules/protocol.py` 102-137. |
| Without `--predict_ligand`, one ligand is chosen at random when several are present; upstream calls that "meaningless". | Not stated. | Stated in `considerations` and `predict_ligand` help. | Manifest prose inspection. | README 88; `examples/commandline_examples.sh` line 3; `modules/protocol.py` 115-126. |
| `--predict_multi` predicts and scores all allowed ligands; upstream asserts more than one ligand. | Description was close, but a one-ligand run reached PLACER's assert. | Precise description; Runner rejects fewer than two ligands before model load. | `test_predict_multi_requires_more_than_one_ligand`. | README 88; `PLACER.py` 209-210. |
| `--target_res` is a protein residue crop/corruption center and is required when the input has no ligand; with it, corruption is not applied and side chains are rebuilt. | Described only as an optional crop center. | Precise syntax; Runner requires it for ligand-free input. | `test_target_res_is_required_for_a_ligand_free_structure`. | README 93-94, example 150; `modules/protocol.py` 155-181; `PLACER.py` 279-300. |
| `--crop_centers` centers the crop only; it does not select ligands; one center is chosen at random; combining it with `--corruption_centers` ignores the latter with a warning. | Described as "residue or atom selections", implying selection semantics. | Atom-level syntax, explicit non-selection semantics, and a conflict rule. | Parameter conflict test; `test_ligand_and_center_identifiers_must_exist`. | README 106-110; `modules/protocol.py` 190-230. |
| `--corruption_centers` supplies atoms toward which each predicted ligand is corrupted; at least one per predicted ligand is required. | Described as "residue or atom selections around which coordinates are corrupted". | Atom-level syntax; Runner checks the count for predicted ligands. | `test_corruption_centers_need_one_per_predicted_ligand`. | README 111-114; `modules/protocol.py` 194-196. |
| `--fixed_ligand_noise` overrides the backbone noise applied to fixed ligand coordinates. | "Coordinate noise magnitude" did not name the default or units. | Description names the default behavior without repeating its value. | `test_build_argv_roundtrips_every_supported_option`. | README 95-96; `PLACER.py` 198-200. |
| `--rerank` sorts prmsd ascending and plddt/plddt_pde descending; printed model numbers no longer apply. | Description named the metric but not direction or numbering. | Direction and model-number caveat added; adapter passes only allowed values. | `test_malformed_or_conflicting_parameters_are_rejected`. | README 98-101; `modules/utils.py` 160-171. |
| `--bonds` format is `chain-resno-name3-atom:chain-resno-name3-atom:length`. | Described as generic custom bond specifications. | Syntax and example added; Runner validates both atoms and the length. | `test_malformed_or_conflicting_parameters_are_rejected`, center/bond existence check. | README 102-103; `run_PLACER.py` 106-116. |
| `--mutate` format is `resno+chain:name3`; mutation is applied to PDB input only. | Described as generic residue mutation specifications. | Syntax and example added; Runner checks the residue exists and rejects mutation on mmCIF. | `test_malformed_or_conflicting_parameters_are_rejected`, `test_mutation_is_pdb_only`. | README 104-105; `run_PLACER.py` 118-131; `modules/protocol.py` 60-98. |
| `--exclude_common_ligands` skips the AlphaFold3 additive/solvent list during parsing. | Description was broadly correct. | Kept, tightened wording. | `test_build_argv_roundtrips_every_supported_option`. | README 84-87; `modules/utils.py` 174-190. |
| `--residue_json` adds custom residue definitions for `--mutate` or residues already in the structure; the shape is asserted by `add_custom_residues`. | Not exposed as an input at all. | Added optional `custom_residues` JSON role, passed as `--residue_json`, with shape validation and provenance capture. | `test_custom_residue_definitions_follow_the_upstream_shape`. | README 115-120; `modules/placer_input.py` 185-210. |
| `--ligand_file` refines atom typing/connectivity from SDF/MOL2 or CCD; coordinates still come from the PDB/mmCIF; ligands must already be present. | Not exposed. | Deliberately not exposed: the CLI needs a user-supplied `name3:file` mapping, and a typed role cannot carry that mapping without inventing a second name source. It also cannot add a ligand that is absent from the structure. | n/a (documented non-goal). | README 121-124, FAQ 8; `modules/protocol.py` 13-51. |
| `--ignore_ligand_hydrogens` affects only `--ligand_file`. | Exposed even though `ligand_file` was not, so it had no effect. | Removed. | Schema/parameter load; adapter argument-vector tests. | README 125-127. |
| `--ocsv`, `--suffix`, `--weights`, `--idir` are CLI conveniences/model ownership. | Not exposed. | Deliberately not exposed: result naming follows the input stem, weights are server-owned, and the Task is single-input. | n/a. | `run_PLACER.py` 238-251. |
| Custom CSV columns: `fape` (all-atom FAPE loss), `lddt` (actual all-atom lDDT vs reference), `rmsd` and `kabsch` (ligand/rebuilt-atom displacement), `prmsd` (predicted coordinate deviation), `plddt`/`plddt_pde` (predicted confidence). | `kabsch` was missing from the evidence columns; the storyboard did not state directions or reference dependence. | Added `kabsch`; rewrote the result description and storyboard note to separate reference-dependent geometry from predicted confidence and to state directions. | Storyboard/result manifest load; replay bundle tests; `test_placer_shows_the_complex_with_its_own_score_row` keeps the lddt column and numbering note. | README 189-199; `modules/utils.py` 19-39; `modules/losses.py` 1117-1130; replay CSV. |
| The model PDB b-factor column is the predicted per-atom deviation (`pDEVs`); the file is one multi-MODEL PDB. | Storyboard said "The complex and the score row are the same published sample." | Storyboard now says each row names its MODEL by `model_idx`; result description says one MODEL per sample. | Replay browser test (canvas and table) unchanged. | `PLACER.py` 453-456; `modules/utils.py` 140-157; replay PDB. |
| PDB parser keys residues by chain and integer residue number and atoms by name; insertion codes and alternate locations are not represented. | Accepted any PDB; such inputs would silently merge or overwrite residues/atoms. | Runner rejects insertion codes, alternate locations, non-integer residue numbers, and same chain/number residue-name collisions before model load. | `test_insertion_codes_and_alternate_locations_are_rejected`. | `modules/pdbparser.py` 27, 42-45, 158; `modules/utils.py` 140-146. |
| RCSB mmCIF is parsed; mmCIF from other predictors and ligand/mutation post-processing are not supported on the CIF path. | Accepted `mmcif` and `cif` with the same promise as PDB. | Kept both formats but stated the RCSB limitation; `mutate` is rejected for CIF. | `test_mutation_is_pdb_only`; manifest prose inspection. | README line 77, 212; `modules/protocol.py` 92-98. |

## Deliberately unsupported upstream functionality

- Global docking search. `--corruption_centers` remains available as the
  upstream approximation, but the Task does not present it as a docking method.
- Binding affinity or free-energy prediction. PLACER emits confidence and
  reference-geometry scores only.
- `--ligand_file` SDF/MOL2/CCD refinement (needs a second, explicit
  `name3:file` naming contract) and `--ignore_ligand_hydrogens`.
- Batch directory input (`--idir`) and `--suffix`; one complex per Task.
- Non-RCSB mmCIF dialects, hydrogens prediction, insertion-code and altloc
  preservation.

## Outstanding evidence

- GPU/Slurm live smoke with the new `-f` invocation on the family's minimal
  sample, including the real CSV/model artifacts, must run under the Commander's
  serialized accelerator lease. The captured replay already proves the output
  artifact shape for the same single PDB input; the adapter constructs the same
  one-file PLACER invocation for it.
- Browser acceptance of the revised storyboard copy and the result table.
