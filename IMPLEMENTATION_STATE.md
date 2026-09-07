# PR6 Implementation State

This file is the current implementation record for PR6. It is not a promise
that every configured Runner is production-ready.

## Current Refactor Checklist

- [x] Enforce production service identity independently of the invoking operator.
- [x] Restore generic fail-closed admission for technically non-READY families.
- [x] Remove committed MkDocs output and keep Pages publication artifact-only.
- [x] Consolidate documentation to one canonical owner per topic.
- [x] Remove implemented families from the adaptation wait list.
- [ ] Run target-host acceptance; local non-browser tests and strict docs build pass.

## Delivered

- Runner-family plugins, task manifests, direct Apptainer definitions, Doctor,
  live-test receipts, and staged SIF promotion are implemented in the owning
  family trees under `docker/runners/`.
- AlphaFold 2 follows the pinned current upstream revision and uses the
  refreshed pipeline patch and `uv`-based dependency installation.
- The MkDocs Material site has one normative published owner per audience:
  `user-guide/`, `operator-guide/`, `runner-guide/`, `developer-guide/`,
  `reference/`, and `agents/`. Legacy root documents remain source references,
  not competing site namespaces.
- Documentation CI runs `mkdocs build --strict`; the main branch publishes the
  generated site through the GitHub Pages artifact/deploy workflow.

## Readiness

Doctor, active SIF provenance, required smoke coverage, and exact target-host
live receipts are evidence for Runner-family readiness. `enabled` or configured
does not imply `READY`. Use the deployment controller's `runner-status` command
to inspect this evidence; task admission remains governed by enabled state,
access policy, and scheduler/runtime behavior.

## Validation record

- `mkdocs build --strict` passes locally.
- Focused Runner contract tests and Doctor checks pass in the repository test
  environment.
- Target-host image rebuilds for the affected families completed, but the
  current target filesystem is read-only, so the EasIFA live-test receipt and
  final prepared deployment snapshot still require target-host write access.
- Deployment/service identity must remain independent of the invoking operator;
  validate the configured service account and Slurm submission identity on the
  target host.

## Target-host acceptance attempt (2026-09-07)

- Exact checkout head verified: `320b0e4882687f5318c0de66c5f58be6e0e75042`.
- Target environment selected: `/repo/REvoDesign/server/.env.production`.
- First required command, `runner-status --all --json`, could not start because
  the target environment filesystem is read-only. `require_env_file()` attempted
  its normal persisted Redis-password handling and failed appending to the env
  file with `OSError: [Errno 30] Read-only file system`.
- Maintenance mode remains preserved. No repository defect was demonstrated and
  no production services were changed. All ordered acceptance steps remain
  blocked pending target-host write access (including service activation and
  live Slurm evidence).

### Corrected environment evidence

- Correct environment is `.env.production.v7-slurm`; configured identity is `revodesign:revodesign`, numeric `129:137`, matching `getent passwd/group`.
- Strict Doctor across all discovered Runner Families passed with zero diagnostics.
- `runner-status --all --json` reports enabled `easifa` as `BUILD_STALE`: its active SIF exists but provenance is stale and no valid live receipt exists. Required next action is `build-sif` followed by live test.
- No rebuild/live test or activation was attempted because required target artifact and deployment writes remain unavailable.
- Promotion was attempted with `prepare --enabled-runners=easifa --build-sif` and failed during family materialization: removing target snapshot `task_context.py` raised `OSError: [Errno 30] Read-only file system`. Maintenance remains enabled.
- After the writable-root grant, preparation completed far enough to invoke
  `live-test --runner easifa`. The live test failed with
  `IDENTITY_FAILURE`: configured identity is `129:137`, but the invoking
  process is `yinying` `1005:50`. No receipt was accepted or promoted.
- After removing the incorrect controller identity gate, EasIFA live-test was
  retried from `yinying` and reached Apptainer validation. It failed with an
  Apptainer UNIX socket `operation not permitted` error in the sandbox; no PASS
  receipt was issued and maintenance remains enabled.

## Open assessment items

Before a Runner leaves the adaptation wait list or is admitted to production,
pin its upstream revision and assess its scientific I/O contract, executable
entry point, dependency/runtime environment, CPU/GPU and scheduler resources,
weights/databases and other assets, license/access constraints,
Docker/Apptainer feasibility, artifact types, storyboard needs, testing
strategy, and runtime-family placement.
