# ColabFold (AlphaFold2) replay bundle: 2KL8 production result

`2kl8_production_e3c6c52d.json` is a bounded replay bundle of a real ColabFold
production result, served to the browser acceptance suite through the frontend
fixture router. Its artifact bytes are authentic: every payload was downloaded
from the deployment's authenticated artifact API and checked against the served
manifest sha256. It is test evidence, not an acceptance receipt.

## What it captures

- **Run**: task `e3c6c52dd2eabbe020edd567e8444010`, type `colabfold_af2`, deploy
  `57c8114` (campaign base `eae170d`), 2026-10-21T01:02:44 to 01:04:20 (+08:00).
- **Input**: `2KL8.fasta` (sequence role), sha256
  `511d73a16c00fb6a26376e1100317348973a956295ba753098e6ff08cdd53392` (79 aa).
- **Parameters**: `model_type alphafold2_ptm`, `msa_mode single_sequence`,
  `num_recycle 0`, `num_models 1`, `num_seeds 1`, `random_seed 0`, `num_relax 1`,
  `use_fast_kernels false`.
- **Manifest**: sha256 `122d75b7d940a4051ea23ea7316b419ca8d878956b81be46f0de806542afbc89`,
  read from the authenticated API. `response` is the repository's own
  `project_manifest_for_serve` projection of the published manifest and was
  verified byte-for-byte identical to what the API served.
- **Payloads**: 10 artifacts, 231853 bytes. The required view sources
  (`2KL8_scores_rank_001_*.json`, the relaxed and unrelaxed ranked PDBs,
  `2KL8.a3m`) plus the small JSON companions (`config.json`,
  `debug/submission.json`, the SLURM resource/status records).
- **Storyboard**: the checked-in `docker/runners/colabfold_af2/storyboard/index.js`,
  sha256 `d1d2fd1ab1c335c1e0047274645a494d363b9634faaa12fa5400f5d68c4466a4`.

Declared artifacts: 24. Checked in: 10. Excluded: 14, each with sha256 and size.

## What it excludes

Every excluded entry is a declared artifact the capture did not check in, never
truncated: the per-model PNG plots (`*_coverage.png`, `*_pae.png`, `*_plddt.png`),
the binary `2KL8.pickle` (101911 bytes), `citations.bib`, `cite.bibtex`,
`log.txt`, the `.colabfold-msa-complete` / `2KL8.done.txt` markers, the captured
input FASTA, and the SLURM stdout/stderr logs. None is read by a declared view.

## Honest limitation

This was a single-sequence, one-model run, so the publication contains one ranked
model and no `interface_scores.json`. The `interface_confidence` view declares
`sources.data: []` for that case and the page states "This view has no available
artifact." rather than showing a stale or invented interface panel — the replay
asserts exactly that.

The bundle carries the artifacts the views and storyboard read; it is not the
complete result directory. The storyboard module is the current checked-in source,
not the byte-for-byte module the production result page served: the Server reads it
from the deploying runner tree, which this capture user could not read.

Nothing in the bundle asserts that the prediction is scientifically correct.
pLDDT (persisted on the 0–100 scale and shown on it) and pTM are model confidence
estimates; they are not experimental validation.

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
    task_id="e3c6c52dd2eabbe020edd567e8444010",
    result_root="<result root>",
    task_store="<deployment>/revocompute.sqlite3",
    storyboard_dirs=["docker/runners"],
    provenance={...},
)
write_bundle(Path("tests/data/colabfold_af2_replay/2kl8_production_e3c6c52d.json"), bundle)
```

Until then, `tests/fleet/test_replay_bundle.py` re-verifies every payload hash,
the logical-file identities, the storyboard digest and task identity on load, and
`tests/fleet/browser/test_playwright_replay_structure_tasks.py` drives the built
frontend against this bundle.
