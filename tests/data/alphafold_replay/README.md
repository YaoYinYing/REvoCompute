# AlphaFold2 replay bundle: 2KL8 production result

`2kl8_production_51d8c875.json` is a bounded replay bundle of a real AlphaFold2
production result, served to the browser acceptance suite through the frontend
fixture router. Its artifact bytes are authentic: every payload was downloaded
from the deployment's authenticated artifact API and checked against the served
manifest sha256. It is test evidence, not an acceptance receipt.

## What it captures

- **Run**: task `51d8c8758237e84ef5240382880045ee`, type `alphafold`, deploy
  `57c8114` (campaign base `eae170d`), 2026-10-20T22:28:21 to 22:44:50 (+08:00).
- **Input**: `2KL8.fasta` (sequence role), sha256
  `511d73a16c00fb6a26376e1100317348973a956295ba753098e6ff08cdd53392` (79 aa).
- **Parameters**: `model_preset monomer_ptm`, `max_template_date 2021-11-01`,
  `db_preset full_dbs`, `models_to_relax none`, benchmark off.
- **Manifest**: sha256 `8511bc1b546a19e1f38c8016e40ff59a8c95c0ce05a3c808ea02a3037efa06e3`,
  read from the authenticated API. `response` is the repository's own
  `project_manifest_for_serve` projection of the published manifest and was
  verified byte-for-byte identical to what the API served.
- **Payloads**: 21 artifacts, 398366 bytes. The required view sources
  (`ranking_debug.json`, five `confidence_*.json`, five `pae_*.json`, five
  `ranked_*.pdb`) plus the small JSON companions the storyboard reads
  (`timings.json`, `debug/submission.json`, the SLURM resource/status records).
- **Storyboard**: `docker/runners/alphafold/storyboard/index.js` as it stood at
  capture time, sha256
  `fe647218e24810032985d2bd35168e28a9766261ce12d8a8a0af92d3287a2643`; later
  commits revised the module.

Declared artifacts: 53. Checked in: 21. Excluded: 32, each with sha256 and size.

## What it excludes

Every excluded entry is a declared artifact the capture did not check in, never
truncated. The significant ones:

- the five `result_model_*.pkl` (about 7 MB each) and `2KL8/features.pkl`
  (1099928 bytes) — binary and over the per-file payload budget;
- the MSA/template searches (`bfd_uniref_hits.a3m`, `mgnify_hits.sto`,
  `uniref90_hits.sto`, `pdb_hits.hhr` at 330276 bytes) and the five
  `unrelaxed_*` structures;
- the `.cif` copies of the ranked structures, `citations.bib`, the captured
  input FASTA, and the SLURM stdout/stderr logs.

## Honest limitation

The bundle carries the artifacts the views and storyboard read; it is not the
complete result directory. A replay therefore cannot exercise a path that reads
an excluded artifact (for example, the pickles or the MSA hits), and no excluded
path is represented by invented bytes.

The storyboard module is the source as it stood at capture time, not the
byte-for-byte module the production result page served and not the current
checked-in file: the Server reads it from the deploying runner tree, which this
capture user could not read, and later commits revised it. The replayed page
therefore shows a reviewed storyboard against authentic result bytes.

Nothing in the bundle asserts that the prediction is scientifically correct.
pLDDT and pTM shown by this page are model confidence estimates; they are not
experimental validation.

## Capture mode

`provenance.capture.mode` is `synthetic`, and that is the capture's own
observation, not a label choice. The deployment result root is not readable by
the capture user, so the capture could not resolve the task store's finished row
and `result_publications` anchor for the published manifest; without that anchor
`capture_replay_bundle` records the weaker mode by design. The scientific-contract
inventory consequently labels the bundle `synthetic_mock` with
`scientific_claim: none`, even though its bytes came from the real run. The
bundle is preserved as captured; its JSON was never hand-edited to make a label
come out right, and no mode is asserted that the capture did not observe.

## Recapture

A recapture that could earn the stronger mode needs a read-only copy of the task's
result root and the deployment task database, so the canonical publication
anchor can be resolved:

```python
from pathlib import Path
from frontend_fixtures import capture_replay_bundle, write_bundle

bundle = capture_replay_bundle(
    task_id="51d8c8758237e84ef5240382880045ee",
    result_root="<result root>",
    task_store="<deployment>/revocompute.sqlite3",
    storyboard_dirs=["docker/runners"],
    provenance={...},
)
write_bundle(Path("tests/data/alphafold_replay/2kl8_production_51d8c875.json"), bundle)
```

Until then, `tests/fleet/test_replay_bundle.py` re-verifies every payload hash,
the logical-file identities, the storyboard digest and task identity on load, and
`tests/fleet/browser/test_playwright_replay_structure_tasks.py` drives the built
frontend against this bundle.
