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
- Tests: graph/loader refusal cases, prepare-only submission freezes one node, opens no GPU requirement,
  and places only the selected stage. 220 focused tests pass.

## Next action

- Add the create-task mode selector and result/detail presentation, then implement MODEL_ONLY with
  provenance-bound cross-Task artifact reuse (M2).

## Blockers

- Real target-host AF2/AF3 receipt requires maintainer-authorized compute and assets.
