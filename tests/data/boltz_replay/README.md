# Boltz replay bundle: not checked in

A bundle was assembled from the production artifact API for task
`b17fe439872ad10288534606270325e8` (type `boltz_predict`, deploy `57c8114`, SIF
sha256 `afeb5646...`), but it cannot be committed: the published result includes
`boltz-model-assets.sha256`, whose bytes embedded a host-local provisioning root.
`capture_replay_bundle` refuses a payload that carries a host path, and
`tests/frontend_fixtures/replay_bundle.py` re-checks that on load.

The runner-side cause is fixed in this branch's history (`8082c1e`: the manifest
now names assets relative to the mount and verification runs from the asset
root). The already-published bytes predate that fix and cannot be re-captured
without a new production Boltz run, so `boltz_predict` has no replay-backed
browser acceptance here. It stays at `BLOCKED_EVIDENCE`; no synthetic stand-in is
substituted and `tests/fleet/browser/test_playwright_replay_structure_tasks.py`
does not list it.

To unblock: run one minimal production Boltz task on the fixed runner, then
capture it with `capture_replay_bundle(..., storyboard_dirs=["docker/runners"])`
and write it here as `tests/data/boltz_replay/<name>_production_<task8>.json`.
