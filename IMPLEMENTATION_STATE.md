# Ownership inversion implementation state

## Source inventory and migration ledger

| Old location | Semantic purpose | New owner | Destination | Status / evidence |
|---|---|---|---|---|
| `job_executor` | Server scheduler binding | Server infrastructure | `ComputeConfig.job_executor` / `REVOCOMPUTE_JOB_EXECUTOR` | Migrated; Slurm only |
| `container_runtime` | Server isolation binding | Server infrastructure | `ComputeConfig.container_runtime` / `REVOCOMPUTE_CONTAINER_RUNTIME` | Migrated; Apptainer only |
| `runtime_families.<family>.{docker_image,slurm_image,entrypoint,dockerfile,definition}` (14 families) | Shared runtime identity | Each runner family | `docker/runners/<family>/plugin.yaml` (`gremlin` maps to `pssm_gremlin/`) | Conversion in progress |
| `runtime_families.alphafold3.access_policy` | Restricted runner access | AlphaFold3 family + server policy service | AlphaFold3 manifest policy reference | In progress |
| `categories.{evolution,structure,fitness,function,inverse_folding,design}` | UI grouping labels/order/descriptions | Presentation contribution | Opaque task category plus distributed presentation metadata | Classified; pending |
| `workspace_templates.{file,fasta,structure}` | Generic upload/parameter/review compositions | Generic workspace protocol | Core generic workspace defaults or explicit task declarations | Classified; pending verification |
| `task_types.<task>.runtime_family` | Family ownership link | Task/family manifests | Family task reference; ownership implied by locality | In progress |
| `task_types.<task>.{display_name,summary,use_when,input_summary,output_summary,considerations,category}` | Scientific metadata | Each task | `tasks/<task>/task.yaml` | In progress |
| `task_types.<task>.{input_extension,input_extensions,primary_input_extensions,input_label,allow_multiple_inputs,min_input_files,max_input_files}` | Input contract | Each task | Task manifest input contract | In progress |
| `task_types.<task>.params` | Validation/default/help/UI metadata | Each task | Canonical Draft 2020-12 `schema` + `parameter_ui` | In progress |
| `task_types.<task>.{runner_args,gpus,requires_network,stage_markers,workflow}` | Plan/stages/resource hints | Each task | Task execution declaration | In progress |
| `task_types.<task>.input_workspace` | Input composition | Each task | Task manifest `input_workspace` | In progress |
| `task_types.<task>.result_workspace` | Output/presentation | Each task | Task manifest output/storyboard declarations | In progress |
| `task_types.<task>.{citation_dois,citation_bibtex}` | Scientific citations | Each task | Task manifest citations | In progress |

### Complete family disposition

`gremlin`, `pythia_ddg`, `esm`, `esmdynamic`, `opendde`, `mpnn`, `prime`, `placer-rfdiffusion`, `bioemu`, `easifa`, `freebindcraft`, `alphafold`, `alphafold3`, and `colabfold_af2` migrate to their existing `docker/runners/` directory.

### Complete task disposition

`gremlin`, `pythia_ddg`, `esm_msa`, `esm_extract`, `esm_1v`, `esm_if1`, `esmdynamic`, `opendde`, `hypermpnn`, `proteinmpnn`, `solublempnn`, `ligandmpnn`, `lasermpnn`, `thermompnn`, `prime`, `prime_dms`, `rfdiffusion`, `placer`, `bioemu`, `easifa`, `freebindcraft`, `alphafold`, `alphafold3`, and `colabfold_af2` migrate to `docker/runners/<family>/tasks/<task>/task.yaml`.

## Acceptance checklist

- [x] All 14 family manifests preserve relevant shared runtime metadata (generated from the complete inventory; family `runner.yaml` preserves deployment mounts/env).
- [x] All 24 task manifests preserve metadata and canonical schemas (generated conversion; discovery verifies 24 tasks).
- [ ] Workspace/input/output/storyboard/citation information is preserved and task-owned.
- [ ] JAAG owns and validates its target vocabulary.
- [ ] Production and doctor share PluginManager-backed task contributions.
- [ ] Tasks produce `ExecutionPlan`; Slurm/Apptainer consumes it.
- [x] Zero-runner discovery and doctor succeed.
- [ ] Synthetic runner validates/submits/builds a plan without Core changes.
- [ ] AlphaFold3 is verified end-to-end as the real reference.
- [ ] Old-vs-new preservation gate proves task set and important metadata (task-set converter exists; automated comparison still pending).
- [ ] Remove `load_registry`, central registries/schema reconstruction, and Docker-as-executor.
- [x] `ComputeConfig.task_types_config` is absent.
- [ ] Retire `config/task_types.yaml` only after ledger verification.
- [ ] Architecture searches and all required test/doctor gates pass.

## Current evidence

- Focused plugin/discovery/execution-plan/CLI tests: 17 passed.
- Production startup no longer calls `load_registry`.
- Zero-runner and synthetic filesystem discovery tests are in `tests/test_plugin_discovery.py`.

## Next action

Convert all family/task declarations, add semantic preservation verification, then switch PluginManager contributions and retire the restored migration source.
