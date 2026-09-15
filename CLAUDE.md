# CLAUDE.md

Guidance for work in the standalone REvoCompute repository.

## Maintenance strategy

- Keep this file concise and limited to project-invariant guidance that prevents repeated mistakes.
- Add durable learnings after substantial work, prune low-value or stale guidance, and move detailed procedures into focused documentation when it exists.
- Treat `CLAUDE.md` as the canonical agent guidance. `AGENTS.md` mirrors it so every supported coding agent receives the same rules.

## Engineering principles

- Keep implementations simple, end-to-end, and modular. Remove obsolete paths rather than adding compatibility layers or speculative abstractions.
- Grow the system in working layers. Each new capability should leave an end-to-end product that can be exercised before more complexity is added.
- Prefer established, maintained libraries and existing project dependencies when they reduce complexity. Check their documentation and types before assuming a capability is missing.
- Make long-term architectural decisions; do not introduce a known stopgap that is intended to be replaced later.
- The server is the single source of truth for task definitions, schemas, extensions, resource policies, and scientific constants. Do not duplicate YAML/Python configuration in JavaScript; expose server-owned data through APIs.
- Each owning `task.yaml` is the sole authoritative source of user-facing Task parameter vocabulary and semantics. Project it through server APIs and resolved Runner inputs; never duplicate defaults or parameter help in Core, frontend code, `runner.yaml`, adapters, or Markdown.
- Never vendor third-party frontend libraries. Pin Python packages only after verifying real distribution channels and wheel compatibility.
- For CUDA runners, match the direct Apptainer base and compiled wheels to the same CUDA minor version. Preserve validated dependency stacks in isolated SIFs unless a runner-specific test requires a change.
- For long-running engineering tasks, read `LONG_TASK_HANDLING.md` for methodology guidance.

## Repository conventions

- Repository root: `/repo/REvoCompute`; source package: `revocompute/`; tests: `tests/`; deployment controller: `run/restart.sh` and `run/revocompute_ctl/`.
- Python requires 3.12+. Python files use `from __future__ import annotations`, 120-column formatting, and GPL-3.0-only headers.
- Keep test files focused and use repository-root paths via `Path(__file__).resolve().parents[1]` from files under `tests/`.
- Run `make test`, `make test-cov`, and the relevant Docker/Compose smoke tests. Validate shell syntax for changed scripts and render Compose files with safe example values.
- Before broad formatting, checkpoint intended changes, inspect the resulting diff for collateral rewrites, and run focused tests against the final code.
- Documentation has one owner per page under `docs/`; the site is the single source of truth. Never add a root-level guide that duplicates a `docs/` page, and run `mkdocs build --strict` after changing any page or `mkdocs.yml`. See `docs/developer-guide/documentation.md`.

## Task input contracts

- Task inputs are named roles, not positional files. Never assign scientific meaning from upload order, filenames, or extensions alone, and do not add flat `primary_input_extensions`-style contracts.
- Each owning `task.yaml` declares stable role IDs, display labels, logical data types, accepted formats, and per-role cardinality. The Server projects that contract into the API, UI, immutable input manifest, artifact reuse, and Runner dispatch.
- Keep transport safety, format parsing, logical role validation, neutral normalization, and Runner scientific preparation separate. Generic Server validation must not silently protonate, assign charges, atom-type, minimize, or otherwise alter scientific interpretation.
- Preserve original user inputs and hashes as an immutable role-resolved snapshot. Runner-prepared files and preparation logs are separate provenance artifacts and must never replace originals.

## Testing policy

- Test behavior, not repository text. Do not add tests that read static Runner or Server files merely to assert deps, SIF directives, YAML/JSON declarations, JS, CSS, HTML, workflow text, dependency pins, paths, or documentation; snapshots of those assets are the same anti-pattern. Real parsers, schemas, linters, builders, executors, HTTP behavior, DOM/browser behavior, and public APIs are valid consumers.
- Server-owned behavior belongs under `tests/server/` and should use synthetic Runner fixtures when production Runner identity is irrelevant. Cross-component protocol behavior belongs under `tests/integration/`.
- Runner unit tests are only for Runner-owned executable logic such as parsers, converters, normalizers, command builders, or postprocessors, under `tests/runners/<runner>/`. A declarative Runner may have no pytest tests.
- Runner runtime correctness comes from SIF build/`%test`, Doctor, smoke tests, target-host live acceptance, scientific outputs, and exact receipts—not pytest assertions about `task.yaml`, `plugin.yaml`, `test.yaml`, SIF, deps, shell text, or frontend source.
- Lower test count or coverage after deleting self-confirming tests is acceptable. Keep meaningful API, auth, registry, readiness, scheduler, artifact, persistence, and input-contract behavior coverage; do not add ceremony tests to restore a number.

## Tool execution

- Tools are authenticated, short-lived, CPU-only utilities executed by the dedicated Tool worker, never by web handlers or Slurm. They accept only typed named inputs and bounded parameters; never execute user code or expose network/GPU controls.
- Tool runtime families start lazily, run each call in a fresh child process, and stop after an idle timeout. COLD is available; warmth is an optimization rather than readiness or durable state.
- Tool workspaces and rows are ephemeral. A Tool output becomes durable only when the Server copies and verifies it into an immutable Task input snapshot with Tool/runtime provenance.
- Keep neutral inspection/conversion distinct from protonation, charge assignment, atom typing, minimization, inference, and other scientific preparation. Test Tool behavior and runtime execution, never literal manifest, recipe, script, or documentation contents.

## Workflow and review discipline

- Use test-case-driven fixes for live and integration defects: encode the observed behavior in the smallest focused test, make the smallest production change, and run the focused gate before the broader suite.
- Keep commits coherent and checkpoint working states before deployment or broad mechanical changes. Do not include unrelated user work from a dirty worktree.
- Do not repeatedly trigger automated reviews. Request one review pass, batch valid findings, and verify locally between pushes. Request another pass only when a material redesign genuinely warrants it.
- Treat CI, review feedback, deployment, and living tests as one delivery loop. Diagnose unchanged-code CI failures as possible environment regressions before changing product code.
- For server changes, verify the real path through API, worker, SLURM, and Apptainer. Monitor the SLURM job and validate status, manifest, logs, and required artifacts through the public API.
- Keep credentials out of commands, logs, commits, and status reports. Store transient tokens in mode-`0600` temporary files and remove them when the live test is complete.
- When a required production accelerator is occupied, use `squeue` to identify the blocking job and inspect available metadata with `scontrol show job <jobid>` before deciding whether to wait. Scheduler visibility is not scheduler understanding: consider fields such as job name/state, runtime/time limit, start/end time, command, work directory, reason, and GPU allocation. Defer accelerator-dependent validation immediately for an obviously long workload such as production molecular dynamics. If duration remains unclear, wait ten minutes once, inspect with both commands once more, then either proceed or defer for the current delivery; never enter an indefinite polling loop or interfere with another user's job.

## Runner intake and DBTL

New runners are self-contained under `docker/runners/<family>/` with a plugin manifest, task manifests, `runner.yaml`, direct Apptainer definition, `run.sh`, family `test.yaml`, contract tests, and a minimal reproducible run. No central task-registry entry is required. Record the pinned source commit, license, hardware, inputs, parameters, outputs, weights, dependency versions, and resource limits before implementation.

Follow Design-Build-Test-Learn: design the contract, build a candidate SIF directly with Apptainer, run real SLURM/Apptainer smoke tests through the API, then record version and resource lessons. Docker/Compose remains the server deployment gate. The living test must use a minimal safe input and record effective walltime plus CPU, host-memory, GPU-memory, and GPU-utilization observations. Keep the server authoritative and keep runner-specific legacy pins isolated.
