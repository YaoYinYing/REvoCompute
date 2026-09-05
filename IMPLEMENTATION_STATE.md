# Runner Readiness and AlphaFold3 Live Acceptance Implementation State

## Resource-bound validation identity follow-up

### Completion checklist

- [x] Bind validation identity to effective public resource values for every required smoke TaskType and workflow stage.
- [x] Resolve resources through the shared production `resolve_submission_resources()` path.
- [x] Reuse one immutable canonical snapshot for receipt identity and live-test task seeding.
- [x] Exclude resource source/override provenance and unrelated management state from the digest.
- [x] Fail readiness closed when current resource values are malformed or unreadable.
- [x] Prove CPU, memory, timeout, partition, GRES, nodes, ntasks, QoS, account, constraint, and exclusivity invalidation.
- [x] Prove restoring equal effective values restores identity equivalence without producing `BUILD_STALE`.
- [x] Cover both AF3 workflow stages generically without family branches in Core/readiness code.
- [x] Issue a new real AF3 receipt under the resource-bound identity and reconfirm target `READY`.
- [x] Run full local/Compose/Doctor gates, push PR #5, and verify its latest GitHub checks.

### Current phase

The resource-bound identity implementation, target revalidation, and delivery verification are complete.

### Verification performed

- Focused resource/readiness/live-worker/protocol suite: 56 passed.
- Controller, process-isolation, Slurm, AF3, Doctor, and architecture suite: 134 passed.
- Target AF3 changed from `READY` to `VALIDATION_STALE` after the identity extension while retaining current active SIF build provenance `sha256:066a314ab32c8d484c0150ead20d950aedeb653dd11f1510fe7e78bd25025e9f`.
- Source/override provenance equivalence and all effective public resource field changes are covered with the real AF3 family contract in isolated tests.
- The new AF3 live acceptance passed through real Slurm jobs 4420 (`alphafold3.features`, CPU) and 4421 (`alphafold3.model`, GPU) against the unchanged active SIF `sha256:61774626af9165bf67891e1c1713d0501037dc585b96bd82596776c73b490163`.
- The resource-bound receipt configuration digest is `sha256:1fbf169415f3cbcd69538d0819e48d3e0ed8296532ed1d1c5145e7ab4e72c559`; its report records the exact public resource snapshots reused for both workflow stages.
- Smoke case `minimal-alphafold3` finished in 99.934 seconds (121.552 seconds total), ingested 18 artifacts, and passed every required output contract.
- PASS report: `/mnt/data/srv/revodesign/server-slurm/images/live-tests/alphafold3/1788610944601259316-smoke.json`; the exact receipt is `/mnt/data/srv/revodesign/server-slurm/images/receipts/alphafold3.json`.
- Target `runner-status --runner alphafold3` returned `READY` with current build provenance, the new validation identity, and 1/1 required smoke coverage.
- Full non-browser coverage gate: 731 passed, 4 skipped, 83% coverage.
- Source-tree strict AF3 Doctor, shell/JavaScript syntax, architecture scan, and `git diff --check` pass.
- The isolated Docker Compose server full-stack smoke passes through API submission, mocked Slurm/Apptainer orchestration, result publication, and cleanup.

### Known blockers

- None. Target resources were available during the preceding AF3 acceptance.

### Next concrete action

Leave PR #5 open and unmerged for review.

---

## Readiness baseline

- Branch: `feat/runner-readiness-status` from merged PR #4 commit `8dbb0e3`.
- Design source: `TODO.md` (1157 lines), read in full with `LONG_TASK_HANDLING.md` and repository guidance.
- Required real vertical slice: `alphafold3` through production Slurm, Apptainer, GPU, parsing, and artifact ingestion.
- Readiness is computed from Doctor, the active SIF, build provenance, current receipt identity, and required smoke coverage.

## Readiness completion checklist

### Generic model and resolver

- [x] Add an immutable generic `RunnerReadiness` model with stable structured reason codes and JSON serialization.
- [x] Derive all readiness states from existing Doctor, active-SIF, build-provenance, live-receipt, and smoke-plan sources.
- [x] Preserve precedence and the distinction between `BUILD_STALE` and `VALIDATION_STALE`.
- [x] Keep authorization, scheduler capacity, scientific execution, automatic repair, and Runner-specific IDs outside readiness.

### Operator interface and automated proof

- [x] Add `runner-status --all` and `runner-status --runner <family>` with concise human output and stable `--json` output.
- [x] Cover Doctor failure, missing SIF, stale build, missing/stale/current receipt, wrong hash, contract-only invalidation, redaction, unknown Runner, and all-family scope.
- [x] Prove status inspection is read-only and candidate SIFs do not determine active readiness.

### AlphaFold3 target-instance acceptance

- [x] Audit AF3 definition, manifests, scripts, outputs, access policy, mounts, resources, build inputs, and minimal smoke case.
- [x] Pass strict Doctor for the current AF3 family.
- [x] Build or reuse a current AF3 direct candidate SIF through the production mechanism and pass `apptainer inspect` / `apptainer test`.
- [x] Run the real production PluginManager -> TaskRequest -> ExecutionPlan -> Slurm -> Apptainer/GPU -> parser/ingestion chain.
- [x] Record job ID, exact SIF SHA256, case ID, final task status, wall time, artifact count/contracts, observations, report, and receipt.
- [x] Activate the exact accepted SIF and prove `runner-status --runner alphafold3` reports `READY`.
- [x] Reconfirm existing GREMLIN readiness and candidate promotion behavior.

### Documentation and delivery

- [x] Document the configured -> built/current -> live-validated -> READY lifecycle and invalidation/actions.
- [x] Run focused tests, full tests/coverage, shell syntax, Compose render/smoke gates, architecture checks, and `git diff --check`.
- [x] Commit coherent checkpoints without unrelated changes, push the branch, and open a PR against `main` without merging.
- [x] Verify latest GitHub CI passes and record final acceptance evidence here.

## Readiness current phase

Complete. PR #5 is open for review and intentionally unmerged.

## Readiness verification performed

- Verified the clean branch starts from merged PR #4 commit `8dbb0e3`.
- Read `TODO.md`, `LONG_TASK_HANDLING.md`, `CLAUDE.md`, and the PR #4 implementation state.
- Focused readiness/live protocol/worker suite: 27 passed.
- Controller/readiness focused suite: 68 passed; targeted CLI argument rerun: 16 passed.
- Real identity fixture proves semantic Task contract and `test.yaml` changes yield `VALIDATION_STALE`, while a declared `run.sh` build-input change yields `BUILD_STALE`.
- Source-tree AF3 strict Doctor reports no diagnostics.
- Target-instance pre-preparation status truthfully reports `NOT_CONFIGURED`: the old materialized AF3 family predates PR #4 and lacks `test.yaml`.
- AF3 audit confirms pinned upstream commit `c0f97eda...`, direct SIF `%test`, read-only weights/database/reduced-BFD mounts, two-stage CPU/GPU execution, restricted policy, and required output contracts.
- The upstream locked JAX stack installs CUDA 12.9 wheels, so the direct base is now the matching CUDA 12.9.1 image; its `%test` asserts the runtime package minor. Target driver 570.124.06 satisfies CUDA 12.x minor compatibility.
- AF3 candidate build and `apptainer test` passed in 879.34 seconds. Exact SIF SHA256: `sha256:61774626af9165bf67891e1c1713d0501037dc585b96bd82596776c73b490163`; build provenance: `sha256:066a314ab32c8d484c0150ead20d950aedeb653dd11f1510fe7e78bd25025e9f`.
- The live run used production resource snapshots for both workflow stages and real Slurm jobs 4418 (`alphafold3.features`, CPU) and 4419 (`alphafold3.model`, GPU). The compute node exposed two NVIDIA A100-PCIE-40GB devices; the model stage requested the normal single-GPU policy.
- Smoke case `minimal-alphafold3` finished normally in 98.357 seconds (119.966 seconds including candidate validation), ingested 18 nonempty artifacts, and passed every required structure/confidence/provenance output contract.
- PASS report: `/mnt/data/srv/revodesign/server-slurm/images/live-tests/alphafold3/1788603459653091332-smoke.json`; exact identity receipt: `/mnt/data/srv/revodesign/server-slurm/images/receipts/alphafold3.json`.
- Receipt-gated promotion activated that exact SIF. Target `runner-status --runner alphafold3 --json` reports Doctor PASS, current build provenance, current receipt, 1/1 required smoke cases, and `READY`.
- The real workflow exposed and fixed three generic production defects: missing per-stage live-test resource snapshots, a non-absolute `bash` executable at Slurm `execve`, and loss of completed workflow job IDs from acceptance evidence. It also established that scalar result fields need explicit nullable semantics for valid single-chain AF3 `iptm: null` output.
- Existing GREMLIN target state was reconfirmed without mutation: Doctor passes and the current active artifact is truthfully `BUILD_STALE` against the newly materialized build inputs. Exact-receipt candidate promotion remains covered by the controller suite.
- Focused AF3/result/live-worker/resource/Slurm suite: 72 passed. Controller full-stack contract subset: 36 passed.
- Full non-browser coverage gate: 719 passed, 4 skipped, 83% coverage. The 12 Playwright cases require Chromium, which is not installed on this target host; they remain part of GitHub CI.
- Shell syntax, JavaScript syntax, architecture scan, and `git diff --check` pass.
- The isolated Docker Compose server full-stack smoke passes through API submission, mocked Slurm/Apptainer orchestration, result publication, and cleanup.
- Commits `bb283a5` and `ca4fcf9` are pushed on `feat/runner-readiness-status`; PR #5 targets `main` and is intentionally unmerged.
- GitHub run `33961905648` passed `REvoComputeTests` (including Chromium browser contracts) and `ServerComposeFullStack` on the PR head.

## Readiness known blockers

- None. Remaining work is local/CI delivery verification.

## Readiness next concrete action

Leave PR #5 unmerged for review.

---

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

Merge-ready pending the final GitHub `REvoComputeTests` rerun after the semantic blocker fixes.

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

- [x] Generalize live-test receipt validation to the exact artifact under test so an unchanged active SIF can be revalidated after test/configuration changes without rebuilding.
- [x] Make task-scoped Doctor collect and validate every sibling task schema and the complete family smoke plan before narrowing task-specific diagnostics.
- The reference vertical slice is validated. Other families remain NOT VALIDATED until their target-host weights, databases, and GPU resources are available; no synthetic PASS is created.

## Next concrete action

Wait for the final GitHub checks, then merge PR #4 if they remain green.
