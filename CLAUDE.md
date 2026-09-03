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
- Never vendor third-party frontend libraries. Pin Python packages only after verifying real distribution channels and wheel compatibility.
- For CUDA runners, match builder/runtime images and compiled wheels to the same CUDA minor version. Preserve validated dependency stacks in isolated runner images unless a runner-specific test requires a change.

## Repository conventions

- Repository root: `/repo/REvoCompute`; source package: `revocompute/`; tests: `tests/`; deployment controller: `run/restart.sh` and `run/revocompute_ctl/`.
- Python requires 3.12+. Python files use `from __future__ import annotations`, 120-column formatting, and GPL-3.0-only headers.
- Keep test files focused and use repository-root paths via `Path(__file__).resolve().parents[1]` from files under `tests/`.
- Run `make test`, `make test-cov`, and the relevant Docker/Compose smoke tests. Validate shell syntax for changed scripts and render Compose files with safe example values.
- Before broad formatting, checkpoint intended changes, inspect the resulting diff for collateral rewrites, and run focused tests against the final code.

## Workflow and review discipline

- Use test-case-driven fixes for live and integration defects: encode the observed behavior in the smallest focused test, make the smallest production change, and run the focused gate before the broader suite.
- Keep commits coherent and checkpoint working states before deployment or broad mechanical changes. Do not include unrelated user work from a dirty worktree.
- Do not repeatedly trigger automated reviews. Request one review pass, batch valid findings, and verify locally between pushes. Request another pass only when a material redesign genuinely warrants it.
- Treat CI, review feedback, deployment, and living tests as one delivery loop. Diagnose unchanged-code CI failures as possible environment regressions before changing product code.
- For server changes, verify the real path through API, worker, SLURM, and Apptainer. Monitor the SLURM job and validate status, manifest, logs, and required artifacts through the public API.
- Keep credentials out of commands, logs, commits, and status reports. Store transient tokens in mode-`0600` temporary files and remove them when the live test is complete.

## Runner intake and DBTL

New runners require a task registry entry, runner YAML, Dockerfile, `run.sh`, definition file, contract tests, and a minimal reproducible run. Record the pinned source commit, license, hardware, inputs, parameters, outputs, weights, dependency versions, and resource limits before implementation.

Follow Design-Build-Test-Learn: design the contract, build a candidate image, run real Docker and (where applicable) SLURM/Apptainer smoke tests through the API, then record version and resource lessons. The living test must use a minimal safe input and record effective walltime plus CPU, host-memory, GPU-memory, and GPU-utilization observations. Keep the server authoritative and keep runner-specific legacy pins isolated.
