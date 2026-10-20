# BioEmu replay bundle: 2KL8 production result

`2kl8_production_115a4a8a.json` is a captured production BioEmu result, served to
the browser acceptance suite through the frontend fixture router. It is not a
fixture and it is not synthetic: `provenance.capture.mode` is
`reproduced_real_result`, resolved from the deployment task store's finished row
and its `result_publications` manifest anchor.

## Provenance

- Task `115a4a8af225b37c002f1c1a88e9d82c`, type `bioemu`, finished
- Deploy commit `57c8114`; SLURM job `309738`
- SIF sha256 `03584083ff142829ae33c88620d2e83c3b70eb285980d134ac4a51d730b3fc98`
- Input `2KL8.fasta` sha256 `511d73a16c00fb6a26376e1100317348973a956295ba753098e6ff08cdd53392` (79 aa)
- Parameters: `num_samples 24`, `batch_size_100 4`, `denoiser_type dpm`,
  `filter_samples true`, `base_seed 7`
- Manifest sha256 `b12f655badd0da0214925bf5639628df2a642d3c1ef591b1f0cbb74ac6b522bd` (7212 bytes), output check passed
- `samples.xtc` 36924 bytes sha256 `9bafc38108a0ef9155ffce2e7035f2874235279dfea1d02c710c52cc000abcb7`
- `topology.pdb` 31702 bytes sha256 `45b172920650c482cd06cbfd6a5d5f93a7228dd46da7070e8169b8914946f9e1`

The bundle carries only the two required view sources (`topology.pdb` as text,
`samples.xtc` as base64) and the empty SLURM stderr diagnostic. Everything else —
the four `batch_*.npz` files, `sequence.fasta`, `citations.bib`, the execution
JSON — is recorded in `excluded` with its hash and size; the capture never
invents bytes it did not read.

## What is authentic and what is not

Authentic: the manifest response, both required view sources, and the task
identity. mdtraj reads the served XTC as 23 frames of 391 heavy atoms over 79
residues in one chain (CA RMSD vs. frame 0 is 0.000–0.284 nm); the XTC `time`
values 0..23 are sample-index placeholders, not physical time.

Not available in this capture, and deliberately not fabricated:

- BioEmu drew 24 samples; the validity filter dropped exactly one and published
  23. The other three drawer counts are not published.
- No population weights, energies, kinetics, or original sample ids are
  published, so none are shown.
- The production manifest was published before this Task declared
  `expected_files.yaml` and a Storyboard, so `response.storyboard` is `null` and
  `result.files` is empty. The storyboard module is exercised separately by the
  browser test from the checked-in runner tree against this bundle's artifacts.

## Recapture

The capture is deterministic given the result root and the task store. With a
read-only staged copy of the result root and the deployment SQLite database:

```python
from pathlib import Path
from frontend_fixtures import capture_replay_bundle, write_bundle

bundle = capture_replay_bundle(
    task_id="115a4a8af225b37c002f1c1a88e9d82c",
    result_root="<result root>",
    task_store="<deployment>/revocompute.sqlite3",
    storyboard_dirs=["docker/runners"],
    provenance={...},
    max_payload_bytes=1_048_576,
    max_bundle_bytes=1_048_576,
)
write_bundle(Path("tests/data/bioemu_replay/2kl8_production_115a4a8a.json"), bundle)
```

`tests/fleet/test_replay_bundle.py` re-verifies every payload hash and the
publication anchor on load.
