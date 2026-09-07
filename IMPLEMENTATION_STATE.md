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
does not imply `READY`. `runner-status` is the operator view of the shared
readiness contract used by production submission admission: new submissions to
a technically non-READY family fail closed before durable task, upload, queue,
or Slurm side effects. Access entitlement and transient scheduler capacity are
separate decisions, and a later readiness change does not cancel tasks already
running.

## Validation record

- `mkdocs build --strict` passes locally.
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
- Current PR branch head under repair is `c481e43`.
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

## Open assessment items

Before a Runner leaves the adaptation wait list or is admitted to production,
pin its upstream revision and assess its scientific I/O contract, executable
entry point, dependency/runtime environment, CPU/GPU and scheduler resources,
weights/databases and other assets, license/access constraints,
Docker/Apptainer feasibility, artifact types, storyboard needs, testing
strategy, and runtime-family placement.
