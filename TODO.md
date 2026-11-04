# Runner Upstream Capability, Version and Adaptation Standards Campaign

> Temporary working plan for this Draft PR. Remove this file before `READY_FOR_FINAL_REVIEW`.
> Durable guidance belongs only in existing `docs/runner-guide/` owners and family-owned files.

## Objective

Reconcile the full shipped Runner Fleet with authoritative upstream science and the exact upstream software that the images install. Repair valuable missing or misleading Task-level capabilities, inspect upstream releases and perform evidence-backed upgrades, and update the existing Runner authoring/acceptance documentation. Keep the existing architecture: enabling a Runner Family automatically registers its `plugin.yaml` Task manifests. Core must not know method-specific science.

Starting base: `main` `8cdf41a5d20df3edc1aa96d6e6a5a0bdb2f9cc03` (after #133). Re-read current exact `main`/head and reconcile before implementation. The initial tree has **43 families with `plugin.yaml`**, including reference/mock families; the list must be rediscovered programmatically, not assumed stable.

## Non-negotiable boundaries

- **No new Core scientific-capability registry, knowledge graph, central runner-name dispatch, Task metadata authority, custom workflow engine, or duplicate manifest.** Scientific interpretation remains in the owning family, `task.yaml`, adapter, and acceptance.
- An upstream paper is a claim, a repository revision is an implementation, the deployed SIF is a specific environment, and a live-test receipt is observed execution. Never conflate those evidence levels.
- Do not expose every upstream CLI flag. Prioritize distinct, useful scientific operations, alternative input modes, and parameters that change an experiment. Document intentional omissions with reasons.
- Do not silently change default science, output meaning, input compatibility, published role names, checkpoint identity or licenses. A new input mode is an execution-contract change and needs evidence.
- Keep existing Graph IR, typed Stage definitions, Runner Fleet, admission, resource accounting, Result Workspace and readiness gates as-is. Extend only a family-owned contract unless a concrete unavoidable generic defect is proven and separately reviewed.
- No mass automatic `latest` upgrades, unpinned source builds, runtime model downloads, unreviewed checkpoint swaps, fabricated scientific results, or tests that merely assert YAML text.
- A merged PR is not an authorized server deployment, active SIF promotion, Runtime Bundle activation, destructive migration, cancellation of production Tasks, or permission to alter live user data. Target-host test execution and resource expenditure require appropriate operator authorization and isolated candidate handling.

## M0 — Establish exact-head source truth and organize ownership

- [ ] Commander reads `CLAUDE.md`, `LONG_TASK_HANDLING.md`, `docs/agents/single-pr-campaign.md`, existing Runner Protocol, and this TODO. Verify exact main/head, changed paths, no active conflicting campaign, and baseline CI.
- [ ] Discover every family by `docker/runners/*/plugin.yaml`. Obtain actual deployment enablement/readiness only from authorized deployed evidence; source presence is not production enablement. Distinguish reference/mock, disabled, withheld, restricted, enabled, and production-certified.
- [ ] Delegate independent non-overlapping family cohorts: (A) folding/structure, (B) dynamics/design/MPNN, (C) remaining fleet/version census, (D) docs/integration. Reserve **Independent Campaign Adviser** with no implementation ownership; Commander coordinates and serializes overlapping edits. Add additional family owners only when the slot and test resource budget permit.
- [ ] Publish the 43-family census and owner ledger to this PR's discussion, not a second machine-readable catalog or a permanent duplicated support matrix. Thread is the canonical technical record.

## M1 — Source-backed upstream knowledge and Task coverage audit

- [ ] For **every** shipped family, identify its actual upstream(s), pinned commit/tag/package, model/checkpoint/data version and license, and the authoritative reference sources (primary paper/supplement if applicable; pinned README/docs; CLI/API; example workflows; upstream tests; release notes). Include source URL and exact revision/line or reproducible CLI evidence. Mark proprietary/unavailable upstream honestly.
- [ ] Inventory *user-relevant scientific operations* and their scientifically meaningful variants: accepted structures/sequences/complexes/MSAs; optional preprocessing; modes, conditioning, restraints, sampling, scoring; output interpretation; upstream constraints; resource and network dependencies. Distinguish claimed by a paper, available in pinned code, available only in newer releases, and experimentally verified.
- [ ] Compare upstream operations to registered `task.yaml`, `plugin.yaml`, execution adapters, Result Workspace, `expected_files.yaml`, `test.yaml`, Storyboard and real output. Classify each mode: `verified exposed`, `implemented but hidden`, `missing`, `intentionally excluded`, `unavailable at pinned version`, `unverified`, or `broken`. Explain every non-exposed meaningful operation.
- [ ] Publish one compact 43-row family inventory in the PR discussion. Minimum columns: family, enablement scope/source, pinned version, latest applicable official version, upstream evidence, important gaps and dispositions, version disposition, affected Task(s), required validation, owner. Each substantive finding links to a family-scoped comment/thread and source evidence.
- [ ] No guessed capabilities: issue an evidence-based disposition when code/paper disagree or a feature requires upstream modification. Do not silently implement scientific algorithms not supported by the pinned upstream.

### Priority scientific counterexamples (investigate, do not assume fixes)

- [ ] `alphafold`: distinguish upstream `--use_precomputed_msas`, provided alignments, single-sequence/no-MSA inference, and feature construction. Verify what the **pinned** upstream truly supports; implement only validated pathways, not a fake no-MSA toggle.
- [ ] `alphafold3`: current JSON Task accepts upstream specifications; `tests/data/json/alphafold3_tiny.json` already has empty `unpairedMsa` and `pairedMsa`. Determine whether MSA-free is already executable and merely undiscoverable, and ensure the pinned AF3 feature/model path and network/resource semantics are correct. Do not duplicate JSON science in Core.
- [ ] `colabfold_af2`: `msa_mode: single_sequence` and a corresponding smoke fixture already exist. Verify actual no-search/no-network behavior against the pinned ColabFold version, including the declared MSA/features stage's network requirements. Fix only verified incorrect planning, Task semantics or user discoverability.
- [ ] `bioemu2`: currently only the `bioemu2_equilibrium` FASTA Task is registered. Review pinned `v0.1.0rc0` source/docs for structure prediction, system construction from mmCIF/YAML, all-atom start-coordinate **propagation**, and any other supported modes. Do not confuse using a structure to specify a molecular system with conditioning on its coordinates. Implement justified additional family-owned Task(s) with appropriate input roles, topology/trajectory semantics and real scientific tests.
- [ ] `mpnn/ligandmpnn`: verify both LigandMPNN and side-chain-packing checkpoint availability and upstream argument forwarding; distinguish upstream `backbones/` from actual `packed/` structures. Investigate reported `pack_side_chains=1` failure and the large default batch count. Ensure optional modes are not misrepresented as completed capability or as packing outputs without packed coordinates.
- [ ] Inspect known suspension/gap notes in `docs/runner-guide/wait-list.md` (for example Boltz and FRODOCK) rather than assuming a green SIF implies usable scientific functionality. Do not silently enable suspended families.
- [ ] Extend beyond this seed cohort to all discovered families. Prioritize externally enabled, research-critical, high-impact missing input or algorithm modes; do not spend the whole PR exposing minor debug switches.

## M2 — Upstream release comparison and bounded version upgrades

- [ ] For each family, identify **actual build/deployed pin**, available official releases/tags and the best relevant current **stable** version at the date of audit. For forks, compare the correct source lineage and effective commit, not just a similarly named public package.
- [ ] Read intervening changelogs and code-level migration risks. Check upstream licenses/terms, dependency locks and Python ABI, CUDA minor/driver, upstream API/CLI changes, model asset/checkpoint availability and SHA256, runtime defaults, input/output compatibility, and performance or GPU-memory changes.
- [ ] Choose a traceable disposition for all families: `upgrade now`, `retain current pin`, `blocked (why)`, or `defer (why)`. An upstream release is **not** automatic authorization to upgrade; preserve validated SIFs and users' immutable tasks.
- [ ] Implement a bounded, high-value cohort of **safe and meaningful** upgrades on this PR, with independently testable owner slices. Prefer fixes that unblock a missing Task mode or remedy a concrete defect. If none is safe, state that openly; never fake an upgrade by changing presentation metadata.
- [ ] For each selected upgrade, update the real pinned build/lock/patch path and any existing `upstream.json`/family provenance; change Task contracts only when upstream behavior requires it. Reconcile build-input coverage, network/model mounts, resource bounds, and actual output/role contracts. Do not create another version database or external polling service.
- [ ] Classify changed files by Build, Runtime Bundle, Execution, or Presentation identity using `docs/runner-guide/runtime-bundles.md`. Rebuild the candidate SIF for changes to `.def`, lockfiles or image-baked adapter code; reuse the SIF only for eligible overlay-only edits, with new exact-identity live receipts.
- [ ] Explain explicit keep/defer decisions, including what future upstream evidence or asset availability would reopen them. Significant changes that cannot be scientifically accepted under this PR must remain separate, source-backed follow-ups rather than unvalidated merges.

## M3 — Update standards in existing documentation

- [ ] Review and refine the initial edits in `docs/runner-guide/adding-a-runner.md`, `runner-family-protocol.md` and `test-plan.md`: upstream source triangulation, pinned-vs-newer distinction, capability-to-Task mapping, deliberate exclusions, version upgrade dispositions, mode-level test evidence, and owner boundaries.
- [ ] Reconcile `docs/runner-guide/index.md`, `task-contract.md`, `plugin-manifest.md`, `runtime-bundles.md`, `model-resources.md`, `docker/runners/README.md`, and existing traceability examples **only as needed** to eliminate concrete contradictions. Link to the owning page rather than duplicating the same guidance.
- [ ] Keep existing `task.yaml` the sole authority for parameters/defaults/help and the existing automatic Task registration. No permanently tracked central 43-row version/capability matrix. Family `README.md` or `SCIENTIFIC_TRACEABILITY.md` may preserve genuinely useful scientific rationale; PR comments contain the campaign census and source-backed dispositions.
- [ ] Documentation should teach agents **how to investigate** upstream software: verify exact revision, extract scientifically meaningful modes, compare Task coverage, implement bounded changes, validate real outputs, state unsupported limitations. Provide one small concrete example without turning the guide into a universal scientific tutorial.
- [ ] Run `mkdocs build --strict`, check navigation/anchors, and remove stale or duplicate instructions made obsolete by the changes.

## M4 — Verification, scientific review and delivery

- [ ] For every modified Task, demonstrate schema validation, named input-role resolution, parameter forwarding and alternative-mode behavior with focused family executable tests. No text-only tests for YAML/README/definitions.
- [ ] For newly supported non-default scientific operations, use real upstream/target-host cases. Assert scientific artifact semantics (e.g., absence of MSA query in genuine no-search mode; actual side-chain coordinates vs backbone-only; BioEmu2 input-coordinate propagation and system consistency), not just `task_finished` or exit code 0.
- [ ] Run strict Doctor, Runner fast tests, scientific-contract audit, affected server/browser regression tests, fleet checks, `mkdocs build --strict`, and exact-head CI. Record the commands, exact commits and outcome in PR discussion.
- [ ] Perform the existing target-host `prepare` / `live-test` acceptance through authorized isolated candidate SIFs and bundles for every changed enabled Family; observe real scientific outputs and resource usage. No authorized host access => record `NOT VERIFIED / NO PROMOTION` rather than claim readiness.
- [ ] Reject regressions in access controls, network isolation, immutable Task snapshots, pinned StageRun provenance, output validation, GPU accounting, crash recovery and Runner readiness. Reviewer should examine exact changed scientific semantics, model asset and license implications.
- [ ] Independent Campaign Adviser remains active and independently challenges scope, latest-version assumptions, interpretation of upstream papers, science, acceptance and Core boundary. Independent scientific reviewer plus R1/R2/R3, Examiner when relevant, and final **Campaign Acceptance Auditor** assess the exact integrated head under `docs/agents/single-pr-campaign.md`.
- [ ] Before final handoff, retire root `TODO.md` and temporary campaign state; consolidate durable family facts into owning family files and documentation. Final Auditor posts explicit `ACCEPTANCE_AUDITOR_PASS` against exact head. Commander reports `READY_FOR_FINAL_REVIEW` only after that verdict; **maintainer alone decides squash merge and any production action**.

## Acceptance / stopping rule

The deliverable is an evidence-backed census of all 43 initial families (reconciled to the eventual exact tree), corrected high-priority Task capability omissions with genuine scientific proof, a defensible version decision for each family and tested safe upgrades where feasible, and concise updated authoring standards. A capability is not `verified` merely because upstream mentions it or the API accepts its parameter. Newer releases, non-default modes and disabled families may be honestly `deferred`, `unsupported` or `NOT READY`; no forced upgrade or deployment to satisfy a checklist.

## Commander control state

Keep only exact base/head, merge/no-merge, blocker category, owner, Adviser verdict, CI/evidence pointers and next decision. All detailed technical findings and family audit rows belong in this PR's discussion. Owners read those threads directly, implement minimal scoped changes, and attach exact-head regression evidence. Do not pause for routine decisions; escalate only actual policy/scientific ambiguity, missing operator authorization, unavailable model assets, or irreversible action.
