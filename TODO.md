# TODO — Foundry 1.0 Compatibility and Controlled Pin Update

> Planning Draft; remove this root TODO.md before merge. Avoid competing with task-scoped Storyboard or parameter-semantics PRs. Base pin in the current REvoCompute manifest: `b02eed6a6bdf8f44d14a80cc36e3da13c9f2291c` (2026-09-01).

## Upstream evidence to verify

The RosettaCommons/foundry `production` branch was observed 14 commits ahead of the REvoCompute pin. Upstream README describes Foundry 1.0 packaging changes, removal of the shared `foundry` Python namespace in favor of model-specific package internals, AtomWorks 3, and unchanged external model CLI/checkpoint paths in many cases. The RF3 README cautions that the inference API and confidence outputs are still being stabilized. **Recheck exact upstream HEAD before selecting a pin.** Foundry RF3 was already available before this new packaging release.

## Tasks

- [ ] Record pinned and target upstream commit SHAs, delta and upstream release/tag; compare `production` only to an explicit immutable target SHA.
- [ ] Review upstream license/code/model-weight usage rights and inherited model-specific components, including separate checkpoint redistribution and commercial restrictions. Do not assume null license metadata grants rights.
- [ ] Produce an upstream compatibility table for RFD3, RFD3NA and RF3: CLI entrypoints, Hydra override spellings, input JSON/CIF semantics, named assets, relevant defaults, outputs, filenames, confidence units, early-stopping behavior and numerical interpretation.
- [ ] Compare upstream requirements/lock changes, AtomWorks compatibility, Python/PyTorch/CUDA/cuEquivariance/optional backend requirements, and source namespace imports; generate reproducible pinned dependency lock and build provenance if implementation proceeds.
- [ ] Verify checkpoint registry identity with SHA256 and operator-managed paths/manifest. Avoid replacing existing checkpoints or pulling weights automatically.
- [ ] Test dependency installation and direct Apptainer/SIF build in a suitable host; do not claim validated SIF from Python-only test.
- [ ] Run command construction/integration smoke for `foundry_rfd3_design`, `foundry_rfd3na_design`, `foundry_rf3_fold`; compare minimal actual input/output and representative edge cases to pinned baseline where feasible.
- [ ] Explicitly cover RF3 early stop (metrics only), PAE, confidence arrays, ranking, multi-sample output; cover compressed RFD3/RFD3NA designs and scientific-specific artifact identities.
- [ ] Keep this PR scoped to pinned source, runtime dependencies/launcher compatibility and verifiable family tests; do not rewrite Core or Daylight components.
- [ ] Produce a gate and rollback plan: candidate build -> fast/static tests -> genuine target-host live-test receipt -> staged promotion; no automatic deployment or model upgrade.
- [ ] Flag operator network, GPU, SIF/cache and licensing dependencies as BLOCKED if unavailable, not success.
- [ ] Coordinate output selector changes with task-scoped contract PR; avoid two branches overwriting the same asset declarations.
- [ ] Do not convert a model upgrade into an unreviewed scientific benchmark claim; capture output/provenance differences, not just run exit code.

## Acceptance

- [ ] Immutable upstream pin and dependency lock verified and documented; current validated pin remains recoverable.
- [ ] Command semantics and intended outputs proven for each model or clearly declared pending actual host execution.
- [ ] No rights violations, missing checkpoint fingerprints, unapproved weight downloads or false readiness reports.
- [ ] Changes to Build and Execution identity trigger correct candidate rebuild/live-test; no production SIF promotion in PR.
- [ ] If technical or licensing acceptance cannot complete, leave upgrade in Draft with a precise blocking report and no unsafe version bump.
- [ ] Remove temporary root TODO.md before merge.

No merge, deploy or force-push without maintainer approval.
