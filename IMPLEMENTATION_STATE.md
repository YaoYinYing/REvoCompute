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
- No SIF rebuild was performed during redeploy (`sif_sha256s` is empty); direct SIF builds must be invoked separately with `prepare --build-sif --use-proxy`.
- Maintenance-window rebuild attempts (including retry) failed at the first OCI pull with Apptainer `conveyor failed to get: Get https://index.docker.io/v2/: EOF`; no Runner SIF was produced and no live test was run.
- Gateway remains in maintenance; application services are intentionally down pending a successful rebuild.

## Scope note

This task intentionally makes no Runner runtime, container, registry, policy, or
server integration changes. Existing broader documentation-system work in the
worktree predates this focused request and should be reviewed or split
separately.
