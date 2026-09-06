# PR6 Implementation State

This file is the current implementation record for PR6. It is not a promise
that every configured Runner is production-ready.

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

## Readiness and production admission

Doctor, active SIF provenance, required smoke coverage, and exact target-host
live receipts are evidence for Runner-family readiness. `enabled` or configured
does not imply `READY`. The deployment publishes a generic fleet-level
readiness snapshot, and production admission rejects NEW tasks for non-READY
families with an actionable reason. Existing and running tasks continue
unaffected when readiness later becomes stale.

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

## Open assessment items

Before a Runner leaves the adaptation wait list or is admitted to production,
pin its upstream revision and assess its scientific I/O contract, executable
entry point, dependency/runtime environment, CPU/GPU and scheduler resources,
weights/databases and other assets, license/access constraints,
Docker/Apptainer feasibility, artifact types, storyboard needs, testing
strategy, and runtime-family placement.
