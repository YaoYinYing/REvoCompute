# Implementation State — Stage Selection and Artifact Reuse

Status: M1 delivered for PREPARE_ONLY; M2/M3 and UI remain. Base `6d726f54` + local commits.

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

## Next action

- Result/detail presentation of the selected mode and omission reasons, then MODEL_ONLY with
  provenance-bound cross-Task artifact reuse (M2).

## Blockers

- Real target-host AF2/AF3 receipt requires maintainer-authorized compute and assets.
