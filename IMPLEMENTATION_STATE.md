# Docking Runner Suite Implementation State

## Current phase

PR #14 remediation. The fetched PR head and local HEAD both started this
continuation at `637cd7d677590c24c6611907b04474df61b495ce`; `origin/main` was
`41ba8fd860b0c31f46a770caa46428a96d73b125`. The existing PR branch is checked
out and the pre-remediation checks were green.

Scheduler inspection used both `squeue` and `scontrol show job` as required.
The production accelerator is occupied by a clearly long-running molecular
dynamics workload, so GPU live acceptance is deferred for this delivery with
no further polling.

## Completion checklist

- [x] Read `TODO.md`, repository guidance, and `LONG_TASK_HANDLING.md`.
- [x] Fetch and confirm the current PR #14 head, review findings, and CI state.
- [x] Repair receptor/ligand cardinality through the API and wrapper contracts.
- [x] Replace Gnina ligand autoboxing with an explicit bounded Cartesian box.
- [x] Restore DiffDock's retained ESM-2 import while excluding structure prediction.
- [x] Add and test Runner-owned normalized `scores.csv` and `summary.json` artifacts.
- [x] Rebuild the exact AutoDock Vina candidate SIF and pass its embedded `%test` gate.
- [x] Defer final GPU candidate builds and live acceptance to follow-up work without
  weakening readiness or production enablement.
- [x] Run final-candidate AutoDock Vina target-host CPU acceptance and issue an exact receipt.
- [x] Record GPU live acceptance as deferred with no receipt or readiness exception.
- [ ] Update PR #14, pass exact-head CI, merge, and redeploy the preserved production fleet plus Vina only.
- [x] Create `feat/docking-runner-suite` from the latest `origin/main`.
- [x] Record pinned upstream source, license, dependency, hardware, input, output,
  weight, and resource-limit decisions for all four families.
- [x] Add a complete AutoDock Vina family: plugin manifest, Task contract, direct
  Apptainer definition, wrapper, Runner configuration, citations, result
  presentation, reproducible smoke plan, and focused tests.
- [x] Add a complete AutoDock-GPU family with AutoGrid map preparation and
  high-throughput ligand handling.
- [x] Add a complete Gnina family with GPU search and selectable CNN
  scoring/rescoring behavior.
- [x] Add a complete DiffDock family that accepts only an explicit protein
  structure plus ligand structure and never accepts or folds protein sequence.
- [x] Keep all docking vocabulary in the owning `task.yaml` and resolved Runner
  inputs; add no central TaskType special cases or duplicated parameter defaults.
- [x] Add immutable, minimal docking fixtures and Runner contract tests covering
  manifests, schemas, wrappers, artifacts, citations, runtime pins, and the
  structure-only DiffDock invariant.
- [x] Reproduce and fix the create-task seed dice responsiveness defect, with a
  focused browser or JavaScript regression test.
- [x] Document the four Runner contracts, setup/assets, licensing, operational
  constraints, and production validation evidence.
- [x] Pass focused docking, TaskType discovery, architecture, wrapper, readiness,
  and seed-control tests.
- [x] Pass the effective `make test` selections, shell syntax checks, Compose rendering,
  and `git diff --check` against the final tree.
- [x] Build the Vina candidate SIF directly with Apptainer on the target host and
  pass its `%test` gate; leave GPU candidate completion for the follow-up.
- [x] Run the required Vina smoke case through the public API, Slurm, and
  Apptainer; verify status, required artifacts, and the exact readiness receipt.
- [x] Record the available Vina live-test duration and resource policy; defer GPU
  utilization evidence until each later target-host acceptance test.
- [ ] Commit coherent checkpoints without unrelated work, push the branch, and
  open a PR titled `feat: add molecular docking runner suite`.
- [ ] Confirm current-head PR checks are green and merge the accepted PR before deployment.

## Verification performed

- `git fetch origin main`: fetched successfully.
- `HEAD`, `origin/main`, and `FETCH_HEAD` all resolved to
  `41ba8fd860b0c31f46a770caa46428a96d73b125` before branch creation.
- Strict Doctor reported no diagnostics for all four new Runner families.
- `tests/test_docking_runners.py`, TaskType discovery, Runner architecture,
  static wrapper, and live-test protocol gates pass.
- The non-browser repository suite passed: 937 passed, 4 skipped, 32 deselected.
  Runtime definitions changed afterward, so this broad gate will run again on
  the final tree.
- The focused real-Chromium seed-control regression passes at a 390px viewport.
- DOI resolution and checked-in BibTeX verification pass for all four families.
- Final AutoDock Vina candidate SIF and embedded `%test` pass. Its target-host
  live test passed through API, worker, Slurm, and Apptainer in 31.498 seconds;
  all required output-contract checks passed. The exact receipt binds SIF
  `sha256:deb23d9362fce121f919c87d773314d425a00d3dfd00b6eff24a5d55e3333f39`
  to the current build provenance, configuration, and test-definition digests.
- Final focused docking tests pass: 9 passed. Full browser contracts pass:
  32 passed. Shell/JavaScript syntax, strict MkDocs, both Compose renders,
  citation verification, and `git diff --check` pass.
- Non-browser coverage reached 83% with 943 passed and 4 skipped. The three
  established coverage-instrumented restart subprocess cases exceeded their
  90-second harness limit; the exact three cases pass without coverage in
  153.09 seconds.

## Known failures and blockers

- AutoDock-GPU, Gnina, and DiffDock final candidate completion and target-host
  GPU acceptance are follow-up work. Their live tests are intentionally not
  part of this delivery while the production accelerator is occupied.
- No GPU-family receipt exists in the production evidence store, and none of
  the three GPU docking families is present in `ENABLED_TASKRUNNERS`.
- Official DiffDock-L v1.1 model assets are provisioned under
  `/mnt/db/weights/revocompute/diffdock`, and their archive and extracted-file
  checksums pass. The existing ESM2-650M cache is mounted separately read-only
  and verified by its own manifest.
- The configured proxy initially returned HTTP 503 errors. After recovery, HTTPS
  mirrors plus package-manager retries have been reliable.
- AutoDock-GPU, Gnina, and DiffDock GPU live acceptance is deferred because the
  production accelerator is occupied by a long-running user workload. No live
  receipt or readiness exception will be created for these families.

## Next concrete action

Inspect all exact identities and the absence of GPU receipts, then commit,
push, pass exact-head CI, merge, and redeploy the preserved production fleet
with AutoDock Vina as the only newly enabled docking Runner.
