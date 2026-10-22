# BioEmu2 replay bundle: 2KL8 production result

`2kl8_production_4d77ffcc.json` is a captured BioEmu2 equilibrium-ensemble
result, served to the browser acceptance suite through the frontend fixture
router. It is not synthetic: `provenance.capture.mode` is
`reproduced_real_result`, resolved from a finished task row in the deployment task
store and its server-owned publication anchor.

## Run identity

- Task `4d77ffccf4519b73f73cb9cf2cd8ac28`, type `bioemu2_equilibrium`, finished
  2026-10-21T10:22:49 (+08:00); walltime 63.4 s
- Input `2KL8.fasta` (role `sequence`), sha256
  `511d73a16c00fb6a26376e1100317348973a956295ba753098e6ff08cdd53392` (79 aa)
- Parameters: `num_samples 2`, `sampler edm`, `num_steps 4`,
  `physicality_mode high_quality`, `seed 0`
- Manifest sha256
  `8e7f9314dd185d436a8998357bbdff7cb0aa941f0bc2e1cc6e3ebbfc2f88d2b3`
  (10213 bytes), publication revision 1
- Declared view: `conformational_ensemble` (`trajectory`, primary) over
  `topology.pdb` and `samples.xtc`, `frame_unit: sample`

## Payload inventory

Twelve payloads, 117966 bytes declared in total; 139858 bytes in the bundle file
(the binary XTC is carried base64).

| Path | Bytes | Role |
| --- | --- | --- |
| `samples.xtc` | 5944 | coordinates, sha256 `d0f3845cd735f4000adbb92ae3ac9795b896a16a9601962a24c7fb513e7bd5da` |
| `topology.pdb` | 52357 | adapter PDB topology, sha256 `1437bc93750968364111ea8cf849a5d0e3e1677a954b67210912a30515c40496` |
| `topology.cif` | 57760 | upstream topology, sha256 `9387643c18139995991d57991ec1521ecdb46f26b06e91a7a060714e9c4a15dd` |
| `physicality.json` | 177 | per-sample verdicts, sha256 `22a533e6b5dd72683ac09e182628a746f7e8df09ddc4908397b3dc0746e29dbc` |
| `system.yaml` | 207 | resolved sampling system, sha256 `c0f5d2e2102e2b190d3a1793f2a3a86f29192b417633d4bb157c550888e3cbf6` |
| `sequence.fasta` | 87 | sampled sequence, sha256 `9d82e8842fbff46e33b4a3e23634efa277f6021876b8f58879ad77a097664ff3` |
| `debug/inputs/sequence/2KL8.fasta` | 85 | submitted input |
| `debug/submission.json` | 436 | submission record |
| `execution/slurm-status.execution.json` | 262 | scheduler status |
| `execution/slurm-*.resource.json` | 527 | resource observation |
| `execution/slurm-*.stdout.log` | 124 | job stdout |
| `execution/slurm-*.stderr.log` | 0 | empty |

`excluded` is empty: the capture kept every published artifact.

## What the capture mode means

`reproduced_real_result` is the stronger of the two modes
`capture_replay_bundle` writes. The capture resolved the task's finished row and
its `result_publications` anchor (`manifest_sha256`, `manifest_size`,
`revision`) from the deployment task database, read the result root read-only,
and recorded every served artifact path; each payload was checked against the
manifest's sha256, binary coordinates were carried as base64, and host-local
paths and secret-shaped metadata were scrubbed before persistence.
`tests/fleet/test_replay_bundle.py` re-verifies the stored bundle digest, every
payload hash and size, the task identity, and the publication anchor on load.

## Honest limitations

- **Both published frames are `rejected`.** Upstream's physicality check reports
  `bad_bonds_sidechain` for sample 0 and sample 1. Upstream does not filter
  rejected samples out, so the page must show 0 of 2 accepted rather than an
  ensemble that looks clean.
- **Two samples over four denoising steps is a contract demonstration, not a
  converged ensemble.** The run exists to exercise the Task, its view, and its
  storyboard end to end; it says nothing about the conformational landscape.
- **Hardware.** Upstream's smallest tested device is an 80 GB A100. This run was
  accepted on a 40 GB host, so it is outside upstream's tested envelope.
- **No storyboard in the served manifest.** The production manifest was
  published before this Task declared a Storyboard, so `response.storyboard` is
  `null`. The manifest does carry the six logical `result.files` entries this
  Task resolves; the browser test adds only the Storyboard declaration (through
  the Server's own resolver) and serves the capture's own views, file URLs, and
  artifact bytes.
- **Not scientific validation.** The bundle asserts what the run published, not
  that the sampled conformations are correct.

## Recapture

The capture is deterministic given the result root and the task store. A
manifest that declares a storyboard whose entrypoint does not resolve in the
supplied runner tree fails the capture closed; this capture predates the Task's
declaration, so it carries no storyboard source. With a read-only staged copy
of the result root and the deployment SQLite database:

```python
from pathlib import Path
from frontend_fixtures import capture_replay_bundle, write_bundle

bundle = capture_replay_bundle(
    task_id="4d77ffccf4519b73f73cb9cf2cd8ac28",
    result_root="<result root>",
    task_store="<deployment>/revocompute.sqlite3",
    storyboard_dirs=["docker/runners"],
    provenance={...},
    max_payload_bytes=1_048_576,
    max_bundle_bytes=1_048_576,
)
write_bundle(Path("tests/data/bioemu2_replay/2kl8_production_4d77ffcc.json"), bundle)
```
