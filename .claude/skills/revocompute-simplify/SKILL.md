---
name: revocompute-simplify
description: Use when asked to find simplifications, delete dead or speculative code, remove duplicated representations of a fact, prune unused runner/task manifests or API surface, replace hand-rolled code with a dependency, or review a diff for over-engineering in REvoCompute.
---

# Finding REvoCompute Simplifications

Turn a broad "find things to simplify" request into evidence-backed candidates
that remove or collapse real surface area. This is guidance, not a checklist:
follow the code, keep judgment active, and prefer a few well-proven candidates
over a pile of thin guesses.

Read [`CLAUDE.md`](../../../CLAUDE.md) first, then
[architecture invariants](../../../docs/agents/architecture-invariants.md) and
[testing](../../../docs/developer-guide/testing.md). Simplifications that fight a
stated ownership rule need extra evidence, not less.

## What counts as a strong candidate

A strong candidate removes, folds, or demotes something real, with clear
evidence that the current design costs more than it buys:

- A route, config knob, plugin hook, helper, or adapter has no production caller.
- Tests or docs are the only consumers and the behavior they pin is not
  load-bearing.
- Two representations mirror the same fact — a default mirrored from `task.yaml`
  into frontend JavaScript, or a runner constraint restated in `runner.yaml` and
  an adapter.
- A plugin or manifest declares capability no runner or task uses.
- A feature implements speculative generality with no product owner.
- Hand-rolled code reimplements what the standard library or an existing project
  dependency already provides.

Thin candidates are not worth a proposal: a single typo, "this looks complex"
without call-site proof, or deleting an intentionally documented runner,
adapter, or input role.

## Survey broadly

Cover these domains — use parallel subagents when the request asks for breadth,
and require evidence rather than guesses:

- Core server: `revocompute/` routes, plugins, task types, schemas, storage.
- Runtime: `docker/runners/<family>/` manifests, `run.sh`, definitions, adapters.
- Tool runtimes: `docker/tools/<family>/` manifests and entrypoints. The Tool
  worker mounts this tree read-only and `ToolRegistry.discover` globs its
  `*/plugin.yaml`, so a field found only here still has a production consumer.
- Frontend: `revocompute/static/` JavaScript, CSS, and templates.
- Tests and docs: `tests/`, `docs/`, generated assets.
- Deployment: `run/revocompute_ctl/`, Compose files, env surfaces.

Start with the largest production deltas. An audit that stops after obvious
unused symbols misses the files where duplicated lifecycle or validation
machinery carries most of the cost.

## Prove or reject each candidate

Classify consumers before writing anything:

- Production: `revocompute/`, `docker/runners/`, `docker/tools/`, `run/`,
  deployed `runner.yaml`, and the Compose service definitions.
- Non-production: `tests/`, `docs/`, `tools/`, README files, comments.
- Ambiguous: scripts and fixtures that may be real smoke paths. Inspect usage.

Search the exact symbol first — the name, the route, the config key, the manifest
field, and any wire string — then read the call sites. Grep hits in tests and
docs do not establish a production consumer, and absence of grep hits does not
prove a route is unreachable; check dynamic registration and plugin discovery.

Reject or downgrade when:

- A production caller exists and removing it would be a product decision.
- The design is justified by `CLAUDE.md`, an architecture invariant, or a
  recorded scientific contract, and the new evidence does not beat that reason.
- The removal forces unrelated churn without reducing public API or behavior.
- The idea is correct but tiny — leave a short `TODO` instead.

## Audit trust and lifecycle boundaries

For every defensive copy, re-validation, or fallback, name where the value came
from and who owns it next. Same-process typed calls normally borrow read-only
values; the command line, uploaded files, environment configuration, workers,
SLURM, database rows, and wire responses own or validate their data. Keep a check
when it compares independently produced observations that can diverge. Remove one
that only re-inspects a value the same function just produced.

## Hand-rolled versus a dependency

Introducing a dependency is a valid simplification move, not an exception — but
prove it like any other candidate:

- Name the exact surface the package or standard-library call covers, and record
  the residual semantics it does not.
- Check its health, maintenance, and footprint. Prefer the standard library.
- Weigh net deletion: implementation plus its dedicated tests plus docs, minus
  the glue that remains. A wrapper that relocates the same complexity is not a
  win.
- Verify a real distribution channel and wheel or wheel-free compatibility
  before pinning (`CLAUDE.md`, dependency rules).

## Write the proposal

One durable proposal per topic. Record it in the maintainer backlog — `TODO.md`
or a focused `TODO_*.md` — not in a new root-level guide, which the documentation
workflow rejects.

Structure it as: the current API and its files, the consumer evidence separating
production from tests and docs, exactly what to remove or fold including manifest,
schema, snapshot, and documentation cleanup, the strongest argument for keeping
it, the observable end state and gates, and the risks. Be concrete enough that an
implementing change can follow the trail.

For a small, local cleanup that needs no design decision, leave a short tagged
comment instead: name the smell, why it is safe to revisit, and the action.

## Prose moves with the code

Treat comments and documentation as maintained surface area. Apply
[revocompute-prose](../revocompute-prose/SKILL.md) to any prose in scope — a
deleted API leaves stale comments behind, and those are part of the deletion.

## Validation

Run the root gates — [`make test`](../../../Makefile) and `make test-cov` — plus
the narrow owning tests for anything you change. For a real removal, prove the
negative condition through the real path: the API no longer exposes it, and
production no longer depends on it. Self-authored tests alone are not sufficient
evidence — see the long-task protocol below.

When opening or updating a PR, summarize how many proposals were added, retained,
or rejected, the areas surveyed, what was intentionally excluded, and which checks
passed. Use a draft PR while the survey is still expanding.

## Related

For work that is a large architectural migration rather than a cleanup, follow
[long-task handling](../../../docs/agents/long-task-handling.md) instead: it owns
the phase, checklist, and completion-evidence rules.
