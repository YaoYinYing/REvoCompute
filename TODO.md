# Operator Host Executor — deployment correctness

**Status:** PLANNED / DESIGN BRANCH ONLY. Screenshot-derived field report; no production diagnosis or tests have been executed by this PR.
**Priority:** urgent functional unblock. **Base:** main at `14ea7441fd1aeeccb2abf37a217c1bbf42ab0e6e`.
**Ownership:** `revocompute/operator_executor.py`, `revocompute/runner_host.py`, host/deployment controller, operator tests/docs as needed. Avoid writing `frontend/src/features/admin/fleet/FleetAdmin.ts`; that belongs to the resource/admin PR.
**Symptoms:** Admin /compute/runner_fleet reports “Operator executor unavailable … mutating actions are disabled”; ~30 families appear BUILD_STALE after deployment.

## R0 — evidence before changes
- [ ] Read CLAUDE.md, LONG_TASK_HANDLING.md, docs/operator-guide/{fleet-operations,deployment-control,runner-readiness}.md, `operator_executor.resolve_executor`, `runner_readiness`, `run/restart.sh`, Compose mount/runtime boundaries.
- [ ] Inspect *actual target deployment* identity and permissions, host.server_root(), `run/restart.sh` visibility, `REVODESIGN_SERVER_ENV` (path only; never reveal values), `.env.production`, Python executable, Compose mounts, executable identity. Capture an independently reproducible `availability(host)` diagnostic.
- [ ] Distinguish “executor missing”, “executor cannot run”, “runner image fingerprint stale”, “readiness proof unavailable”, “resource capacity unavailable” and access state; gather truthful evidence and timestamps.
- [ ] Check whether controller path is inside container vs on host. **Do not** blindly mount host filesystem/socket, inject Docker socket, add unrestricted command execution, or route privileged shell through the Web container.
- [ ] Compare `restart.sh runner-status --json` with `GET /compute/api/auth/admin/runners` for at least one enabled and one stale family; collect non-secret fingerprint/provenance metadata.
- [ ] Verify whether stale states originate from changed build inputs, image version, mounts, or host-specific evidence. Do not mass rebuild SIFs or overwrite READY receipts.

## Design & implementation
- [ ] Select the least-privileged *typed*, bounded executor boundary that works on target host, preserving existing Host Operator semantics and fail-closed mode. Escalate if it would change privilege/trust boundary.
- [ ] Preserve controller CLI as break-glass pathway and its stronger operator-only privileges; Web never exposes arbitrary argv, path or shell.
- [ ] Make an unavailable reason actionable without leaking absolute paths, secrets, or sensitive environment.
- [ ] Prevent optimistic READY, mutation when executor unavailable, automatic repeated retries, uncontrolled builds, or fake success.
- [ ] Implement deterministic health/readiness evidence and an operator diagnostic procedure which does not require production workload mutation.
- [ ] Add focused process/permission-path and degraded-mode tests with real process/API consumers; avoid static-file assertions.

## Acceptance & safety
- [ ] Test missing script, missing env file, nested/unsafe path, subprocess unavailable, stale plan, permissions, and working valid controller; validation of secrets stays path-only.
- [ ] Validate both API and CLI derived readiness report identical evidence and do not rewrite historical READY state when executor is absent.
- [ ] If target host cannot be tested, explicitly mark HOST-UNVERIFIED; no false claim of recovery.
- [ ] Run targeted tests, applicable `make test`, Compose/shell validation and CI; system-boundary independent review on exact head.
- [ ] No production SIF rebuild/Slurm mutation/restart without operator safety window and authorization.
- [ ] Remove this temporary TODO and any local work logs, screenshots or credentials from final diff; retain only durable focused operator docs and tested code.
