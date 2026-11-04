# Implementation State — Proton-PottsMPNN

Status: M0 upstream evidence captured. Base `6d726f54`.

## Completed

- Pinned source HEAD, checkpoint file/size, MIT scope, 30-token v6 vocabulary and CPU-feasible design path
  at `09682abf`.
- Restored successor scope from #123 and #130.

## Next action

- Inventory the checkpoint hash and the exact `PottsMPNNPHEngine` input/output contract; define the Task
  parameters and refusal rules.

## Blockers

- Weights are not provisioned under `/mnt/db/weights/`; target-host acceptance requires maintainer
  authorization.
