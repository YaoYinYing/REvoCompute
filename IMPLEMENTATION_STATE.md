# Direct SIF and Runner Live Acceptance Implementation State

## Baseline

- Branch: `refactor/direct-sif-live-acceptance` at `b545886` (`origin/main`), with the migration work in the worktree.
- Design source: `TODO.md` (1196 lines), read in full with `LONG_TASK_HANDLING.md` and repository guidance.
- Reference vertical slice: `pssm_gremlin` / runtime family `gremlin`.
- Server deployment boundary remains Docker Compose; scientific execution remains Slurm + Apptainer.

## Completion checklist

### Inventory and design

- [x] Inventory Runner manifests, Dockerfiles, Apptainer definitions, build/freshness/promotion paths, tests, CI, and documentation references.
- [x] Select one real Runner family for the vertical slice before bulk conversion.
- [x] Define the direct-SIF build-input/provenance contract and exact-hash receipt identity.
- [x] Define the family-owned `test.yaml` schema, safe fixture resolver, and report/receipt schemas.

### Reference vertical slice: GREMLIN

- [x] Convert GREMLIN's Dockerfile installation knowledge into authoritative `gremlin.def` with direct upstream bootstrap and `%test`.
- [x] Remove GREMLIN Docker runtime metadata and obsolete Dockerfile.
- [x] Add GREMLIN `test.yaml` and a minimal immutable fixture under `tests/data/` covering its enabled TaskType.
- [x] Build the exact candidate GREMLIN SIF directly and atomically with Apptainer.
- [x] Validate the candidate using real `apptainer inspect` and `apptainer test`.
- [x] Seed a normal isolated TaskRequest through production input validation.
- [x] Execute through PluginManager -> TaskDefinition -> ExecutionPlan -> real Slurm -> real Apptainer candidate SIF.
- [x] Accept through normal task completion, parser, ingestion, and required artifact contracts.
- [x] Emit a durable report and exact-hash/config-bound PASS receipt.
- [x] Prove receipt-gated GREMLIN candidate promotion while preserving the active SIF on failure.

### Production controller and Core integration

- [x] Replace Runner Docker-image builds with direct `apptainer build` candidate builds; retain server Docker/Compose builds.
- [x] Remove `docker_image`, `dockerfile`, Docker image ID, and `docker-daemon` assumptions from Runner runtime loading/validation.
- [x] Replace Docker-image freshness with explicit build-input digest, Apptainer version, definition digest, and SIF SHA256 provenance.
- [x] Implement deterministic `RunnerLiveTestWorker` lifecycle and structured failure categories.
- [x] Implement collections/scopes (`--runner`, `--task`, `--all`, `--collection`) in the deployment controller.
- [x] Integrate candidate artifact selection at a generic ExecutionPlan runtime-artifact boundary.
- [x] Integrate exact-hash live-test receipts and required smoke coverage into prepared promotion/readiness.
- [x] Extend Doctor with static `test.yaml`, TaskType, fixture confinement/existence, and real parameter-schema validation.
- [x] Ensure secrets are excluded from configuration fingerprints, reports, and receipts.

### Bulk Runner migration

- [x] Convert every remaining production family `.def` to a direct upstream bootstrap and authoritative install recipe with useful `%test`.
- [x] Remove every Runner `Dockerfile` and Docker runtime manifest field after consumers migrate.
- [x] Add family-owned `test.yaml` and minimal fixtures; cover every enabled TaskType with required smoke cases.
- [x] Run Doctor across the complete family tree and record resource-blocked live tests as NOT VALIDATED.

### Tests and CI

- [x] Add protocol tests for parser/schema, confinement/symlink escape, TaskType and parameter validation.
- [x] Add build provenance/staleness, atomic candidate staging, exact-hash invalidation, report serialization, and promotion-gate tests.
- [x] Add state-machine success/failure/timeout and real internal architecture integration tests with mocks only at OS/HPC boundaries.
- [x] Add Doctor and ExecutionPlan candidate override integration tests.
- [x] Add architecture tests proving obsolete Runner Docker build dependencies are absent while server Compose remains.
- [x] Remove `DockerRunnerCompatibility`, `make test-docker-compat`, and Runner Docker smoke tests; preserve/clarify server Compose CI.
- [x] Ensure GitHub-hosted CI never issues a live-validation receipt or claims target-cluster readiness.

### Documentation and final acceptance

- [x] Update `CLAUDE.md` and `AGENTS.md` together (the repository symlink keeps them identical).
- [x] Update `docker/runners/README.md`, root `README.md`, `DEPLOYMENT_CONTROL_GUIDE.md`, `OPERATIONS_AND_TASK_ADAPTER_GUIDE.md`, and relevant runtime docs.
- [x] Run focused and full repository tests, shell syntax checks, architecture audit, Doctor, and `git diff --check` (696 non-browser tests pass; Playwright remains environment-limited).
- [x] Render/validate Docker Compose with safe example values and confirm its server topology is unchanged.
- [x] Run available target-host direct build and real Slurm/Apptainer acceptance; record exact evidence or an explicit external blocker without fake PASS.

## Current phase

The migration is under final semantic review; PR merge readiness remains blocked until active-SIF receipt revalidation and multi-task task-scoped Doctor validation pass.

PR: `#4` (`refactor/direct-sif-live-acceptance` -> `main`).

## Current findings

- All 15 production family plugins now declare direct-SIF runtime metadata, family-owned `test.yaml`, and immutable upstream definition bases; no Runner Dockerfiles remain.
- `run/revocompute_ctl/build.py` builds only the server Docker image; `registry.py` stages direct Apptainer candidates and records definition/input/Apptainer/SIF provenance.
- Promotion validates every staged candidate's exact live-test receipt before replacing any active SIF, preventing partial multi-family activation.
- Doctor validates every family declaration, fixture confinement/existence, TaskType coverage, and real parameter schemas; the complete tree is strict-clean.
- CI retains the server Compose gate and protocol tests but never issues target-cluster receipts.
- Existing family runtime configuration remains authoritative for mounts, environment, defaults, resources, and external databases; live tests reuse it.

## Verification performed

- Confirmed the migration branch starts at `b545886` and preserves the server Compose topology.
- Read `TODO.md`, `LONG_TASK_HANDLING.md`, `CLAUDE.md`/`AGENTS.md` instructions.
- Enumerated family files and searched production/tests/docs/CI for old architecture terms.
- Protocol unit tests: 9 passed.
- GREMLIN direct build succeeded with Apptainer 1.4.5; its image test imported the scientific stack and verified required tools.
- GREMLIN live acceptance PASS: Slurm job 4353, 169.486 s case duration, 124 artifacts, and all required alignment/PSSM/coupling contracts passed.
- Candidate SHA256: sha256:66453488024c2e8ebeb1aec201c6dfa45f60fa77205ffe8903ed03d2a47814d9.
- PASS report: /mnt/data/srv/revodesign/server-slurm/images/live-tests/gremlin/1788577830-smoke.json.
- Exact-hash receipt: /mnt/data/srv/revodesign/server-slurm/images/receipts/gremlin.json.
- Plain `python -m pytest` non-browser invocation: 696 passed, 4 skipped; Playwright tests require a browser runtime unavailable in this environment.
- Controller candidate receipt validation fails closed for malformed plans/receipts; standalone controller tests now work without `PYTHONPATH`.
- PR #4 CI: `REvoComputeTests` and `ServerComposeFullStack` both passed, including the GitHub-hosted browser contracts.

## Known blockers

- [ ] Generalize live-test receipt validation to the exact artifact under test so an unchanged active SIF can be revalidated after test/configuration changes without rebuilding.
- [ ] Make task-scoped Doctor collect and validate every sibling task schema and the complete family smoke plan before narrowing task-specific diagnostics.
- The reference vertical slice is validated. Other families remain NOT VALIDATED until their target-host weights, databases, and GPU resources are available; no synthetic PASS is created.

## Next concrete action

Implement and verify the two semantic blockers above, then rerun the focused and full acceptance gates before updating PR #4 readiness.
