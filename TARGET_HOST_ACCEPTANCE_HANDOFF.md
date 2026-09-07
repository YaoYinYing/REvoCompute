# Target-host acceptance handoff

Date: 2026-09-07

## Scope

The requested final acceptance is for PR #6 at exact commit
`320b0e4882687f5318c0de66c5f58be6e0e75042`. Production must remain in
maintenance mode until the ordered acceptance sequence succeeds.

## Verified facts

- The correct deployment environment is `.env.production.v7-slurm`.
- Configured service identity is `revodesign:revodesign`, UID/GID `129:137`.
  Host lookups agree:
  `getent passwd revodesign` -> UID 129, primary GID 137; and
  `getent group revodesign` -> GID 137.
- Strict Doctor across all discovered Runner Families passed with zero
  diagnostics.
- `runner-status --all --json` reports the enabled `easifa` family as
  `BUILD_STALE`. Its active SIF exists, but current build provenance does not
  match and no valid live-test receipt exists.
- The configured target paths are under `/mnt/data`, including:
  `/mnt/data/srv/revodesign/server-slurm/server`.
- `/mnt/data` is mounted from `/dev/sdb` with `ro,nosuid,nodev,relatime`.
  Directory modes are permissive, but writes fail with
  `OSError: [Errno 30] Read-only file system`.

## Promotion attempt

The authorized command was attempted:

```bash
REVODESIGN_SERVER_ENV=/repo/REvoCompute/.env.production.v7-slurm \
  bash run/restart.sh prepare --enabled-runners=easifa --build-sif
```

It failed during `materialize_runner_families()` while replacing the target
snapshot (`task_context.py`). No SIF was rebuilt or promoted, no services were
activated, and maintenance mode remains preserved.

## Why the previous deployment may have appeared to work

The materialization path predates PR #6. A previous run may have used an
already-materialized snapshot, skipped rebuild/promotion, used another
`SERVER_DIR`, or run while `/mnt/data` was writable. PR #6 did not cause the
read-only mount.

## Options under discussion

### 1. Repair the durable target filesystem (required for production)

Remount or repair `/mnt/data` so it is writable, then verify with a write probe.
If the remount is refused, inspect kernel/filesystem errors and schedule
offline repair or replacement. This preserves the configured production paths
and is the only option that can produce valid target-host acceptance evidence.

### 2. Use `/tmp` or `tmpfs` for development rehearsal only

A separate non-production env can point `SERVER_DIR` and `CONFIG_DIR` at a
writable temporary directory. This is useful for exercising controller logic,
but it is not production acceptance: state is ephemeral, Slurm nodes may not
share the path, and SIFs/receipts/deploy stamps are not durable evidence.

### 3. Add a future explicit staging-root feature

The controller could support an explicitly marked development staging root, with
production mode rejecting ephemeral paths. This would require a deliberate
design and tests. It must not silently redirect production receipts, SIFs, or
runtime data, because that would validate a different instance.

## Resume sequence after durable storage is writable

1. Verify `findmnt -T /mnt/data` reports `rw` and a `touch`/remove probe works.
2. Run `prepare --enabled-runners=easifa --build-sif`.
3. Run `live-test --runner easifa` and obtain the exact receipt.
4. Re-run `runner-status --all --json` and confirm readiness.
5. Run prepared preflight and `restart --mode=prepared`.
6. Verify web, worker, and maintenance containers run as UID/GID `129:137`.
7. Execute the production-path Slurm smoke job and verify scheduler identity
   `revodesign` plus parser/result publication.
8. Run final readiness checks, then remove maintenance and verify a normal
   submission.

No repository fix is justified by the current evidence; the demonstrated
failure is host filesystem state.
