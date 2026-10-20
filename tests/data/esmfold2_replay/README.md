# ESMFold 2 replay bundle: minimal production result

`minimal_production_9803381e.json` is a bounded replay bundle of a real ESMFold 2
production result, served to the browser acceptance suite through the frontend
fixture router. Its artifact bytes are authentic: every payload was downloaded
from the deployment's authenticated artifact API and checked against the served
manifest sha256. It is test evidence, not an acceptance receipt.

## What it captures

- **Run**: task `9803381e59eeb152b0c654dcd1c4d871`, type `esmfold2_predict`, deploy
  `57c8114` (campaign base `eae170d`), 2026-10-21T00:59:37 to 01:02:10 (+08:00).
- **Input**: `minimal.fasta` (sequence role), sha256
  `6a2134f4b4b1fabd218c9ba994889a4281e773de30fe8c1dd5b96f6d72594b29`.
- **Parameters**: `model_variant fast`, `num_loops 1`, `num_sampling_steps 2`,
  `num_diffusion_samples 1`, `seed 0`, `msa_max_depth 1024`,
  `kernel_backend cuequivariance`, `include_embeddings false`.
- **Manifest**: sha256 `a07a41390013d1d8a84794d319f26a043d4b078bea96756065a03a9dbc69f1ff`,
  read from the authenticated API. `response` is the repository's own
  `project_manifest_for_serve` projection of the published manifest and was
  verified byte-for-byte identical to what the API served.
- **Payloads**: 9 artifacts, 32632 bytes — every required view source
  (`mini_protein/sample_001.cif`, `sample_001_confidence.json`,
  `sample_001_plddt.csv`, `sample_001_pae.json`), the evidence item
  `mini_protein/prediction.json`, `work_items.json`, and the small
  submission/SLURM companions.
- **Storyboard**: the checked-in `docker/runners/esmfold2/storyboard/index.js`,
  sha256 `1d9fa4579cb62a260b6038557a97eb17adb6dcde8d5566d51c5341d950255e2a`.

Declared artifacts: 13. Checked in: 9. Excluded: 4, each with sha256 and size.

## What it excludes

`citations.bib`, the captured input FASTA, and the SLURM stdout/stderr logs. None
is read by a declared view, and nothing is truncated.

## Honest limitation

The bundle carries the artifacts the views and storyboard read; it is not the
complete result directory. The storyboard module is the current checked-in source,
not the byte-for-byte module the production result page served: the Server reads it
from the deploying runner tree, which this capture user could not read.

The run published one sample. pLDDT is persisted by ESMFold 2 on its own 0–1
scale and the page shows it on that scale rather than rescaling it to 0–100; pTM is
a model confidence estimate. Neither is experimental validation, and nothing in the
bundle claims the prediction is scientifically correct.

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
    task_id="9803381e59eeb152b0c654dcd1c4d871",
    result_root="<result root>",
    task_store="<deployment>/revocompute.sqlite3",
    storyboard_dirs=["docker/runners"],
    provenance={...},
)
write_bundle(Path("tests/data/esmfold2_replay/minimal_production_9803381e.json"), bundle)
```

Until then, `tests/fleet/test_replay_bundle.py` re-verifies every payload hash,
the logical-file identities, the storyboard digest and task identity on load, and
`tests/fleet/browser/test_playwright_replay_structure_tasks.py` drives the built
frontend against this bundle.
