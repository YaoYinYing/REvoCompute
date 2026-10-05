# fpocket replay bundle

`1suo_2pockets.json` is a bounded, sanitized replay bundle of a **real** fpocket
result, consumed by `tests/frontend_fixtures/` so the production frontend can be
driven against authentic Runner bytes. It is test evidence, not an acceptance
receipt; see `docs/developer-guide/testing.md` for the boundary it occupies.

## What it captures

- **Run**: the pinned fpocket 4.2.3 SIF (`/var/tmp/pr45-sif/fpocket_v1.sif`),
  executed through the family's own `run.sh` → `detect.py` → `normalize_results.py`
  over `tests/data/pdb/1SUO.pdb` at the 100-iteration smoke volume from
  `docker/runners/fpocket/test.yaml`.
- **Manifest**: published through the real server finalize path
  (`task_runtime._finalize_results_manifest`), projected through the shared
  `revocompute.result_projection.project_result_manifest` — the same function
  `GET /compute/api/results` serves through.
- **Result contract it exercises**: the `entity-table` primary over the real
  normalized `pockets.csv`, the `scalar-summary` detection summary, the
  `evidence-bundle` of fpocket's own raw files, and the logical-file/storyboard
  grouping the family declares.
- **Payloads**: 90 textual artifacts, each re-hashed from the source bytes. The
  storyboard is read from the runner deployment tree
  (`result_storyboard.runner_root`), not the result root.

## What it excludes

`1SUO.pdb` and fpocket's own `work/1SUO_out/1SUO_out.pdb` exceed the per-file
payload budget and are recorded in `excluded` with their sha256, size, and reason
— never truncated.

## Honest limitation

The run was scheduled by no batch scheduler: it executed locally through
Apptainer, so there is no Slurm allocation receipt and no task-store status row.
The bundle records that in `provenance.capture.scheduler`. The result bytes, the
normalizer, and the publish path are the real ones; only the cluster scheduling
is absent.
