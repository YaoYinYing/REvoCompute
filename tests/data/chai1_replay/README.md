# Chai-1 replay bundle: minimal production result

`minimal_production_018c32b6.json` is a bounded replay bundle of a real Chai-1
production result, served to the browser acceptance suite through the frontend
fixture router. Its artifact bytes are authentic: every payload was downloaded
from the deployment's authenticated artifact API and checked against the served
manifest sha256. It is test evidence, not an acceptance receipt.

## What it captures

- **Run**: task `018c32b6d5d97dbb2fd99792155211b2`, type `chai1_predict`, deploy
  `57c8114` (campaign base `eae170d`), 2026-10-21T00:57:10 to 00:59:15 (+08:00).
- **Input**: `minimal.fasta` (entities role), sha256
  `c53e07aafbfc563781ec87fb8a8ee13179957c9e99ad0ac6f099e6c2365da6e1`.
- **Parameters**: `use_esm_embeddings true`, `use_msa false`,
  `use_restraints false`, `num_trunk_recycles 1`, `num_diffusion_timesteps 2`,
  `num_diffusion_samples 1`, `seed 0`, `low_memory true`.
- **Upstream**: Chai 0.6.1, commit `8d5ac0f9`; the run's `run_metadata.json`
  records `runtime_network: false`.
- **Manifest**: sha256 `f877ef7461e731dc31fb7f10e58cba673f70d98279759fcc51c1fa8732f7fb1e`,
  read from the authenticated API. `response` is the repository's own
  `project_manifest_for_serve` projection of the published manifest and was
  verified byte-for-byte identical to what the API served.
- **Payloads**: 11 artifacts, 36228 bytes. The required view sources are the
  ranked CIF (`ranked/rank_0.model_idx_0.cif`), `confidence.rank_0.json`, and the
  three confidence arrays `plddt.rank_0.npy`, `pae.rank_0.npy`,
  `pde.rank_0.npy` — the NPY files are base64 with hash and size taken from the
  decoded bytes. `ranking.json`, `run_metadata.json`, and `chai1-model-assets.json`
  are the evidence-bundle items.
- **Storyboard**: the checked-in `docker/runners/chai1/storyboard/index.js`,
  sha256 `cb6b8d06d534316acaa162525458eb752cc8a825c8fb5057f758e1316f8697aa`.

Declared artifacts: 17. Checked in: 11. Excluded: 6, each with sha256 and size.

## What it excludes

`citations.bib`, the captured input FASTA, the SLURM stdout/stderr logs, and the
upstream intermediates (`upstream/pred.model_idx_0.cif`,
`upstream/scores.model_idx_0.npz`). None is read by a declared view, nothing is
truncated, and no excluded path is represented by invented bytes. The NPY
confidence arrays are small enough to be carried, so the page draws the captured
values through the server's bounded projection route rather than a placeholder.

## Honest limitation

The bundle carries the artifacts the views and storyboard read; it is not the
complete result directory. The storyboard module is the current checked-in source,
not the byte-for-byte module the production result page served: the Server reads it
from the deploying runner tree, which this capture user could not read.

This was a single-chain run, so the published `iptm` is 0.0, which is the value the
page shows; the bundle does not relabel it as an interface quality. pLDDT (shown on
Chai-1's persisted 0–1 scale), pTM, and ipTM are model confidence estimates, not
experimental validation.

The captured `chai1-model-assets.json` embeds the host provisioning root in its
`provisioning_root` field, because `docker/runners/chai1/run.sh` copies the
checked-in `model-assets.json` into the result unchanged. That is a real artifact
defect of the run (the same class as the Boltz one fixed in `8082c1e`), not a
defect of the replay: the bytes are shown as published and the bundle does not
rewrite them. `chai1-model-assets.json` is a required item of the
`prediction_evidence` view, so the bundle cannot drop it without dropping the
view.

The replay harness's host-path guard did not catch this path, and that is a
second, separate defect: `_HOST_PATH` in `tests/frontend_fixtures/replay_bundle.py`
only matches a path preceded by whitespace or the start of a string, so a path
that begins a JSON string value is not detected. The same gap already admits
`(/tmp/rc/prodrop)` in the BioEmu bundle's `provenance.source`. The fix belongs
in the guard (and then a recapture), not in a hand edit of this file.

Unblocking the runner side needs a Chai-1 `model-assets.json` that does not
publish an operator path, a SIF rebuild, a fresh production run, and a recapture.

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
    task_id="018c32b6d5d97dbb2fd99792155211b2",
    result_root="<result root>",
    task_store="<deployment>/revocompute.sqlite3",
    storyboard_dirs=["docker/runners"],
    provenance={...},
)
write_bundle(Path("tests/data/chai1_replay/minimal_production_018c32b6.json"), bundle)
```

Until then, `tests/fleet/test_replay_bundle.py` re-verifies every payload hash,
the logical-file identities, the storyboard digest and task identity on load, and
`tests/fleet/browser/test_playwright_replay_structure_tasks.py` drives the built
frontend against this bundle.
