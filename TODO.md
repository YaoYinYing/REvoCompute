# TODO — Task-scoped Result Contracts and Storyboards

> Planning Draft; remove this root TODO.md before merge. Depends on the baseline/defect inventory in PR #92, but does not need to wait for an exhaustive fleet audit to prove the known Foundry case.

## Architectural invariant

Core understands safe paths, declared logical files, artifact integrity, per-task ownership/authorization and generic renderers; it must **not** recognize fpocket, GREMLIN_LH, RF3 or any other TaskType by name. A Runner family may host multiple TaskTypes that require mutually incompatible expected-output trees and Storyboards. Storyboard assets are deployment-controlled trusted code, not arbitrary task-output JavaScript.

## Baseline

- `revocompute/result_storyboard.py` currently reads `<family>/expected_files.yaml` and `<family>/storyboard/storyboard.yaml`.
- `docker/runners/foundry/` hosts RF3 folding and RFD3/RFD3NA design under one family. `tests/fleet/test_fleet_result_contract_audit.py` explicitly records the RFD3/RFD3NA `*.cif.gz` mismatch.
- Daylight `StoryboardHost` uses a declared trusted entrypoint plus ResultManifest logical IDs and generic View services.

## Tasks

- [ ] Define explicit TaskType-owned locations (e.g. `tasks/<task-id>/expected_files.yaml`, `tasks/<task-id>/storyboard/`) and document the exact precedence and compatibility rule for family-level assets; never infer from result filenames or user-controlled inputs.
- [ ] Resolve the owning Task manifest's trusted path, protect against traversal/symlinks/ambiguous ownership, and keep static asset URL/API authorization and caching correct.
- [ ] Keep runner discovery and manifest finalization deterministic. Projection and replay must use the **same** runtime resolution; no duplicated test-side renderer logic.
- [ ] Support Task-specific required/optional logical IDs and per-task result views without adding TaskType string-switches to Core, frontend, or global plugin registries.
- [ ] Split the Foundry RF3 and RFD3/RFD3NA output declarations and Storyboard assets where justified by actual output examples. RF3 ranked seed/sample CIF, PAE and confidence are not interchangeable with compressed RFD3 design candidates.
- [ ] Correct existing Foundry known-result-tree defects only with observed, pinned output patterns (not guesses or hand-wavy widened wildcards). Preserve raw artifacts when metadata is missing.
- [ ] Ensure an existing fpocket/GREMLIN_LH/family-scoped installation has unchanged routing, output identity, browser behavior and scientific replay.
- [ ] Preserve reader permissions, safe SVG/JS/module policy, view abort/dispose, object-URL cleanup, keyboard/mobile behavior and CSP constraints.
- [ ] Update Example Runner documentation and an example TaskType-scoped declaration, including migration from family-scoped assets.
- [ ] Add parser/path/security tests, contract-audit tests, Manifest replay tests, and focused RF3/RFD3/RFD3NA browser behavior.
- [ ] Apply a correct change-impact classification: changed execution-relevant selectors require new live-test receipts; purely cosmetic labels must not automatically rebuild SIFs.

## Acceptance

- [ ] Two distinct TaskTypes in one runtime family can publish different logical files and different Storyboards without Core model-specific branches.
- [ ] Foundry design structure outputs no longer fall through the shared RF3 filename contract.
- [ ] No relaxing of artifact verification, auth, accepted data types, or Runner output integrity.
- [ ] Existing family-scoped declarations remain supported and exercised by regressions.
- [ ] No bulk beautification of unrelated Runner Storyboards, no Foundry version bump, no production upgrade.
- [ ] Full relevant tests and docs gates pass; exact-head CI and unverified live-host limits disclosed.
- [ ] Root TODO removed before merge.

## Stop conditions

If the output shape cannot be proven against authoritative fixture/upstream code, keep the affected task explicitly incomplete; do not manufacture examples. No merge, deploy or force-push without owner permission.
