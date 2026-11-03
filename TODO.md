# Runner Result Contract Closure

Baseline: main `c90b2890489e3062080a9ec997e71bb69799d329` (merged PR #132).
Goal: close the enabled Runner TaskType result-contract coverage gaps without changing scientific semantics or touching the newly deployed production release.

## M0 — Establish the actual defect set

- [ ] Fetch live main, PR exact head, CI, and the canonical `tools/audit_runner_scientific_contracts.py --json` result. Cross-check `revocompute/result_audit.py` and the fleet inventory tests.
- [ ] Reconcile the **11 historical enabled TaskType gaps** in the PR #132 release dossier with Commander's report that **two** remain after production deployment. Read the deployment evidence at `.claude/campaigns/production-release-candidate/deployment-2026-11-03.md` if accessible; the file is not present in GitHub main. Distinguish committed code, deployed state, local-only fixes, and audit limitations.
- [ ] Record authoritative scientific output filenames, required/optional conditions, declared view sources, file types, result roles, and authentic output evidence per TaskType.

Historical review inventory (not an assertion that all eleven currently fail on the deployed host):

| Family | TaskType | Earlier state |
| --- | --- | --- |
| geodock | geodock | tree_absent |
| mpnn | thermompnn | tree_absent |
| pallatom | pallatom_generate | tree_absent |
| pythia_ddg | pythia_ddg | tree_absent |
| rfdiffusion2 | rfdiffusion2_ligand_binder | tree_absent |
| rfdiffusion2 | rfdiffusion2_motif_scaffold | tree_absent |
| codontransformer | codon_optimize | no_required_source |
| esm | esm_extract | no_required_source |
| esmdynamic | esmdynamic | no_required_source |
| foundry | foundry_rf3_fold | no_required_source |
| simplefold | simplefold_predict | no_required_source |

The source-wide audit previously counted 12 unaudited tasks; enabled and whole-fleet denominators must remain distinct.

## M1 — Repair owning contracts

- [ ] Delegate by nonoverlapping Runner family groups. Start with ThermoMPNN and Pythia-ddG but reconcile all eleven.
- [ ] Fix `expected_files.yaml` in the owning family or Task directory and any necessary `task.yaml` Result Workspace selector or Storyboard. Use only observed scientific outputs to decide `path` / `pattern`, `cardinality`, `required`, `type` and `role`.
- [ ] Required primary scientific output must be validated. Conditional outputs (e.g., trajectories, optional refinement) stay conditional. Do not invent placeholders, widen patterns to catch everything, relax required view sources, exclude Tasks, or suppress audit findings.
- [ ] Prefer declaration-only changes. Change `run.sh`, shared runtime, scientific definitions or dependencies only if a reproducible defect requires it. Record the exact SIF/Bundle/contract identity impact.

## M2 — Test against real outputs

- [ ] Add family-owned output-contract tests for every repaired TaskType. Assert real filename selection, primary-view resolution, role/type, requiredness, cardinality and negative failures for missing or misnamed files. Cover supported optional branches.
- [ ] Re-run the canonical scientific contract auditor and `make test-fleet`. Require no outstanding unaudited required-source gap among enabled Tasks, no new concrete defects, and an accurate enabled/disabled denominator.
- [ ] Authenticate outputs against existing read-only finished Task records or isolated Slurm/Apptainer acceptance. Static tests and synthetic fixtures are insufficient to certify real upstream output. Preserve immutable identities and exact receipts.
- [ ] A source declaration can invalidate test/execution identity even without rebuilding SIF. Revalidate accordingly. Do not deploy, restart, promote artifacts, alter live tasks or activate bundles in this campaign.

## M3 — Human-readable evidence and review

- [ ] Post a canonical PR comment with an **11-row before/after matrix**, including source state, deployment evidence, source commit, observed outputs, exact validation identity and certification verdict. Clearly label unresolved or inaccessible evidence.
- [ ] Update the existing `docs/developer-guide/scientific-contract-inventory.md` from the regenerated audit. Do not create a second Runner Contract or duplicate the fleet roster.
- [ ] Preserve the distinction: **31/31 execution READY does not by itself mean every TaskType is scientifically result-certified**.
- [ ] Run scoped tests, `make runner-fast`, applicable server and browser contracts, strict docs, test boundaries and full exact-head CI. Independent R1/R2/R3, scientific result reviewer, continuously active Independent Campaign Adviser, and final independent Campaign Acceptance Auditor must verify the frozen head.
- [ ] Remove temporary root TODO before requesting maintainer squash merge.

Commander operates autonomously in scoped code, docs, CI and isolated scientific acceptance; detailed findings belong in PR threads. Ask the maintainer only for genuine release-policy choices, inaccessible evidence or new production authority. The maintainer separately authorized the previous deployment: do not construe that past approval as blanket permission for future production changes.

**Exit gate:** all confirmed enabled-source result-contract defects are fixed with test and authentic output evidence or explicitly remain NOT CERTIFIED with a concrete reason. No deployment or merge in this campaign without separately granted maintainer approval.
