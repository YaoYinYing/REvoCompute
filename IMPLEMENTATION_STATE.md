# PR6 Implementation State

This file is the current implementation record for PR6. It is not a promise
that every configured Runner is production-ready.

## Current Refactor Checklist

- [x] Enforce production service identity independently of the invoking operator.
- [x] Restore generic fail-closed admission for technically non-READY families.
- [x] Fail live-test acceptance closed on configured execution UID/GID and every observed Slurm scheduler identity.
- [x] Apply configured scheduler username to receipt/readiness identity matching.
- [x] Replace HTTP submission's deployment-controller readiness resolver with a lightweight shared admission attestation.
- [x] Share candidate server-image preparation across one `live-test --all` invocation.
- [x] Bind live-test validation identity to YAML bytes and fixture content hashes.
- [x] Remove the obsolete legacy live-test executor request protocol.
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
does not imply `READY`. `runner-status` is the operator view of the shared
readiness contract used by production submission admission: new submissions to
a technically non-READY family fail closed before durable task, upload, queue,
or Slurm side effects. Access entitlement and transient scheduler capacity are
separate decisions, and a later readiness change does not cancel tasks already
running.

## Validation record

- `mkdocs build --strict` passes locally.
- Repository non-browser test gate passes: 752 passed, 4 skipped (3 warnings).
- Focused Runner contract tests and Doctor checks pass in the repository test
  environment.
- Target-host acceptance is not yet complete. The Codex sandbox mount namespace
  reports `/mnt/data` as read-only, while the target host's own mount namespace
  reports `/mnt/data` as writable. The sandbox restriction is not evidence that
  the production filesystem is read-only; target-host commands must run in the
  real deployment namespace.
- Deployment/service identity remains independent of the invoking operator.
  The operator orchestrates validation; the candidate worker executes the
  scientific path as the configured service identity and every required Slurm
  job must report the configured scheduler username.

## Target-host acceptance history (2026-09-07)

- Historical acceptance attempt was against `320b0e4882687f5318c0de66c5f58be6e0e75042`.
- Current PR branch head under repair is `6640c68` (working-tree fixes continue from this pushed head).
- Earlier acceptance attempts used an outdated environment selection and a
  restricted Codex mount namespace. They did not establish production-host
  readiness or a PASS receipt. Maintenance remained enabled and services were
  not activated.

### Corrected environment evidence

- Correct environment is `.env.production.v7-slurm`; configured identity is `revodesign:revodesign`, numeric `129:137`, matching `getent passwd/group`.
- Strict Doctor across all discovered Runner Families passed with zero diagnostics.
- `runner-status --all --json` reports enabled `easifa` as `BUILD_STALE`: its active SIF exists but provenance is stale and no valid live receipt exists. Required next action is `build-sif` followed by live test.
- No production PASS receipt has been issued or promoted. The prior
  controller-identity failure was a repository defect: operator identity must
  not be compared with service identity. The corrected design delegates live
  scientific execution to a candidate one-off worker container, where actual
  execution UID/GID and every Slurm scheduler identity are checked. A sandbox
  Apptainer socket error is not production-host evidence.
- Candidate worker repair is implemented and focused worker/controller tests
  pass. A real target-host EasIFA acceptance is still required before prepared
  deployment can proceed. Keep maintenance enabled until that ordered sequence
  produces an exact current receipt.
- Live-test acceptance now rejects mismatched execution UID/GID, missing or
  mixed Slurm scheduler identities, and records the structured identity evidence
  in failed cases. Receipt validation applies the same scheduler identity check
  to every recorded workflow stage.
- The worker validates every request-declared fixture hash against the mounted
  fixture before copying it, and its DB import may create the run root before
  execution; only isolated result/workspace/upload children require fresh
  creation. The old underspecified executor request schema is rejected rather
  than treated as a compatibility path.
- Production admission reads only the controller-published per-runner
  attestation under `SERVER_DIR/readiness/`; controller readiness derivation is
  performed once after deployment, while missing or malformed evidence fails
  closed. The shared `RunnerReadinessStatus` type owns the READY definition for
  both controller and application code. Admin resource-policy updates remove
  the attestation immediately, providing deterministic invalidation without
  request-time SIF hashing or Doctor execution.
- Readiness publication runs through the configured service UID/GID in a
  throwaway server container, creates mode-0755/0644 service-owned storage, and
  atomically swaps a complete staged fleet into place. Restart invalidates
  evidence before runner-tree materialization and all stop/mutate steps;
  publication or finalizer failure removes partial evidence, leaving admission
  fail closed.
- Restart resolves and validates the configured service identity before it
  invalidates admission evidence. Username/group-only deployments therefore
  use their resolved numeric identity for service-context cleanup, while a
  conflicting explicit UID/GID fails without removing the current evidence.
- Final TODO blocker repair is implemented in the working tree: live-test uses
  the canonical server image build, launches a one-off candidate worker, mounts
  the selected Runner contract read-only, streams SIF hashes, captures every
  workflow-stage scheduler identity, and does not require operator membership
  in `RUNNER_GID`. The sandbox retry reached Docker image build but was blocked
  by denied access to `/var/run/docker.sock`; this is not target-host evidence.
- The latest local CI-equivalent non-browser run passed 752 tests with 4
  skips; GitHub Actions status/logs remain externally unavailable from this
  sandbox.

## Target-host acceptance (2026-09-08)

- Production operator is `yinying`; the selected environment is
  `.env.production.v7-slurm`; configured and host-resolved service identity is
  `revodesign` UID 129, GID 137.
- Strict Doctor across all enabled Runner Families passed with zero errors.
- Initial `runner-status --all --json` reported EasIFA `BUILD_STALE` with no
  current receipt. The existing `.next` candidate was verified against its
  current build provenance and SIF hash; no unrelated family was rebuilt.
- The first target-host EasIFA live-test reached candidate server image build,
  then exposed a repository defect: the one-off worker argv omitted the
  `docker compose` executable and began with `-f`. The focused fix is
  `6640c68`; its worker tests pass and the fix was pushed to the existing PR
  branch. The prior run's exact report is retained under the deployment
  `images/live-tests/easifa/` directory.
- GitHub Actions for `6640c68` are green: REvoCompute Tests, Server Compose
  FullStack, and build all passed. A post-fix target-host rerun still requires
  approved Docker/Slurm/Apptainer host access; maintenance remains enabled and
  prepared activation has not been attempted.

## Open assessment items

- Concurrent restart finalization and admin resource updates do not yet share a
  generation or lock. A future resource revision should prevent an older
  in-flight readiness calculation from republishing evidence after an admin
  update invalidates it.

Before a Runner leaves the adaptation wait list or is admitted to production,
pin its upstream revision and assess its scientific I/O contract, executable
entry point, dependency/runtime environment, CPU/GPU and scheduler resources,
weights/databases and other assets, license/access constraints,
Docker/Apptainer feasibility, artifact types, storyboard needs, testing
strategy, and runtime-family placement.
