# Implementation State — Stage Selection and Artifact Reuse

Status: M1 delivered for PREPARE_ONLY; M2 server-side reuse (MODEL_ONLY) delivered and tested; M3
UI/API presentation and target-host receipt remain. Base `6d726f54` + local commits.

## Completed

- Successor scope restored from #119 and #130's preserved requirements.
- Manifest-declared `execution_modes` (mandatory `full`, ordered stage subsets) in the Task loader.
- `compile_graph(task_type, mode)` selects the same graph's declared subset, records the mode in the
  frozen document and digest, and refuses a subset that drops a required producer.
- Submission accepts `execution_mode`; admission, GPU entitlement, referenced families and placement
  follow the selected stages. Detail API projects `execution_modes`.
- AF2 (`features -> model`) and AF3 (`features -> model`) declare `full` and `prepare_only`.
- Create-Task renders a mode selector when a Task declares more than one mode and submits
  `execution_mode`; the preflight path uses the same field.
- Tests: graph/loader refusal cases, prepare-only submission freezes one node, opens no GPU requirement,
  and places only the selected stage; frontend submission carries the selected mode. 224 Python focused
  tests, 17 frontend tests and `tsc --noEmit` pass.

## Adviser findings applied

- Task identity now includes the execution mode, so prepare_only and full never deduplicate.
- Omitted stages project as `SKIPPED` (`stage_omitted_by_mode`, dependency `skipped`); no StageRun.
- The blanket non-full exemption is gone. Each mode declares `output_contract`: `full` (assess the
  Task's result contract), `stages` (validate the selected stages' required output ports), or `none`
  (no completeness claim, reason `mode_<id>`). AF2/AF3 `prepare_only` uses `stages`; `model_only` will
  use `full`. Regression tests cover missing/present preparation artifacts and model-only missing/
  complete scientific outputs.
- `execution_modes` participates in the live-test `configuration_digest`.
- The top-level `mode` duplicate is gone; the digest-covered `document` is the authority and the worker
  wraps mode resolution in the bounded `execution_graph_changed` refusal.
- `execution_mode` is in the submission schema; mode stage names are fully qualified; ids must be
  lowercase; the owner family is seeded only when a selected stage uses it.

## M2 — MODEL_ONLY with provenance-bound cross-Task reuse

- An execution mode declares `reuse`: consumer port reference -> `{role, type}`. The loader validates
  the port exists on a selected stage, is required, matches the declared type, and that roles are
  unique identifiers. AF2 and AF3 declare `model_only` (`stages: [model]`, `output_contract: full`,
  reuse role `prepared_features`).
- `compile_graph(task_type, mode, reuse)` rewrites a selected consumer's omitted-required-producer
  binding to `reuse:<role>`, records `reuse_inputs` (role/type/port/verified source) in the frozen
  document, and covers all of it with the digest. A declared role without a supplied reference, an
  extra reference, or a source type mismatch is refused.
- Submission accepts a `reuse` JSON object (role -> `{source_task, stage, port, digest}`). Before any
  upload or allocation side effect it validates: caller owns the source Task (403
  `reuse_source_not_owned`), source finished (`reuse_source_not_completed`), latest stage attempt
  COMPLETED with recorded output identity (`reuse_stage_not_completed`), port exists and type matches
  the consumer port (`reuse_port_unknown`/`reuse_type_mismatch`), source task type agrees
  (`reuse_source_incompatible`), and the port's artifact set re-hashes to the supplied digest
  (`reuse_digest_mismatch`). The identity participates in `_derive_task_id` and the frozen graph.
- Dispatch re-verifies the frozen source before the consumer owns an attempt and copies the verified
  bytes into the existing `stage_inputs` layout with the same `stage_inputs.json` document, naming the
  source Task/stage/attempt as provenance. A changed, deleted or superseded source refuses the stage
  as `stage_input_unavailable`/`stage_input_invalid` before an attempt/allocation exists. No producer
  StageRun is opened in the consumer Task; `stage_runs` stays the sole authority.
- The Task Type API projects each mode's `output_contract` and `reuse` list; the live-test
  configuration digest now includes both. Docs: the reuse contract is recorded in
  `docs/developer-guide/composable-execution-architecture.md`.
- The Runner consumes the staged artifact, not its own tree. `common/runtime/stage_inputs.py`
  (`resolve`, `materialize`, `declares`) verifies each staged file's size and sha256 and is mounted by
  both AF bundles. AF2 materializes the single `prepared_features` file to the `features.pkl` path
  `run_alphafold.py --run_stage=model` reads; AF3 materializes the staged `<job>/<job>_data.json`
  layout into its feature directory, which is what `find_processed_json` and `--json_path` expect.
  Both derive the stage marker from the verified bytes. The stage is selected by the document
  declaring the reuse role, so a full-mode model stage — whose document declares the in-graph
  `features` role — keeps using the tree it built. The declared ports suffice: AF2's pinned model
  stage reads only `features.pkl`; AF3 inference with `--run_data_pipeline=false` reads only the
  processed `_data.json`.
- Promotion is still pending: AF2's `run.sh` is a `build_inputs` entry baked into the SIF, so the
  model-stage change needs a SIF rebuild plus a fresh live-test receipt; AF3's `run.sh` and both
  bundles' new `common/runtime/stage_inputs.py` are runtime overlays, so a candidate bundle activation
  carries them. No real MODEL_ONLY target-host acceptance has run.
- Tests: compile digest/rejection cases, named submission refusals (each mutation fails its test),
  reuse-identity task separation, successful submission freeze, successful dispatch materialization
  with no producer StageRun, and changed/deleted/foreign-owner/removed source refusals. 208 focused
  tests pass across the five brief suites; `mkdocs build --strict` passes.

## Next action

- Create-Task: offer the caller's validated reusable artifacts for MODEL_ONLY (PR #138 surface; the
  server projection is ready). Result view: show reused source provenance.
- AF2/AF3 FULL byte-parity and target-host receipt remain release gates.

## Blockers

- Real target-host AF2/AF3 receipt requires maintainer-authorized compute and assets.
