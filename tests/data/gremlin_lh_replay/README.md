# GREMLIN_LH replay bundle

`2kl8_seed0_944ed43af62e.json` is a bounded, sanitized replay bundle of one real
GREMLIN_LH result, consumed by `tests/frontend_fixtures/` so the production
frontend can be driven against authentic Runner bytes. It is test evidence, not
an acceptance receipt; see `docs/developer-guide/testing.md` for the boundary it
occupies.

## What it captures

- **Task**: `944ed43af62ead9f5c9560bae1ccd897` — the canonical 2KL8 GREMLIN_LH
  case (`gremlin_lh_fit`, seed 0, input `2KL8.i90c75_aln.a3m`), read-only from
  the production result store as the task owner. No new Slurm job.
- **Manifest**: the published ResultManifest (schema v3), projected through the
  shared `revocompute.result_projection.project_result_manifest` — the same
  function `GET /compute/api/results` serves through.
- **Storyboard**: read from the runner deployment tree
  (`result_storyboard.runner_root`), not the result root.
- **Payloads**: 17 textual/scientific artifacts, each re-hashed from the source
  bytes. `receipt_digest` recomputes against the machine-generated production
  receipt for the same task.

## What it excludes

An artifact too large for the per-file budget, a binary artifact, and a payload
that embeds a host-local absolute path are recorded in `excluded` with their
sha256, size, and reason — never truncated. `model/gremlin_mrf.npz` (341 KiB,
over budget) and `plots/coupling_apc.png` (binary) are excluded by policy.

## Capturing on a host

Two environment gotchas when running a capture or the browser acceptance:

- **Stale scratch**: a leftover `/tmp/revocompute-live` (or similar) scratch
  directory from an earlier run can shadow a fresh capture. Remove it before
  capturing rather than reusing it.
- **Submission path**: a locally served stack answers submissions on
  `localhost:8081`, not the default port; point any manual API submission at
  that host:port when exercising the live path.
