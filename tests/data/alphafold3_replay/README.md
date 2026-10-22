# AlphaFold 3 replay bundle: tiny production result

`tiny_production_4fed6908.json` is a bounded replay bundle of a real AlphaFold 3
production result, served to the browser acceptance suite through the frontend
fixture router. Its artifact bytes are authentic: every payload was downloaded
from the deployment's authenticated artifact API and checked against the served
manifest sha256. It is test evidence, not an acceptance receipt.

## What it captures

- **Run**: task `4fed69081a408adb00f3dc76b6880dc7`, type `alphafold3`, deploy
  `57c8114` (campaign base `eae170d`), 2026-10-20T22:47:29 to 22:49:31 (+08:00).
- **Input**: `alphafold3_tiny.json` (specification role), sha256
  `4e8b10c2f6b512a1e6064b31ef2ac00c065713f6fa239efaf4953fb57baa0ad8`.
- **Parameters**: `max_template_date 2021-09-30`, `num_recycles 1`,
  `num_diffusion_samples 1`, `resolve_msa_overlaps true`, `save_embeddings false`,
  `save_distogram false`.
- **Manifest**: sha256 `0e2aaabe9c034cff26c5631e3ef662b9becd992efa35cced385757aac84c9c99`,
  read from the authenticated API. `response` is the repository's own
  `project_manifest_for_serve` projection of the published manifest and was
  verified byte-for-byte identical to what the API served.
- **Payloads**: 15 artifacts, 73992 bytes. The required view sources (two model
  CIFs, two summary-confidence JSONs) plus the `evidence-bundle` items
  (`tiny-protein_ranking_scores.csv`, both `*_confidences.json`, both `*_data.json`)
  and the `TERMS_OF_USE.md` the model ships beside its outputs.
- **Storyboard**: `docker/runners/alphafold3/storyboard/index.js` as it stood at
  capture time, sha256
  `d6a0b0848712b58d4b533f33b11c3dbbbdb826919a5c9273ecaa4cbdb93bdbe8`; later
  commits revised the module.

Declared artifacts: 21. Checked in: 15. Excluded: 6, each with sha256 and size.

## What it excludes

All six excluded entries are small and none is read by a declared view:
`.alphafold3-features-complete`, `citations.bib`, and the stdout/stderr logs of
the features and model SLURM jobs. Nothing is truncated, and no excluded path is
represented by invented bytes.

The run published two structure records (a seed-1 sample and the combined
record), so the `scalar-summary` view shows the first of two published summary
records and says so.

## Honest limitation

The bundle carries the artifacts the views and storyboard read; it is not the
complete result directory. The storyboard module is the source as it stood at
capture time, not the byte-for-byte module the production result page served
and not the current checked-in file: the Server reads it from the deploying
runner tree, which this capture user could not read, and later commits revised
it. The replayed page therefore shows a reviewed storyboard against authentic
result bytes.

Nothing in the bundle asserts that the prediction is scientifically correct. pTM,
ipTM, and pLDDT shown by this page are model confidence estimates; they are not
experimental validation. The captured ipTM is null (single chain), and the replay
shows it as not available rather than inventing a value.

## Capture mode

`provenance.capture.mode` is `synthetic`, and that is the capture's own
observation, not a label choice. The deployment result root is not readable by
the capture user, so the capture could not resolve the task store's finished row
and `result_publications` anchor for the published manifest; without that anchor
`capture_replay_bundle` records the weaker mode by design. The scientific-contract
inventory consequently labels the bundle `synthetic_mock` with
`scientific_claim: none`, even though its bytes came from the real run. The
bundle is preserved as captured and its JSON was never hand-edited to make a label
come out right.

## Recapture

A recapture that could earn the stronger mode needs a read-only copy of the task's
result root and the deployment task database, so the canonical publication
anchor can be resolved:

```python
from pathlib import Path
from frontend_fixtures import capture_replay_bundle, write_bundle

bundle = capture_replay_bundle(
    task_id="4fed69081a408adb00f3dc76b6880dc7",
    result_root="<result root>",
    task_store="<deployment>/revocompute.sqlite3",
    storyboard_dirs=["docker/runners"],
    provenance={...},
)
write_bundle(Path("tests/data/alphafold3_replay/tiny_production_4fed6908.json"), bundle)
```

Until then, `tests/fleet/test_replay_bundle.py` re-verifies every payload hash,
the logical-file identities, the storyboard digest and task identity on load, and
`tests/fleet/browser/test_playwright_replay_structure_tasks.py` drives the built
frontend against this bundle.
