# Campaign TODO — Recover Task-Oriented Scientific Result Storyboards

> **Single PR / production-evidence-first Campaign.** This document is a working plan, not proof of successful execution. Do not claim that a Task works until a real production task and browser interaction have been observed. The maintainer alone authorizes squash-merge and any production promotion requiring approval.

## /goal

Restore the scientific usability of REvoCompute Result Workspace, one TaskType at a time, by deriving each task-owned Storyboard from **new, Commander-submitted, authentic production API → Slurm → Apptainer → published ResultManifest** evidence. Preserve Runner ownership of scientific meaning, the shared viewer/primitives and manifest security boundaries, and the existing artifact/download fallback. Deliver one integrated PR with independently owned task families, real-result replay/browser acceptance, and an explicit per-Task outcome; never equate “valid manifest” with “usable scientific result.”

## 0. Ground truth and non-negotiable boundaries

- [ ] At campaign start, re-read `origin/main`, the complete open-PR/CI state, current production deploy SHA, active Runner catalog/readiness, and the existing campaign/agent protocols. **Do not rely on the SHA below as current.**
- [ ] Baseline observed in GitHub `main` at `d6e681cedb60a1c85aa7ab2fc1812c1f571448e8` (2026-10-20): 56 Task manifests, 23 `expected_files.yaml` files, and 16 Storyboard declarations. Counts describe *declared sources*, not actual production readiness or guaranteed browser behavior.
- [ ] Baseline critical regression: BioEmu's Task declares `trajectory` with `topology.pdb` + `samples.xtc`, but ships neither a logical result tree nor Storyboard; the TS Result Workspace registers only the `matrix` scientific view plugin; `artifactForView()` picks only the first source; `MolecularViewer` offers static `loadStructure()` without trajectory frame handling.
- [ ] **Historic migration evidence:** PR #32's pre-migration base `83fef06032027eda8bdff6fb1a99eed5afcd0658` had a live-coded `renderTrajectory()` in `revocompute/static/js/task-results.js` and Mol* `loadTrajectory()`/frame-control support in `viewer-shell.js`. Its registry included eight scientific view plugins: `candidate-collection`, `entity-table`, `evidence-bundle`, `alignment`, `trajectory`, `metric-series`, `matrix`, and `scalar-summary`. Compare each legacy capability with current Vite implementations, mark parity/missing/changed, and migrate supported behavior to the current architecture without reinstating the retired iframe or legacy shell. Old code establishes the existence of an implementation, **not** independently observed production functionality.
- [ ] The Commander must **personally use the actual authorized production service/API to submit and observe a fresh test case for every TaskType taken into active Storyboard implementation**. A subagent's report, direct container invocation, synthetic fixture, existing task ID, local output, or guessed sample does not satisfy this gate. Old task receipts may be used for diagnosis, never substituted for the new case without documented maintainer exception.
- [ ] Use the deployed Runner's `test.yaml` smoke case as a starting input, but choose an example that actually exercises the intended scientific presentation. Record any inadequacy of the smoke case; never invent source files.
- [ ] Do **not** allow a production rollout just to make a screenshot pass. Submission must use ordinary authenticated endpoints and the canonical API → Worker → Slurm → Apptainer → finalization path. No direct database injection, fabricated job receipt, bypass of admission, credentials in fixtures, or privileged copying of another user's Task.
- [ ] Production is shared infrastructure: respect access controls, quotas, GPU/CPU queue availability, network dependencies, and test-window leases. Set bounded submission and polling budgets; never saturate production merely to fill available coding-agent slots.
- [ ] No unrelated backend, scheduler, UI-shell, authentication, Slurm, or Runner-refactoring campaign. If an authentic result reveals a computation defect, document and triage it explicitly instead of disguising it as a presentation fix.
- [ ] One PR only. Owner worktrees/local topic branches are **not additional PRs**. One integration owner serially integrates completed owner commits into the PR branch; no concurrent modifications to one shared worktree. Do not force-push or squash-merge without maintainer approval.
- [ ] Independent Campaign Adviser stays active throughout; checks evidence fidelity, scientific claims, scope, writer ownership, review quality and exact-head merge readiness independently of Commander.
- [ ] An independent **Examiner (Examer)** owns hands-on browser interaction, screenshots and visual/scientific UX acceptance. Examiner must be independent of Task implementation, the Commander and the Adviser: Playwright success and Owner self-approval cannot substitute for its findings.

## 1. Diagnose the missing contract, do not redesign Core by guesswork

- [ ] Build a discovered Task matrix: `TaskType`, `family`, deployed SHA, readiness, declared view plugins, view-source selectors, expected-file tree scope, Storyboard scope, artifact capabilities, existing browser acceptance, and product-visible result behavior.
- [ ] Build a **legacy-to-current scientific-view parity matrix** for all eight formerly registered plugin kinds. Audit old plugin responsibilities and interactions, not only plugin identifiers. Each missing shared primitive must have either a recovered implementation or a scoped, explicit justified alternative; a task-owned Storyboard does not excuse a broken declared secondary view.
- [ ] For every declared primary and secondary view, classify the **actual implemented renderer**: task-owned Storyboard interaction, shared protocol renderer, appropriate generic preview, explicit justified download-only, or **unimplemented**. A declared plugin name is not proof of an implemented renderer.
- [ ] Explicitly report when a scientific view requiring multiple files gets collapsed to the first source (`ResultWorkspace.artifactForView()`); when `storyboard.yaml` is absent; when the declared logical result tree does not address the real output; or when a viewer capability is absent.
- [ ] Split assessment into *declaration validity*, *actual artifact availability*, *scientific interpretation*, *browser renderability*, and *production interaction*. Do not mark any one green on the strength of another.
- [ ] In the PR design record, document the root mismatch: `result_workspace.views` describes scientific intent, `ResultManifest` approves artifacts, `Storyboard` composes their task-specific scientific semantics, shared primitives implement interaction, and the browser must actually be able to render the declared operation.
- [ ] Preserve task-scoped result ownership introduced in PR #93 and boundary hardening in #99. A task directory shipping `expected_files.yaml` owns its Storyboard; a task without its own tree can only take the family fallback as specified by `revocompute/result_storyboard.py`. Never choose a contract by inspecting result filenames.

## 2. Commander: production discovery and evidence handoff (mandatory before owner design)

For **each** targeted TaskType, Commander performs and records:

- [ ] Confirm deployment and Runner state: repo/main/deploy revisions, enabled/readiness state, SIF and runtime-bundle identities where available, candidate Task schema, test input source, known cost/size limits, and permission to use the test window.
- [ ] Prepare a small, real, scientifically interpretable input accepted by the Task's named input roles and declared parameters; prefer the Runner's required test plan and a deliberately nontrivial example if necessary.
- [ ] **Submit the Task itself via production API** (not through a subordinate) using the authorized test account and normal admission path. Save the returned task handle/ID and accepted parameter/input snapshot. On admission denial, runner unavailability, missing weights, unsupported network, or production incident: mark BLOCKED with the actual reason and stop. Never claim acceptance.
- [ ] Observe normal status transitions through completion, record scheduler job/accounting source when available, output-check state, terminal outcome, ResultManifest schema v3, projected `views`, `storyboard`, logical `result.files`, artifact listing, and required artifact hashes/sizes.
- [ ] Inspect **real payload content** through authorized artifact routes, not just filenames: topology/coordinate match, model count, score direction/units, ranking, residue indexing, PAE/metrics availability, missing/NaN semantics, limits and scientific caveats. Keep inspections bounded and safe; treat binary content as binary.
- [ ] Open the *deployed* result URL as the Task owner and record what the browser really shows: initial scientific view, controls, errors, usable interaction, archive/download fallback, fullscreen/mobile if relevant. Capture sanitized screenshot and minimal interaction observations; don't capture tokens, private user inputs, or raw production paths.
- [ ] Produce a **Task Evidence Packet** with the fields below. Post a brief index in the single PR thread and deliver the packet to the designated owner before any Storyboard design begins. Technical findings stay in the PR thread; Commander control state stays small.

### Task Evidence Packet (per targeted TaskType)

```yaml
# Example schema; evidence values MUST come from an observed real run.
task_type: <canonical task id>
production_environment: <sanitized environment label>
service_deploy_sha: <observed deploy identity>
runner_identity: <observed runtime/SIF/bundle identity, or unknown>
submission:
  task_id: <actual task id>
  api_route: <canonical submission route>
  input_case: <safe test-case reference and content digest>
  accepted_parameters: <sanitized canonical snapshot>
  status: <actual terminal status or blocked>
  output_check: <observed>
publication:
  manifest_schema: 3
  manifest_digest: <observed digest>
  views: <actual declared view IDs and plugins>
  storyboard: <observed declaration or null>
  logical_files: <actual IDs and cardinalities>
  artifacts: <path, role, size, sha256, media type, source association>
scientific_interpretation:
  entities_and_units: <verified from output and pinned method>
  supported_questions: <answerable scientific questions>
  absent_or_uncertain: <explicit limitations>
browser_observation:
  production_result_url: <owner-authorized non-secret URL>
  behavior: <what actually rendered and worked>
  failures: <error, reproduction step, screenshot reference>
  download_fallback: <verified or failed>
owner_assignment: <subagent>
next_gate: READY_FOR_STORYBOARD_DESIGN | BLOCKED
```

- [ ] Sanitize receipts with the existing provenance/replay mechanisms. Preserve provenance references/digests and selected renderer-essential bytes, **not** full output trees or secrets. Do not make screenshot-only or handwritten mock-data evidence canonical.
- [ ] Distinguish `unknown` from zero; distinguish `filtered-out samples` from failed execution; preserve scientific uncertainty. No invented measurements.

## 3. Architecture — Task Storyboard above shared scientific primitives

```text
TaskType (scientific input/parameter/result declaration)
       │
       ▼
Runner → real computation → published approved artifacts
       │
       ▼
ResultManifest v3 + logical result.files + scoped Storyboard declaration
       │                    │
       │            Result Workspace (auth, host, tabs, fallback, provenance)
       │                    │
       └───────────────► Task-owned Storyboard (scientific narrative/composition)
                            │
                      shared primitives and viewer services
                      (molecular / trajectory / matrix / metric / table)
                            │
                   actual interpretable interaction
                   + downloads + diagnostics + limitations
```

- [ ] Core continues to own auth, publication, bounds, MIME/capability projection, file URLs, lifecycle, errors, artifact fallback and standardized contracts; Task/family directories own scientific storytelling, mapping, ranking and domain-specific controls.
- [ ] No task-name/Runner-name branches in `ResultWorkspace`, generic Mol* adapter, shared view registry or server routing. No speculative universal `ScientificResult` god-object, runner-specific server registry, remote executable Storyboards, or new frontend framework.
- [ ] `Storyboard` may compose multiple logical IDs and shared primitives, and may delegate to registered view renderers. Keep it task-specific only where scientific meaning differs. Reuse family Storyboards only when the **verified real outputs and semantics** are identical.
- [ ] Do not attach physical time, probability, confidence, score direction, residue mapping or candidate association unless the pinned scientific method and actual artifacts justify them.
- [ ] Keep Storyboard module assets under the trusted deployed Runner tree; never load executable code from task output; preserve CSP and task-scoped authorization.
- [ ] An unavailable scientific visualization is an explicit unavailable state with details and working artifact downloads, not a silent substitution masquerading as the requested scientific view.

### Shared primitives (build only when production evidence demands them)

- [ ] **Capability parity first:** recover the still-needed generic semantics behind the legacy `candidate-collection`, `entity-table`, `evidence-bundle`, `alignment`, `metric-series`, `matrix`, `scalar-summary` and `trajectory` protocols as reusable typed components, only to the extent that actual production Task results require them. Do not write 40 bespoke Storyboards to hide one missing shared renderer.
- [ ] **Trajectory/ensemble:** explicit topology + coordinates association, selected frame, frame count, scrub/previous/next/play-pause, bounded loading, cancel/teardown, and sample-vs-physical-time semantics; stable structure viewer instance while frames change. Validate Mol* v5.12.0's actual supported trajectory loading APIs before choosing XTC decode route.
- [ ] **Candidate selector:** model identity, count, ranking from published evidence (not lexical filename ordering), selected candidate, structure/score synchronization and missing companion-file behavior.
- [ ] **Quantitative evidence:** bounded table/matrix/series/scalar compositors with units, legends, score direction, uncertainty and selection semantics declared by the method. Do not compute a new biological truth in the browser by heuristic.
- [ ] **Scientific context:** compact method identity, accepted input summary, primary output, caveats, provenance and actionable artifact export.
- [ ] Prefer existing `window.REvoComputeScientific` primitives, `ResultSelectionStore`, `StoryBoardHost` and `MolecularViewer` adapter. Add narrow capability interfaces and clean teardown only where needed.

## 4. First acceptance case: BioEmu (blocking reference implementation)

- [ ] Commander submits the real `bioemu` Task to the production endpoint using a valid test protein FASTA, known nonzero `num_samples` and the deployed Runner's allowed parameters; records actual result and whether samples survive validity filtering. The output observed, **not assumptions**, determines what is built.
- [ ] Owner inspects `topology.pdb`, `samples.xtc`, `task_finished`, manifest association and run caveats; verifies topology/coordinate atom identity and actual frame count before designing.
- [ ] Add Task-owned `docker/runners/bioemu/tasks/bioemu/expected_files.yaml` and `storyboard/{storyboard.yaml,index.js}` **only after** the actual output paths/types/cardinalities have been observed. No silent change to computational output, sample order, or Runner SIF identity.
- [ ] Implement an **Ensemble Explorer**: sample count; persistent Mol* stage; frame/sample selector; previous/next and optional play; clearly labelled "sample index" rather than simulation time; a short scientific caution that generated ensemble samples are not a measured kinetic trajectory or calibrated thermodynamic populations; full XTC/topology exports.
- [ ] Optionally show structural spread/variation only if derived reproducibly with the correct residue/atom alignment and explicit method/provenance. No fictitious energy landscape, time axis, confidence or equilibrium populations.
- [ ] Validate trajectory memory/frame bounds and loading behavior against the real result. If browser-native XTC is unsupported, document a reproducible, bounded, provenance-linked alternative (such as a derived frame-preview representation), without mislabelling it as the original file or changing the scientific output; test the fallback.
- [ ] Browser acceptance must *interact* with at least two distinct observed frames and verify that atom coordinates really change while model identity, controls and downloads remain correct. A visible download link or the first static structure is not sufficient.
- [ ] Exercise missing/empty/mismatched topology, corrupted XTC, zero samples after filtering, cancelled render, unsupported browser, authentication failure, large trajectory, viewer teardown and return to artifact download.
- [ ] This BioEmu slice establishes the protocol and review standard before wider migration.

## 5. Task-oriented design groups (single PR; adaptive assignment)

The Commander assigns **per TaskType**, based on completed evidence packets. These groups are proposed ownership pools, not assertions that the listed Tasks are deployed or ready:

- [ ] **Owner A — BioEmu/trajectory primitive:** BioEmu reference; RFdiffusion trajectory only when Commander verifies actual trajectory output. Exclusive write ownership of shared trajectory viewer interfaces.
- [ ] **Owner B — structure prediction/quality:** AlphaFold, AlphaFold3, ColabFold, ESMFold2, SimpleFold, Boltz, Chai1, Foundry RF3. Preserve existing functioning Storyboards; fix verified deficits rather than re-implementing them.
- [ ] **Owner C — docking, pocket and geometry:** AutoDock Vina/GPU, Gnina, DiffDock, fpocket, P2Rank, DeepPocket, FRoDOCK, GeoDock, MolProbity. Preserve molecular binding geometry and ranking/scoring semantics; do not equate docking score with experimental affinity.
- [ ] **Owner D — sequence design and generative structure:** ProteinMPNN/LigandMPNN variants, FaMPNN, dynamicMPNN, RFdiffusion2, Foundry RFD3/RFD3NA, PLACER, freebindcraft and related candidates. Distinguish sequences, ranked candidate structures and per-candidate evidence.
- [ ] **Owner E — numerical/scientific analysis:** ESM-1v/ESM-MSA/ESM-IF1, PRIME/DMS, PPIformer, Pythia-ddG, GREMLIN/Gremlin_LH, EvoSplit, EASIFA, ThermoMPNN; keep signed metric units, label definitions, residue indexing and score direction from actual results.
- [ ] **Owner F — acceptance/replay/boundary harness:** independently creates sanitized, bounded `reproduced_real_result` evidence replays from Commander receipts and real manifests; Playwright scenario coverage and regression classification. Never substitutes a replay for a new Commander production submission.
- [ ] **Examiner (Examer) — independent browser and screenshot examiner:** independently opens real owner-authorized production Result pages and exact-head candidate replays; exercises actual scientific controls and records before/after screenshots, UX defects and scientific legibility with reproducible steps. Examiner never becomes a feature-implementation Owner or replaces the Adviser.
- [ ] **Independent Campaign Adviser — continuous independent review:** critiques scientifically incorrect interpretations, fake coverage, contract drift, task overlap, excessive abstractions, owner scope, CI and merge claims; adviser feedback is visible to Commander and maintainers.
- [ ] With 6–9 agent slots, keep Commander, Adviser, Examiner and integration/review capacity explicit; do not run every proposed owner simultaneously if their work conflicts or production evidence has not yet arrived.
- [ ] After each group receives evidence, Owner first publishes a **Storyboard spec**: scientific question(s), real logical inputs, output elements, interactions, limits, failure states and proposed browser test. Commander/Adviser check spec against packet before implementation.
- [ ] Every task must end in one honest state: `INTERACTIVE_VERIFIED`, `GENERIC_PREVIEW_JUSTIFIED`, `DOWNLOAD_ONLY_JUSTIFIED`, `BLOCKED_RUNTIME`, `BLOCKED_EVIDENCE`, or `DEFECT_OPEN`. Never convert blocked/unknown into covered to satisfy a checkbox.

### Examiner acceptance protocol (independent of implementation and CI)

- [ ] **Baseline before design.** After Commander personally submits and observes a real production run, Examiner opens the genuine Result page under authorized user access and independently captures the actual initial render, missing controls, errors, and practical scientific questions a user cannot answer. Link sanitized evidence to the Task Evidence Packet. This is a baseline on the deployed revision, not acceptance of the candidate PR.
- [ ] **Candidate acceptance at exact integrated head.** Open the real production frontend build of the candidate branch against sanitized authentic result replay, exercising its views through the real UI. Record the exact head/build identity; do not claim the already deployed production site contains unpromoted fixes.
- [ ] **Interaction before screenshots.** Select models, switch tabs, inspect molecular geometry, verify residue/metric links, manipulate matrices and tables, exercise keyboard focus, and inspect downloads. For BioEmu, use play/pause/previous/next/scrub on at least two genuinely different coordinate frames; screenshots alone cannot demonstrate coordinate change or animation.
- [ ] **Screenshot analysis.** Record viewport dimensions and sanitized initial/interaction/after screenshots, including desktop/mobile and light/dark where materially relevant. Inspect clipped plots/labels, occluded controls, mobile overflow, fullscreen behavior, hierarchy, typography/contrast, legibility of caveats, loading/empty/error states and whether the user can interpret findings without exporting everything locally.
- [ ] **Failure and lifecycle checks.** Verify missing/optional artifact states, interrupted requests, switching candidates and result tabs, viewer disposal/re-entry, errors, retry/recovery, access-denied UX, and continued authenticated direct download. Do not burden shared production with unbounded stress tests.
- [ ] **Canonical review record.** Post one concise per-Task PR-thread report: authentic Task/Evidence Packet reference, exact head and production deploy revision, interaction steps/results, sanitized screenshot references, observed problems with severity, and an explicit verdict EXAMINER_ACCEPTED, EXAMINER_REJECTED or EXAMINER_BLOCKED. The Owner repairs; Examiner re-tests the changed head. No silent self-approval or carrying an old verdict forward.
- [ ] **Production confirmation after explicit approval.** After maintainer-authorized promotion only, Examiner independently re-opens the actual production Result page and verifies the deployed fix. Candidate replay acceptance alone is insufficient to claim deployment.
- [ ] Adviser independently reviews architecture, scope and scientific interpretation; Examiner owns observable UI interaction and screenshot quality. Commander reconciles both verdicts. Neither role substitutes for real execution evidence or maintainer final merge authority.

## 6. Single-PR Campaign integration discipline

- [ ] Create exactly one Task Storyboard campaign PR against up-to-date `main`; include this plan in a **branch-local** `TODO.md`, with explicit expected removal from root before merge. Keep permanent architecture guidance under `docs/` if needed.
- [ ] Commander maintains a narrow state of TaskType → evidence status → owner → blocker category → integration commit/head → Adviser assessment. Details, evidence packets, test failures and findings live in the **single PR thread** and checked-in bounded provenance where appropriate.
- [ ] Assign exclusive writer ownership for shared `frontend/src/features/results/` modules, `revocompute/result_storyboard.py`, schema/OpenAPI, and each `docker/runners/<family>` subtree. Any shared-contract edit is coordinated before owners depend on it.
- [ ] Owners develop on isolated worktrees/local topic branches created from pinned base; integration owner cherry-picks/merges tested owner commits sequentially into the single PR branch; update only after checking conflicts, blast radius and regressions. Do not have agents concurrently commit to the same branch checked out in different worktrees.
- [ ] Commander does **not** author feature patches. It personally submits/observes production tasks, issues evidence packets, schedules owners, arbitrates conflicts, enforces acceptance and hands off. Production submission is this campaign's intentional, narrowly defined exception to its normal quiescent control-plane role.
- [ ] For each task, record a concise PR-thread acceptance row: TaskType; submitted production task ID; result/manifest digest; output-check; chosen Storyboard behavior; real-result replay ID; independent Examiner browser/screenshot verdict; limitations; exact integrated SHA; owner; Adviser judgment.
- [ ] No blanket “all green” based on static YAML audits, unit tests, CI passing, or one representative Task. Scientific output acceptance, browser replay and production presentation observation are separate claims.
- [ ] Do not merge, deploy a changed image/runtime, mutate auth policy, or alter production scheduler configuration without the maintainer's explicit authorization. Running permitted bounded scientific test tasks through ordinary authenticated production APIs is the required campaign activity.

## 7. Verification gates and definition of done

- [ ] **Gate 0 — inventory:** exact-head discovered 56-task baseline refreshed; each targeted Task classified; API/renderer/Storyboard discrepancies enumerated.
- [ ] **Gate 1 — real execution:** for every TaskType actually implemented, Commander-created production Task ID with valid output check or an explicit blocked reason; actual artefact identity and semantics inspected.
- [ ] **Gate 2 — storyboard design:** owner spec derived from the observed outputs; names, units, associations, warning language and interactions signed off by scientific reviewer/Adviser.
- [ ] **Gate 3 — implementation:** no task-ID conditionals in Core, no fake fallback; the targeted Task meets its own scientific interaction acceptance, not only manifest validity.
- [ ] **Gate 4 — replay/browser:** authentic source-derived, sanitized, bounded replay; Playwright verifies visible scientific answer and at least one method-specific interaction, not simply URL/DOM existence; negative cases and teardown also exercised. Examiner independently manipulates the real candidate-head browser, analyzes before/after screenshots and confirms observed dynamic/selection state.
- [ ] **Gate 5 — production observation:** after authorized candidate promotion, Commander and Examiner independently open the *actual* Result page for an authentic Task on that deployed revision. Distinguish deployment to production from an earlier baseline run; do not confuse version identities.
- [ ] **Gate 6 — fleet/regression:** `python -m revocompute doctor --config-root docker/runners --strict` (or actual documented per-runner syntax), `make test-boundaries`, `make runner-fast`, `make test-fleet`, frontend typecheck/unit/build, relevant Playwright scientific storyboard/replay suites, output contract tests, and `mkdocs build --strict`; verify existing AlphaFold/Boltz/fpocket/GREMLIN/Foundry storyboard functionality stays intact.
- [ ] Revisit target-host live-test receipt whenever a result output contract, view selector, runtime input, bundle or SIF changes, consistent with `docs/runner-guide/adding-a-runner.md`. Presentation-only changes do not require needless SIF rebuilds, but **still require browser-level scientific acceptance**.
- [ ] **Gate 7 — independent review:** Examiner signs off exact-head browser interaction and visual evidence; Adviser and focused reviewers validate the exact integrated head, source/file ownership, error paths, scientific limitations, and absence of implicit result inference. Resolve all P0/P1 findings and either fix or explicitly defer bounded P2 findings with maintainer consent.
- [ ] **Gate 8 — handoff:** single PR reaches `READY_FOR_FINAL_REVIEW`, with scope-complete task ledger, actual production task evidence, CI at exact head, replay links/digests, Examiner verdict and sanitized screenshot evidence, remaining limits, and short maintainer summary. Remove temporary root `TODO.md`. **Stop: do not squash-merge.**

## 8. Hard stop conditions

Stop the affected Task, not the entire independent Campaign, when:

- the production Task cannot be submitted/observed through authorized APIs;
- result identity, model/trajectory association, units or scientific semantics cannot be established from real outputs and pinned upstream code;
- the only path to "success" is to fake/handwrite an output or quietly rename a missing interaction as a static download;
- a change would modify the scientific computation, Runner runtime identity, publication trust boundary or resource policies outside approved scope;
- the required live run is too costly or disruptive for the agreed production window;
- owner and integration branch revisions no longer match the reviewed exact head.

Record the blocker, owner and next action in the PR. Continue unrelated tasks that have verified production evidence.

## Baseline references

- `frontend/src/features/results/ResultWorkspace.ts`, `storyboard-host.ts`, `molecular/viewer-contract.ts`, `renderer-registry.ts`
- `revocompute/result_storyboard.py`, `result_projection.py`, `result_audit.py`
- `docker/runners/bioemu/tasks/bioemu/task.yaml`, `run.sh`, `test.yaml`
- `docs/developer-guide/result-view-plugins.md`, `result-view-protocols.md`, `testing.md`
- `docs/runner-guide/adding-a-runner.md`
- PR #32 (Vite/Mol* cutover), #44 (real-result replay), #88 (Daylight Bench), #92 (scientific contract audit), #93 (Task-scoped result contracts), #99 (contract boundary hardening)