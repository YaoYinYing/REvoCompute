# TODO — REvoCompute Demo Foundation: Agent-operated Design Playground

> **PR scope:** provide a private, resource-light, user-interactable REvoCompute demo at `https://revocompute-demo.yaoyy.moe/` for iterative Claude Code / LCU design QA. This is **foundation only**, not the subsequent UI redesign Campaign.
>
> **Launch state:** planning-only draft. This temporary root `TODO.md` is the implementation brief for the PR owner. **Remove this file from the PR before marking READY_FOR_FINAL_REVIEW or merging**; persist the final operator/developer documentation in the existing documentation tree.
>
> **Maintainer:** retains final design acceptance, domain/security authorization, production-data export approval, and squash-merge authority.
>
> **Initial baseline:** `main@0ad3bc82eaac5f6ef54870c5c28738738d979cdc`, 2026-10-23. At execution time refresh the exact base, inspect current PRs/commits and contracts, and adapt to intervening changes.

## 0. Owner/Commander launch and sources of truth

Read `CLAUDE.md`, `LONG_TASK_HANDLING.md`, and the repository's canonical single-PR protocol before editing. Assign **exactly one implementation owner** for this PR, use an isolated worktree, coordinate any deployment or browser session as an exclusive shared resource, and arrange an independent review appropriate to deployment/auth/trust-boundary risk. Do not silently become another implementation owner. The maintainer, not the Commander, owns the squash-merge decision.

Read and preserve the documented contracts before designing:
- `docs/developer-guide/testing.md` — frontend fixtures, real-result replay, and distinction between frontend evidence and target-host acceptance.
- `docs/runner-guide/task-contract.md` — canonical `task.yaml` parameters, typed input roles, and one-click demo inputs.
- `docs/developer-guide/local-result-workspace.md` and `docs/user-guide/results.md` — post-#86 local ResultManifest v3 experience and limitations. Confirm the implementation present in the current commit, not merely a historical design record.
- `docs/developer-guide/result-view-plugins.md`, `docs/developer-guide/architecture.md`, and `docs/developer-guide/frontend-design-language.md` — result rendering, registry/runtime ownership, and Soft Precision design language.
- `docs/operator-guide/configuration.md`, `docs/operator-guide/deployment-control.md`, `docs/operator-guide/public-access.md` — controller/environment isolation, TLS, access policy, and deployment safety.
- Existing `tests/frontend_fixtures/` and `tests/fleet/browser/`, including `ReplayBundle` and the real-result browser replays.

Use the verified contracts, not this TODO, as authority when the two differ. Any necessary contract change must have a specific documented rationale and tests. Do not manufacture a second Runner/Task parameter registry.

## 1. Objective and intended use

The development workstation has a display and an LCU-capable Claude Code environment, but limited CPU/GPU/RAM/storage and cannot install every scientific Runner, model weight or reference database.

Deliver a **design and interaction playground**, not a second production compute site. From the developer's Chrome session an Agent must be able to:

1. Open a privately protected demo URL and navigate the real REvoCompute shell at desktop and mobile viewport sizes.
2. Discover representative scientific task types, inspect their methods and schemas, load declared demo inputs, and exercise input and parameter validation even when a Runner is **not runnable on the demo host**.
3. Open representative, provenance-labeled result pages and exercise actual frontend renderers with retained authentic outputs or explicitly labeled synthetic fixtures, **without recomputing**.
4. Exercise available local execution only when the host actually has a validated Runner/runtime and sufficient resources; non-runnable paths must fail closed.
5. Iterate safely through `observe → change → build → use browser/LCU → capture evidence → revise`, with reproducible browser regression checks.

The **future** Design Exploration Campaign will use this playground to address Task Discovery, Task Configuration and Result Interpretation. It is not part of this PR.

## 2. Non-goals and prohibitions

Do not:
- install every Runner or replicate the production Slurm cluster;
- migrate or synchronize production user DB, task DB, credentials, quota/credits, filesystems, scheduler identity or runtime bundles;
- expose production administration or production task submission from the demo;
- weaken `ENABLED_TASKRUNNERS`, Runner admission/readiness, input validation, publication rules, authorization, or scientific task contracts;
- add a mock Runner with fake scientific results, invent runtime readiness, or count fixture execution as scientific acceptance;
- implement cross-site task scheduling, cloud proxying, automatic production result fetching, remote Runner fallback or federation;
- introduce another hard-coded parameter list or competing input/result renderer stack;
- redesign Dashboard/Catalog/Task/Result pages in this PR or start a UI Campaign;
- expose an unprotected public demo, install test fixtures in public source indiscriminately, or commit production/user data;
- couple the demo host's ability to boot to a GPU, Slurm queue, model weight, or external database.

If any of these becomes necessary, stop and present a **separate proposal**. Prefer the smallest integration that demonstrates the browser loop.

## 3. Architecture: separation of truths

Preserve **three clearly separated product modes**. They are not interchangeable.

| Surface/mode | Truth source | UI behavior | Permitted actions | Meaning of evidence |
| --- | --- | --- | --- | --- |
| **Preview** | Canonical `task.yaml` metadata and declared demos, in a strictly read-only demo projection | Real catalog/details/form behaviors, explicit **Preview only / Not executable here** status | Browse, load demos, validate inputs/parameters locally or through an intentionally safe read-only path | Demonstrates form/UX contract, *not* host Runner readiness |
| **Replay** | Verifiable, authorized ResultManifest v3 fixture/archive and its declared artifacts | Actual result workspace/view plugins; label **Recorded result** or **Synthetic scenario** | Navigate, render, switch views, download approved fixture assets | Demonstrates frontend compatibility, *not* a new scientific execution |
| **Live** (optional) | Real local Runner discovery, admissibility and execution receipt | Ordinary real Task submission and lifecycle | Only for explicitly installed, enabled, scientifically validated families when approved | Host-specific execution evidence; target-host acceptance rules still apply |

Do not collapse Preview into `ENABLED_TASKRUNNERS`: that selector controls which families are materialized, advertised **as executable**, and accepted. A development-only preview must not masquerade as an enabled Runner in real `/compute/api/types` or reuse the submission path to create phantom tasks. Prefer a separate explicit, read-only preview projection or build-time, schema-checked catalog from the same manifests. It must be entirely disabled outside the demo/testing deployment profile.

**Source authority:** `task.yaml` remains the only author of task-specific input/parameter semantics; `demos.yaml` remains the source for eligible example inputs; ResultManifest v3 remains the result representation. No duplicated parameters, guessed defaults or handwritten scientific fixtures.

**Execution truth:** no “Run” control that silently simulates a completed scientific computation. A Preview mode should explain why execution is unavailable and offer a recorded example if present. Distinguish: available to inspect, fixture replay available, actually installed, runnable, and scientifically accepted.

**State isolation:** the demo has its own auth DB, service DB, Redis, file roots, volumes, runtime state, backups, and security settings. Do not point environment files or bind mounts at production, including via symlink. Use dedicated runtime identities and separate session secrets. The same domain suffix is not authorization to share cookies or token scopes.

## 4. Work package A — Minimal host-ready deployment

### A1. Host discovery and footprint

- [ ] On the actual development machine, record OS/architecture, Docker/Compose availability, LCU/browser accessibility, available disk/RAM/CPU and port conflicts. Do not infer hardware from old context.
- [ ] Inspect `run/revocompute_ctl`, compose layering, current `--mode=dev`, reverse-proxy options and required preflights. Reuse the supported launch/control path where possible; do not invent an independent production deployment controller.
- [ ] Define and measure a **minimal demonstrator profile** that starts without GPU, Apptainer/SIF builds, Slurm submission, scientific weights or databases. Explain any optional integrations explicitly. If a legacy boot preflight assumes a scientific executor, add a **narrow demo-only bypass with refusal of execution**, not a global weakening of production checks.
- [ ] Keep a per-host environment file outside source control, mode 0600; derive safe paths and non-privileged runtime identity. Do not dump secrets to logs/CI.
- [ ] Ensure reproducible start/stop/restart/status/doctor from supported control tooling. An ordinary checkout should not be mutated just to make the deployment work.
- [ ] Document reset/reseed of *demo-owned* data only and safe rollback to the previous deployed revision.

### A2. Private ingress

- [ ] Configure `https://revocompute-demo.yaoyy.moe/` on the development host using an authorized Cloudflare Tunnel or existing TLS reverse-proxy pattern. Use the documented gateway endpoint, not internal Gunicorn.
- [ ] Protect access through Cloudflare Access / equivalent ingress authorization **and** retain correct application permissions. Explicitly approve every account permitted to access the environment. Avoid broad organization/site-wide wildcard exemptions.
- [ ] Lock down host bind/firewall, TLS-forwarding headers, HTTPS-only cookies and HSTS as documented; validate origin cannot be accessed directly from untrusted networks.
- [ ] Add `noindex` / robots deterrence as secondary discovery controls **only**, never as security.
- [ ] Give the demo a small unmistakable but non-invasive **Demo environment** indication; do not impersonate production status or change core visual language.
- [ ] Prove demo login/session cannot authorize production, and demo logout/settings cannot mutate production. Test unauthenticated, forbidden, admin-only and token-leak cases.
- [ ] Record external prerequisites that only the maintainer can do (DNS/Tunnel ownership, permitted access, secret provisioning), without committing or guessing them.

**Deployment verification:** real HTTPS page load in Chrome/LCU; ingress auth enforced; ordinary app authentication enforced as applicable; correct TLS response behavior; no origin bypass; persistent demo-owned state survives restart; demo deletion/reset cannot affect production.

## 5. Work package B — Catalog, form and example preview

- [ ] Design the smallest **demo-only, explicitly non-executable** Task projection from checked-in manifests. Document why it cannot be mistaken for the enabled-Runner registry. Refuse malformed, unknown, stale or unsafe manifest/example records.
- [ ] Present genuine method identity, scientific description, declared typed input roles, constraints, defaults, and citations from the current Task contracts; preserve server-side semantic validation where execution is real.
- [ ] Preserve the existing Task Card/detail/create flow. In preview, do not allow submission; give an honest unavailable-reason and distinguish missing local runtime from misconfigured/failed production readiness.
- [ ] Make the built-in declared demo-input workflow usable for representative tasks, including provenance/licensing and parameter presets. A demo can fill controls but must not spend credits or create a Task.
- [ ] Use readable, scientifically meaningful form validation and handle realistic empty/invalid/multi-role inputs. No hard-coded special case for the handful of demonstration tasks.
- [ ] Avoid sharing personally uploaded examples between users or promoting arbitrary uploads into global fixtures.
- [ ] Confirm updates to a `task.yaml` change the preview appropriately without editing a second scientific schema file. Include a contract-drift check.
- [ ] Scope preview to development/demo; production behavior and API responses must stay unchanged unless an explicitly justified backward-compatible change is necessary.

**Minimum fixture cases:** sequence FASTA task, structure/PDB task, multi-component/complex task, input that has a dialect or non-protein role, task with advanced/optional parameters, and an unsupported/unavailable case. Only use examples that actually exist and can be redistributed; mark absent examples honestly.

## 6. Work package C — Authentic results and UI replay

- [ ] Reuse `tests/frontend_fixtures`, existing `ReplayBundle` patterns and the post-#86 **Local Result Workspace** rather than writing a second ResultManifest interpreter.
- [ ] Decide the smallest path for **interactive** result inspection in the demo: privately retained, allowlisted authentic test bundles; local result folder selection; or a thin fixture adapter that passes the same manifest/artifacts to the existing workspace. Record the chosen provenance and trade-off.
- [ ] Maintain one logical Result Workspace where the current architecture allows it. Reuse Mol*, tabular, plots, text, sequence, multidimensional or other existing renderer capabilities **only as declared in the manifest**.
- [ ] Fixture metadata records origin/provenance, TaskType, source version, manifest schema revision, SHA-256 digests, sizes, privacy/redaction status, and whether data are synthetic or from a previously executed task.
- [ ] Reuse authentic result archives **only when the maintainer has approved transfer** and redistribution/private-storage conditions are satisfied. Never fetch them directly from production credentials or export user data automatically.
- [ ] Store large/private result ZIPs in a demo-local restricted fixture store, **outside Git and the application image**. Add a git-safe, non-sensitive manifest/config index when needed. Respect archive constraints and input trust boundaries.
- [ ] Missing or mismatched fixture files should yield a clear error/disabled scenario, never fabricated output or a blank-success page. Fail closed on unsafe archive paths, symlinks, excessive sizes or untrusted active content per existing security rules.
- [ ] Handle a bundle with a Storyboard: follow the canonical server/local-result policy. Do not execute arbitrary Storyboard code embedded in an archive; an absent allowlisted renderer is a supported limitation.
- [ ] Provide a reproducible way to select a few representative scenarios (structure, table/scoring, multi-artifact, advanced viewer) for visual iteration. Keep selection stable across reloads where practical; don't claim all outputs are available.
- [ ] If progress/history/error UI needs special demonstration states, use **explicitly labeled synthetic scenario fixtures** in testing/preview, not fake production tasks or forged Runner receipts.

**Acceptance:** compare selected replay renders with the current production result UI using the same recorded output (where available); critical pages render without execution dependencies; downloads and provenance remain truthful; missing data fail visibly.

## 7. Work package D — LCU design-feedback loop

- [ ] Confirm LCU actually controls a **visible Chrome session on the development host**. Do not build a new automation bridge solely for this PR.
- [ ] Document a concise runbook: identify deployed commit, launch demo, authenticate with demo-specific account, reserve exclusive browser access, open designated journeys, perform actions, capture screenshots, write findings, and compare before/after.
- [ ] Agent observations are **evidence, not truth by assertion**. Record browser viewport, URL/route, input or result fixture ID, source revision, screenshot reference, interaction steps and objective behavior.
- [ ] Provide at least three reproducible scientific user journeys: `Catalog → Task Detail → Demo Input → Validation`; `Results → Viewer/Metric → Artifact`; `Unavailable Runner → Explicit Preview/No Submit`.
- [ ] Include desktop and mobile-size checks, keyboard/focus navigation, accessible labels, long content, dialog behavior, error states and dark/light theme if supported.
- [ ] Retain scripted browser/contract regression gates in addition to human-like LCU walkthroughs. LCU cannot stand in for backend security tests or scientific Runner acceptance.
- [ ] Keep screenshots/test reports outside Git by default; redact account information and proprietary inputs before sharing.
- [ ] Never allow concurrent agents to operate the same Chrome profile/tab. The Commander allocates browser leases; terminate the lease after the bounded check.

## 8. Work package E — Test gates, evidence and documentation

**Security / contract tests**
- [ ] Production mode does **not** expose demo preview routes/content or enable any submission bypass.
- [ ] Preview-only Task is rejected if a crafted client calls the ordinary submission API directly; no database row, reservation, Slurm job, runner start or credit charge.
- [ ] Missing/invalid manifest and fixture metadata are rejected; contract changes invalidate stale preview/replay where appropriate.
- [ ] Result import/replay respects trust boundaries, origin isolation, data-size limits and non-executable archive behavior.
- [ ] Demo session, auth database, storage and quota are demonstrably isolated from production.
- [ ] Restart/reset only touches explicitly configured demo-owned paths. Test refusal when a configured path points to a parent, symlink or production path.
- [ ] No ingress path grants unauthenticated privileged access or bypasses permission checks; regression tests cover direct and proxied access.
- [ ] No secret, token, production URL embedding of private IDs, or personally identifying fixture leaks to committed screenshots/logs.

**UX / replay tests**
- [ ] Browser fixture tests cover at least the three canonical journeys from §7 and one invalid-input, absent-example, unavailable-runner, missing-result, and mobile navigation case.
- [ ] Use real `task.yaml` and ResultManifest v3 contracts; frontend-only fixtures must not claim scientific readiness.
- [ ] Exercise selected renderer plugin(s) with actual captured outputs where available and verify key UI events, not screenshot appearance alone.
- [ ] Run canonical server/browser/contract checks, `make test-boundaries`, applicable fast tests, frontend lint/build and `mkdocs build --strict` (follow the current repository's commands rather than inventing a new gate).
- [ ] Independent reviewer checks auth, fixture truthfulness, deployment isolation, compatibility of production APIs, and user-facing labels against the exact PR head. Maintain evidence in PR threads, not in a parallel private review log.

**Persistent documentation**
- [ ] Write `docs/developer-guide/demo-playground.md` (or the correct established documentation home) describing purpose, trust model, Preview vs Replay vs Live semantics, fixture sourcing and replay preparation, LCU runbook, resource requirements, failure/rollback recovery and limitations.
- [ ] Add a concise operator deployment reference for the demo host using existing environment and gateway conventions. Document the private host's actual tested settings **without publishing credentials or host secrets**.
- [ ] Include a capability/scenario coverage matrix showing which pages are interactive, which use replay, and which need real execution.
- [ ] Explain how a future design Campaign can use the demo without modifying the Preview/Replay trust model.
- [ ] Delete this temporary root `TODO.md` before final review; the durable design record belongs in existing documentation.

## 9. Milestones, scope decisions and shared-resource gates

**M0 — Baseline and feasibility.** Read all current contracts, inspect the actual development host, choose minimum startup mode and fixture path, write concise execution plan. Show that the private demo can boot without a scientific executor. If this cannot be demonstrated, stop and identify the smallest blocker rather than making broad Core changes.

**M1 — Deployment isolation.** Demo-specific state/env, private TLS ingress, account/session separation, resource-safe startup, rollback. No preview catalog necessary yet. Owner submits concrete browser/TLS/host evidence.

**M2 — Non-executable Task preview.** Canonical manifest projection with honest readiness labels and example-form journey; direct submission remains forbidden for unavailable runners.

**M3 — Replayed scientific results.** Load approved fixture/archive through existing workspace and render representative views, with provenance/verification and missing-fixture refusals.

**M4 — LCU acceptance.** Claude Code operates desktop Chrome across representative scenarios, captures evidence and files any genuine UX defects. Correct **foundation defects** only; broader design improvements become Phase II ideas.

**M5 — Independent review and handoff.** Run regression/CI/security/doc gates, collect independent reviewer evidence against exact head, record limitations and deployment operations, remove root TODO, mark `READY_FOR_FINAL_REVIEW`. Do **not** merge.

**Stop/escalate** if requiring production credentials, a shared auth/session database, direct production scheduling, credit expenditure, public access without authentication, unsafe fixtures, or architectural changes that significantly alter the production Runner/Task/Result semantics. Commander should resolve routine setup conflicts, not use maintainer attention for minor environment details.

## 10. Maintainer acceptance checklist

This PR is a success only when a maintainer can open `https://revocompute-demo.yaoyy.moe/` through approved access and, on the development machine:

- [ ] Confirm private HTTPS ingress and a visible, non-deceptive Demo identity.
- [ ] Navigate real REvoCompute pages without installing the entire scientific fleet.
- [ ] Open representative Task manifests and sample input forms with correct scientific parameters, while knowing exactly which tasks cannot execute.
- [ ] Attempt a preview-only “submit” pathway and **observe a refusal** with no created job, resource charge or backend execution.
- [ ] Open and interact with genuine or clearly labeled synthetic result fixtures; see reliable provenance and useful errors when a fixture is missing.
- [ ] Have Claude Code use LCU in Chrome to complete three reproducible journeys and collect screenshot/interaction evidence.
- [ ] Restart and recover the demo independently of production.
- [ ] Review tests proving prod/demo isolation and no weakening of Runner submission readiness or data security.
- [ ] Read one current runbook, one limitations matrix and an exact-head independent review; find no temporary root TODO in the final diff.
- [ ] Confirm the demo supports **future** creative Design Exploration Campaigns without requiring changes to this PR's trust boundary.

**Out of scope even if tempting:** the Tamarind-inspired UX redesign, autonomous design-Campaign protocol changes, new scientific Runner integration, live production job forwarding, and complete workflow/Pipeline orchestration. Record those as future design opportunities, not opportunistic PR additions.

## 11. Final handoff to the maintainer

Provide only:
- PR number, exact head and merge readiness;
- working demo URL and access prerequisites **without secrets**;
- which Preview/Replay/Live journeys have been **actually observed** and which remain unverified;
- evidence paths and major tests/CI;
- major blockers and accepted limitations;
- independent reviewer assessment;
- concise future Design Exploration Campaign suggestions **separate from this PR**.

The **maintainer alone** chooses if and when to squash-merge or authorize the next Campaign.
