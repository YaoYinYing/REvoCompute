# Implementation State

This ledger was created from the current repository state on 2026-09-03.

## Completion checklist

- [ ] Materialize enabled runner-family trees into each server instance.
- [x] Select plugins by manifest `id`, independent of directory name.
- [x] Normalize and validate family-relative manifest paths.
- [ ] Preserve distributed task semantics and retire the central task registry.
- [ ] Keep JSON Schema validation and task-owned UI metadata.
- [ ] Keep JAAG configuration contribution-owned.
- [ ] Contribute AlphaFold3 access policy from its runner family.
- [x] Make PluginManager/ContributionRegistry authoritative in production.
- [x] Track contribution ownership without mutating contributed values.
- [ ] Keep runner runtime metadata family-owned.
- [ ] Route production execution through ExecutionPlan, Slurm, and Apptainer.
- [ ] Rewrite stale Docker full-stack assumptions.
- [x] Make Doctor validate the production plugin graph and filters.
- [ ] Add real and synthetic end-to-end architecture coverage.
- [ ] Remove obsolete centralized files and compatibility paths after preservation checks.
- [ ] Run focused and complete acceptance gates.

## Current phase

Initial audit complete; plugin discovery, path semantics, ownership bookkeeping, and runner materialization are implemented. The broader registry/policy/execution migration remains incomplete.

## Evidence and known gaps

- `revocompute/plugins/__init__.py` now stores immutable `ContributionEntry` ownership metadata and discovers by manifest identity.
- `run/revocompute_ctl/steps.py` materializes enabled family trees into `SERVER_DIR/docker/runners` during setup/build.
- Distributed task manifests now load workspace, result-view, and citation semantics; broader preservation coverage is still needed.
- `config/task_types.yaml` and `config/access_policies/alphafold3_noncommercial.yaml` remain present.
- ExecutionPlan and Doctor abstractions exist; production integration and complete graph validation require verification.

## Next action

Next: migrate access-policy contributions and retire the central registry only after semantic-preservation verification.
