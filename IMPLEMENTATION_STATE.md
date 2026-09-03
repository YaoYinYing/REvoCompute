# Implementation State

This ledger was created from the current repository state on 2026-09-03.

## Completion checklist

- [x] Materialize enabled runner-family trees into each server instance.
- [x] Select plugins by manifest `id`, independent of directory name.
- [x] Normalize and validate family-relative manifest paths.
- [ ] Preserve distributed task semantics and retire the central task registry.
- [x] Keep JSON Schema validation and task-owned UI metadata.
- [x] Keep JAAG configuration contribution-owned.
- [x] Contribute AlphaFold3 access policy from its runner family.
- [x] Make PluginManager/ContributionRegistry authoritative in production.
- [x] Track contribution ownership without mutating contributed values.
- [x] Keep runner runtime metadata family-owned.
- [x] Route production execution through ExecutionPlan, Slurm, and Apptainer.
- [x] Rewrite stale Docker full-stack assumptions.
- [x] Make Doctor validate the production plugin graph and filters.
- [x] Add real and synthetic end-to-end architecture coverage.
- [ ] Remove obsolete centralized files and compatibility paths after preservation checks.
- [ ] Run focused and complete acceptance gates.

## Current phase

Plugin discovery/materialization and generic plugin-contributed access policies are implemented. The broader registry/execution migration remains incomplete.

## Evidence and known gaps

- `revocompute/plugins/__init__.py` now stores immutable `ContributionEntry` ownership metadata and discovers by manifest identity.
- `run/revocompute_ctl/steps.py` materializes enabled family trees into `SERVER_DIR/docker/runners` during setup/build.
- Distributed task manifests now load workspace, result-view, and citation semantics; broader preservation coverage is still needed.
- `config/task_types.yaml` and `config/access_policies/alphafold3_noncommercial.yaml` remain present.
- AlphaFold3 now contributes `policies/noncommercial.yaml`; generic discovery registers it without Core-specific knowledge.
- `ExecutionBuilder` creates scheduler-neutral plans and `SlurmJob` consumes the plan for Apptainer image/arguments; 38 focused SLURM/plan tests pass.
- Doctor validates plugin API version and meaningful `--runner`/`--task` filters; 50 focused plugin/Doctor/execution tests pass.
- Doctor fixtures now use distributed plugin manifests; `tests/test_doctor.py` passes 3/3 and no longer treats `task_types.yaml` as a valid setup.
- Deployment validation now prefers the materialized `SERVER_DIR/docker/runners` plugin tree and validates runtime assets by manifest ID; focused restart validation passes.
- Deployment validation and prepared preflight now use plugin-owned runtime/policy metadata without falling back to `task_types.yaml`; central task semantics still require preservation audit.
- Deployment executor selection no longer reads task metadata; `detect_executor` uses server-owned Slurm configuration and CLI tests pass.
- Deployment validation no longer falls back to `task_types.yaml`; runtime assets and family policy documents resolve from plugin roots, with family roots retained for SLURM image builds.
- Architecture gates cover zero-runner startup, renamed plugin IDs, invalid manifests/schemas, unsafe paths, filters, missing assets, runner removal, and immutable ownership; combined focused suite passes 64 tests.
- Schema-only task manifests now derive UI `TaskParam` metadata while JSON Schema remains validation authority; extension defaults and constraints are covered by 47 focused tests.
- JAAG target configuration is declared and JSON-Schema validated by the contributing plugin/family; invalid and valid option tests pass.
- GREMLIN full-stack harness now materializes `docker/runners/pssm_gremlin` into the server instance and no longer rewrites `task_types.yaml` or uses the Docker executor override.
- Checkpoint commits `311e7cb`, `1f534db`, `0adcdcc`, and `a7e56d7` are pushed to `origin/refactor-plugin-kernel-doctor`.
- ExecutionPlan and Doctor abstractions exist; production integration and complete graph validation require verification.

## Next action

Next: migrate deployment validation and task consumers away from `task_types.yaml`, retaining it only for preservation tests until coverage is complete.
