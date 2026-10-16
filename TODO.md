# TODO — Runner Scientific Contract Audit

> Planning-only Draft. **Remove this temporary root TODO.md before merge.**
> Base: post-#88 main. First reconcile with main if PR #87 lands. No implementation is claimed at creation.

## Purpose

Build one reproducible, evidence-backed inventory of every discovered Runner TaskType. The Core must remain method-agnostic; the Runner must own scientific names, accepted inputs, parameters, execution mapping, output identity and scientific presentation. Audit first; do not refactor the fleet as part of this PR.

## Known starting evidence — verify against exact new base

- `tests/fleet/test_fleet_result_contract_audit.py` reports **56** TaskTypes, **20** covered by declared result trees, **36** unaudited for required sources, and concrete mismatch in `foundry_rfd3_design` and `foundry_rfd3na_design`.
- Foundry RFD3NA `num_recycles` is user-facing but `foundry/launch.py` does not forward it; confirm upstream before classifying.
- Existing `test.yaml`/fixtures and scientific replay are NOT equivalent to real published output or target-host execution.
- Read `CLAUDE.md`, `AGENTS.md`, Runner Guide, architecture boundary, and the existing `revocompute/result_audit.py`. Never create a second semantic registry.

## Tasks

- [ ] Record exact current base SHA and discover all TaskTypes dynamically through the production loader; do not hard-code 56.
- [ ] Establish a machine-readable, reproducible audit output and concise human-facing table with one row per TaskType: family, runtime/upstream pin, test coverage, license/weights and operator constraints.
- [ ] For every named input role, compare `task.yaml`/input workspace, server validator, actual launcher, allowed file types/cardinality, and canonical upstream examples. Mark unsupported evidence **unknown**, not passed.
- [ ] For every user-facing parameter, trace JSON Schema name/type/default/range -> normalized submitted value -> runner forwarding -> upstream CLI/Hydra/API option. Classify honored, conditionally honored, ignored, wrongly described, hidden-but-supported, or unverified. Record source lines.
- [ ] For every output, inspect `result_workspace.views`, declared required sources, `expected_files.yaml`, normalizer/parser, `storyboard.yaml`, recorded scientific fixtures, ResultManifest and artifact projection. Treat legitimate static undecidability separately from a proven mismatch.
- [ ] Inventory trusted Storyboard coverage by **TaskType**, noting shared-family modules; distinguish generic views from custom composition. No demand that every Task have custom JS.
- [ ] Inventory demo-ready named inputs, `test.yaml` smoke fixtures, and authentic output/replay samples. Flag licenses, byte budgets and reproducibility gaps.
- [ ] Classify each family as validated via static contract, fake/mock runner, real CLI, real model execution, or target-host Slurm/Apptainer. These levels are never interchangeable.
- [ ] Enumerate concrete defects and unknowns, separate them from CI/host limitations. Prioritize by scientific impact, broken user controls, failure to open outputs, missing provenance, and potential silent wrong results.
- [ ] Add or refine **generic** audit assertions where they eliminate manual guesswork, without introducing Runner names into Core logic.
- [ ] Publish a compact actionable inventory/report with links to each source of truth and proposed follow-on PR ownership. Remove temporary reports/screenshots not meant for users.

## Acceptance

- [ ] Every discovered TaskType accounted for (no silently omitted families).
- [ ] Coverage states explicitly differentiate covered / unaudited / known-defective / runtime-verified.
- [ ] Foundry design output defect and RFD3NA parameter discrepancy appear until genuinely resolved.
- [ ] No task science, command, UI, SIF pin, authorization or default behavior changes in this audit PR.
- [ ] The audit can be rerun against another fleet revision without manually rewriting a 56-item registry.
- [ ] Relevant tests and strict docs checks run; exact-head evidence reported.
- [ ] Temporary TODO removed before review-ready/merge.

## Guardrails

No sub-Campaign, no unlimited downstream fixes, no force-push/merge/deploy, no screenshot commits. Preserve server/runtime responsibility boundary. Stop at READY_FOR_FINAL_REVIEW.
