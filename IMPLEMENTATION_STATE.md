# Implementation State — RFD4-Proteina

Status: M0 upstream evidence captured. Base `6d726f54`.

## Completed

- Pinned source HEAD, licence, Python/CUDA profile and weight source from upstream at `68058693`.
- Restored successor scope from #122 and #130.

## Next action

- Inspect the pinned `rfd4-generate` CLI and example conditioning inputs; inventory the Hugging Face
  checkpoint files and sizes before defining the first Task contract.

## Blockers

- Model weights are not provisioned under `/mnt/db/weights/`; target-host GPU acceptance requires
  maintainer authorization.
