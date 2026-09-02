# CLAUDE.md

Guidance for work in the standalone REvoCompute repository.

## Engineering principles

- Keep implementations simple, end-to-end, and modular. Remove obsolete paths rather than adding compatibility layers or speculative abstractions.
- The server is the single source of truth for task definitions, schemas, extensions, resource policies, and scientific constants. Do not duplicate YAML/Python configuration in JavaScript; expose server-owned data through APIs.
- Never vendor third-party frontend libraries. Pin Python packages only after verifying real distribution channels and wheel compatibility.
- For CUDA runners, match builder/runtime images and compiled wheels to the same CUDA minor version. Preserve validated dependency stacks in isolated runner images unless a runner-specific test requires a change.

## Repository conventions

- Repository root: `/repo/REvoCompute`; source package: `revocompute/`; tests: `tests/`; deployment controller: `run/restart.sh` and `run/revocompute_ctl/`.
- Python requires 3.12+. Python files use `from __future__ import annotations`, 120-column formatting, and GPL-3.0-only headers.
- Keep test files focused and use repository-root paths via `Path(__file__).resolve().parents[1]` from files under `tests/`.
- Run `make test`, `make test-cov`, and the relevant Docker/Compose smoke tests. Validate shell syntax for changed scripts and render Compose files with safe example values.
- Before broad formatting, checkpoint intended changes, inspect the resulting diff for collateral rewrites, and run focused tests against the final code.

## Runner intake and DBTL

New runners require a task registry entry, runner YAML, Dockerfile, `run.sh`, definition file, contract tests, and a minimal reproducible run. Record the pinned source commit, license, hardware, inputs, parameters, outputs, weights, dependency versions, and resource limits before implementation.

Follow Design-Build-Test-Learn: design the contract, build a candidate image, run real Docker and (where applicable) SLURM/Apptainer smoke tests through the API, then record version and resource lessons. Keep the server authoritative and keep runner-specific legacy pins isolated.
