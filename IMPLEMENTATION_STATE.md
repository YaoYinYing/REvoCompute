# Runner Adaptation Wait List Task State

## Completion checklist

- [x] Inspect existing README, runner/runtime docs, adapter guides, and roadmap documents.
- [x] Add a focused wait-list planning record without implementing or enabling candidates.
- [x] Record all 12 requested upstream projects and distinguish wait-list status from support.
- [x] Mark unverified license, asset, hardware, presentation, and runtime-family facts as TBD/not assessed.
- [x] Link the wait list from the nearest runner documentation index.
- [x] Verify repository links, candidate count, documentation build, and diff cleanliness.

## Verification

- Wait list: `RUNNER_ADAPTATION_WAIT_LIST.md`.
- Runner index link: `docker/runners/README.md`.
- MkDocs wrapper/navigation link: `docs/runners/wait-list.md` and `mkdocs.yml`.
- `mkdocs build --strict`: passed (upstream Material warning only).
- URL/count check: 12 GitHub URLs and 12 `Wait list` entries.
- `git diff --check` and `bash -n run/restart.sh`: passed.
- Server redeployed with `--use-proxy --keep-gateway`; stamp records checkpoint `570b7dd`, `dirty: false`, and all web/worker/Redis/gateway/maintenance services are running.
- The server deployment baseline was established with `--use-proxy --keep-gateway`; the stamp records checkpoint `570b7dd`, `dirty: false`, and the gateway remains in maintenance for the rebuild window.
- AlphaFold 2 (`alphafold`) has a staged SIF at `images/alphafold_v1.sif.next`, but it is now stale because the definition source pin is being advanced from the historical `c77e5d2` to the current local upstream revision `e5c2cdd59c87df41d1f0b9e49c3820a267726766`. The current upstream requirements still specify the 2.3-compatible JAX/NumPy/TensorFlow stack (`jax==0.4.26`, `numpy==1.24.3`, TensorFlow 2.16.1); this must be rebuilt and checked before promotion.
- The AF2 live acceptance submitted to SLURM but was interrupted while still `RUNNING`; its report is `passed: false`, so the staged SIF was not promoted and no authoritative live receipt exists.
- A full 14-family rebuild was started after AF2 staging, then intentionally interrupted to prioritize AF2 recovery. AF3 package installation was incomplete and left no staged AF3 SIF.
- The full fleet rebuild must resume only after AF2 has a complete live acceptance and promotion. The gateway must remain in maintenance until then.

## Scope note

This task intentionally makes no Runner runtime, container, registry, policy, or
server integration changes. Existing broader documentation-system work in the
worktree predates this focused request and should be reviewed or split
separately.
