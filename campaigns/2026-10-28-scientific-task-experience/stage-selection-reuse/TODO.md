# TODO — feat(workflow): selectable scientific stages and validated artifact reuse

> **Status:** Design / implementation not yet started. No merge authorization.
> **Baseline when drafted:** `17e80ed1dbd00f1389f3ec7047e5661b85ed52eb` (2026-10-28); revalidate against the exact head at implementation.
> **Scope:** Let scientists perform preparation-only, full, and model-only workflows with typed artifact contracts, explicit MSA/template choices and stable provenance.

## Objective
Let scientists perform preparation-only, full, and model-only workflows with typed artifact contracts, explicit MSA/template choices and stable provenance.

## Grounded starting facts
- Depends on the authoritative StageRun contract from the companion core PR.
- AF2 and AF3 already expose `features`/`model` runner modes; a one-size-fits-all `skip_msa` parameter is insufficient.
- MSA searching, template search, feature assembly, inference and optional relaxation are scientifically distinct operations.
- OpenDDE 1.1.1 currently performs MSA/template/inference within `opendde pred`; separability must be confirmed upstream before promises are made.

## Implementation checklist
- [ ] Define manifest-owned, versioned Stage input/output artifact roles with schema, hashes, provenance and optionality; preserve existing immutable input and ResultManifest boundaries.
- [ ] Support submission intent at minimum FULL, PREPARE_ONLY, MODEL_ONLY, with per-Runner supported-mode declaration; do not expose modes that upstream cannot implement.
- [ ] Determine whether MSA_ONLY and TEMPLATE_PREPARE_ONLY can genuinely be implemented for AF2/AF3, and implement only those supported by authoritative upstream interfaces; distinguish `features` from raw MSA.
- [ ] Allow explicit prior-stage artifacts as model inputs only after server-side validation of structure/sequence identity, chain mapping, model-version compatibility and required format.
- [ ] Design template behavior as `search`, `supplied`, or `none` when supported; reject mismatched or untrusted template paths and external URLs.
- [ ] Support user-supplied MSA with explicit paired/unpaired semantics, chain mapping, empty/no-MSA choices, and deterministic fallback restrictions.
- [ ] Ensure upstream AF3 JSON validator does not silently discard legitimate supported data paths; if paths require transformation, rewrite them only to confined server-owned snapshots without allowing arbitrary filesystem references.
- [ ] Preserve per-stage resource planning, admission checks, GPU accounting, cancellation and permission checks, including jobs resuming from saved artifacts.
- [ ] Create a scientific-intent UI: Preparation only, Full prediction, Model from existing features; show required artifacts/compute before submission.
- [ ] Make reusable artifacts discoverable in the user's authorized result workspace with explicit provenance and confidence that they are complete.
- [ ] Adapt AF2 and AF3 first; study OpenDDE actual `pred`/MSA API and implement only if tested, otherwise leave a bounded documented gap.
- [ ] Keep Mol-1 adoption optional; its `mol msa`, `mol prep`, `mol pred` entrypoints can later reuse this contract.
- [ ] Document unsupported combinations, parameter interactions, and scientific warnings without overloading default forms.

## Test and acceptance checklist
- [ ] AF2/AF3 FULL matches existing scientific outputs for representative pinned fixtures.
- [ ] PREPARE_ONLY emits verified reusable artifacts with no inference/GPU charge where appropriate.
- [ ] MODEL_ONLY accepts valid matching artifacts and refuses wrong sequence, differing schema, malformed template or wrong model version.
- [ ] Supplying MSA/templates skips searches only when declared; no implicit network access.
- [ ] Repeated job and interrupted stage recover idempotently without duplicate allocation/artifact publication.
- [ ] Browser/API tests for available and unavailable modes; exact output/provenance replay and validation receipt tests.

## Explicit non-goals
- Do not invent OpenDDE split commands or claim all models support raw-MSA-only workflows.
- Do not build an unrestricted DAG/pipeline builder; focus on stage selection for concrete Runners.

## Dependency and integration policy
Requires `stage-state-contract` PR merged; coordinates, but does not absorb, Mol-1 Runner PR.

## Review protocol and handoff
- [ ] Read `CLAUDE.md`, `LONG_TASK_HANDLING.md`, the Single-PR Campaign Protocol and this TODO before coding.
- [ ] Appoint one PR owner; preserve an independent Campaign Adviser and strict worktree/write ownership.
- [ ] Create or update `IMPLEMENTATION_STATE.md` alongside this TODO when substantive implementation begins; track progress, exact tests and outstanding blockers.
- [ ] Validate exact head, identify adjacent open/merged PRs and avoid rewriting canonical functionality or introducing parallel sources of truth.
- [ ] Post detailed technical findings and regressions to this PR's review threads; report owner/adviser status to Commander.
- [ ] Include fail-path tests, relevant docs, migration/read-only compatibility where needed, and no unverifiable performance or science claims.
- [ ] Keep PR draft until implementation is complete, exact-head CI/review evidence exists and maintainer accepts the scope.
