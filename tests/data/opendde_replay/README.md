# OpenDDE replay bundle: tiny production result

`tiny_production_2f16c036.json` is a bounded replay bundle of a real OpenDDE
production result, served to the browser acceptance suite through the frontend
fixture router. Its artifact bytes are authentic: every payload was downloaded
from the deployment's authenticated artifact API and checked against the served
manifest sha256. It is test evidence, not an acceptance receipt.

## What it captures

- **Run**: task `2f16c036ae748053fe93825e17e464d4`, type `opendde`, deploy
  `57c8114` (campaign base `eae170d`), 2026-10-20T23:27:22 to 23:28:16 (+08:00).
- **Input**: `opendde_tiny.json` (specification role), sha256
  `e6872dbc4567999081d3436f2d5687fd955671b7035061ddfbe39fbbe94d4fd3`: one
  9-residue protein chain, `modelSeeds [101]`.
- **Parameters**: `model_name opendde_v1`, `checkpoint released`, `num_samples 1`,
  `num_steps 10`, `num_cycles 1`, `use_msa false`, `use_template false`,
  `dtype fp32`, `need_atom_confidence true`, `use_tfg_guidance false`.
- **Manifest**: sha256 `42ca915ddca1502e136f4a747e2dcac163026f31e1874ea36bce1c6e7f2c268d`,
  read from the authenticated API. `response` is the repository's own
  `project_manifest_for_serve` projection of the published manifest and was
  verified byte-for-byte identical to what the API served.
- **Payloads**: 7 artifacts, 16705 bytes. Every required view source is present
  (`tiny/seed_101/predictions/tiny_sample_0.cif`,
  `tiny_summary_confidence_sample_0.json`), plus the optional `full_confidences`
  logical file `tiny_full_data_sample_0.json` that the storyboard projects for
  PAE, PDE, and contact probability, and the small submission/SLURM companions.
- **Storyboard**: the checked-in `docker/runners/opendde/storyboard/index.js`,
  sha256 `0f029448f6166a5fa3bc790bfc746218009dba8a03f037a7850853f796374f09`.

Declared artifacts: 10. Checked in: 7. Excluded: 3, each with sha256 and size.

## What it excludes

`citations.bib` and the SLURM stdout/stderr logs. None is read by a declared
view, nothing is truncated, and no excluded path is represented by invented
bytes. The `full_data` JSON is small enough to be carried, so the page computes
its 9 x 9 PAE, PDE, and contact-probability matrices from the captured values.

## Honest limitation

The bundle carries the artifacts the views and storyboard read; it is not the
complete result directory. The storyboard module is the current checked-in
source, not the byte-for-byte module the production result page served: the
Server reads it from the deploying runner tree, which this capture user could not
read.

The run had one sample (`seed_101`), so the candidate list shows one entry. Its
values are shown without client-side rescaling. pLDDT, gPDE, pTM, and ipTM are
model confidence estimates, not experimental validation.

## Capture mode

`provenance.capture.mode` is `synthetic`, and that is the capture's own
observation, not a label choice. The deployment result root is not readable by
the capture user, so the capture could not resolve the task store's finished row
and `result_publications` anchor for the published manifest; without that anchor
`capture_replay_bundle` records the weaker mode by design. The
scientific-contract inventory consequently labels the bundle `synthetic_mock`
with `scientific_claim: none`, even though its bytes came from the real run. The
bundle is preserved as captured and its JSON was never hand-edited to make a
label come out right.

## Recapture

A recapture that could earn the stronger mode needs a read-only copy of the
task's result root and the deployment task database, so the canonical
publication anchor can be resolved:

```python
from pathlib import Path
from frontend_fixtures import capture_replay_bundle, write_bundle

bundle = capture_replay_bundle(
    task_id="2f16c036ae748053fe93825e17e464d4",
    result_root="<result root>",
    task_store="<deployment>/revocompute.sqlite3",
    storyboard_dirs=["docker/runners"],
    provenance={...},
)
write_bundle(Path("tests/data/opendde_replay/tiny_production_2f16c036.json"), bundle)
```

Until then, `tests/fleet/test_replay_bundle.py` re-verifies every payload hash,
the logical-file identities, the storyboard digest and task identity on load, and
`tests/fleet/browser/test_playwright_replay_structure_tasks.py` drives the built
frontend against this bundle.
