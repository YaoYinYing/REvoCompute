# TODO — Sequence-first AlphaFold2 / AlphaFold3 prediction

> Temporary PR-local execution plan. The PR body owns the goal, the Runner Task definitions own published scientific contracts, and the code/tests own behavior. Retire this file before final source acceptance. This PR begins with **no product implementation**.

## Problem and definition of success

The current Create Task catalog offers `alphafold` (AlphaFold2) as a FASTA-input, **MSA-searching** monomer/multimer method, and `alphafold3` as an uploaded-JSON method. The former does not expose MSA-free prediction; the latter already accepts upstream JSON with `unpairedMsa: ""` and `pairedMsa: ""`, but has no sequence-first UI. Users need **explicit, discoverable single-sequence (no-MSA) entries for AF2 and AF3**.

**Single chain is not single sequence:** `model_preset=monomer` alone does not disable AlphaFold2's MSA/database pipeline. Never label that existing path as MSA-free. An executable single-sequence mode means query-only evolutionary input (MSA depth one), no sequence homology search, and no template lookup/use. It is an inference mode, not a claim of equivalent predictive accuracy.

## Discovery (first checkpoint, read current tree, not this plan as authority)

- [ ] Inspect the current `main`, both family `plugin.yaml` and `task.yaml` files, `run.sh`, AF2 `staged_pipeline.patch`, upstream-pinned scientific APIs, Task catalog projection, Create Task workspace plugins, preflight/admission and `test.yaml`. Note the precise current source revision and any overlapping PR.
- [ ] Verify whether the pinned official AlphaFold2 pipeline can construct valid query-only model features without MSA/template searches using supported APIs. Identify the exact feature schema and one real monomer/monomer-pTM execution path. Treat this as a scientific feasibility check, not an assumption that changing `model_preset` or `db_preset` is enough.
- [ ] Confirm AF3 upstream behavior of empty inline `unpairedMsa`/`pairedMsa` and empty `templates` on a real current `alphafold3` image, including processing and inference under offline/no-search conditions. Do not infer success from JSON schema validation alone.
- [ ] Establish the smallest contract/UI mechanism that makes **two distinct, searchable Create Task entries** appear: prefer Runner-owned TaskTypes and existing `files` / `sequence` workspace capabilities over frontend/Server name checks or another plugin framework. Preserve the existing AF2 MSA-assisted and AF3 JSON interfaces.

## Intended user experience and scientific contracts

- [ ] Expose a discoverable AF2 entry clearly identified as **AlphaFold2 — Single sequence (no MSA)**, supporting one pasted protein sequence or one single-record FASTA. Limit to a scientifically supported monomer preset; reject multimer and multi-record input unless verified separately. No MSA/template search and no silent fallback to ordinary AF2.
- [ ] Expose an AF3 entry clearly identified as **AlphaFold3 — Single sequence (no MSA)**, with one pasted protein sequence or single-record FASTA. No manual JSON composition is required. Convert to upstream AF3 JSON through a **family-owned, deterministic, validated** pathway with one protein chain, empty inline MSAs, no templates, and explicit required upstream fields/seeds. Keep the existing AF3 JSON method unchanged.
- [ ] Show the mode, inputs, effective scientific parameters, no-MSA/no-template status, access restriction, resource needs and expected outputs at the same discover/prepare/review surfaces used by other Tasks. Distinguish model method, monomer/single-sequence mode, and MSA availability in user-facing copy.
- [ ] Preserve the original sequence bytes and role-resolved immutable input snapshot; keep generated upstream specification/features separate with provenance tied to the selected mode and validated source hash. Do not silently reinterpret input scientific meaning or add a second source of parameter defaults.
- [ ] Keep AF3's existing noncommercial entitlement/access gate, login/credits/readiness checks, server-side preflight and submission guards intact. Hide neither entry simply because GPU readiness or licensing is unavailable; render the reason through existing catalog/admission projections.
- [ ] Avoid unnecessary new Core schema/branching, duplicated scientific constants, network services, artifact types or compatibility layers. Restrict new logic to owning families plus a reusable existing interface only where needed.

## Implementation

- [ ] Add the smallest Runner-owned Task contract(s), registration, input-workspace declaration and mode-specific scientific preparation needed to deliver the two separate entries. Preserve both existing `alphafold` and `alphafold3` task types and their previous behavior.
- [ ] For AF2, implement or adapt the pinned pipeline to supply **real query-only features** compatible with its inference model (one-row MSA and correct masks/deletion/template features), without invoking MSA or template search tools; verify model input consistency using upstream feature processing rather than guessed tensor shapes. If the upstream version cannot safely support this, report exact evidence as a blocker; **do not substitute ordinary monomer inference**.
- [ ] For AF3, implement an input conversion/normalization path that feeds the existing verified AF3 runtime, without path/URL references, hidden background searches, or frontend-only validation. Keep upstream inference and output format intact.
- [ ] Treat all generated files as derivatives, not replacements for original uploaded bytes; report mode and effective feature-source provenance in results or approved metadata. Preserve the established stage/reuse semantics and do not expose unsafe reuse between different feature modes.

## Acceptance: prove the actual user journey

- [ ] Catalog and browser tests: both new entries appear independently by name/search; select, paste a sequence, upload FASTA, see mode and defaults, preflight, submit, and navigate to result. Verify the existing AF2/AF3 entries remain selectable. Include blocked-access/readiness projection behavior for AF3.
- [ ] API/validation tests: one-record FASTA accepted; multiple records, malformed residues, empty sequence and invalid specification rejected before scheduling; selected mode and generated AF3 JSON content are preserved and reproducible; original hashes remain intact.
- [ ] AF2 negative and adversarial tests: demonstrate **no MSA/template search** occurs; a query-only feature dictionary reaches real model inference; default AF2 remains MSA-assisted. Verify no fake MSA depth or mislabeled result. Test the pinned feature schema and both successful and rejected paths.
- [ ] AF3 executable tests: verify generated JSON has the required dialect/version/seeds and one protein sequence with `unpairedMsa: ""`, `pairedMsa: ""`, `templates: []`; confirm upstream processes it without a search and emits the native CIF/confidence artifacts.
- [ ] Run focused Runner fast/API/frontend tests, relevant full integration/BrowserContracts, and **real Apptainer `%test` + Doctor + target-host Slurm/GPU scientific live acceptance** for each modified executable family before production promotion. If source alone changes, revalidate only impacted image identities; never substitute fake upstream output for native science PASS.
- [ ] Ensure AF3 entitlement, quotas and fail-closed admission still apply; no network used when the explicit no-MSA mode runs. Log provenance and actual test receipts without credentials or unnecessary private sequence content.
- [ ] Keep Independent Campaign Adviser active and obtain one independent exact-head acceptance review with changed-surface evidence. Detailed findings go into this PR; avoid recursive review cycles and nonessential protocol changes.
- [ ] Remove this temporary TODO and other PR-only state before final review. Final PR report: what is live in the interface, verified AF2/AF3 scientific semantics, tests/receipts, any scientific limitations, and the production activation boundary. **Only Maintainer authorizes squash merge and production promotion.**

## Delivery constraints

The required outcome is **two working, visible sequence-first no-MSA entries**, not merely updated labels, demo fixtures, a new documentation page or a manually assembled AF3 JSON example. If either scientific path is unverified, keep the PR Draft and record the concrete blocker. Do not weaken checks or claim completion from static CI. Follow existing runner-provenance, proxy and resource-leasing policy for network-dependent builds. Keep the implementation as a focused feature PR; protocol simplification is separate.
