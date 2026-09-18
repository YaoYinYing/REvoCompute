---
name: revocompute-performance
description: Use when asked to make REvoCompute faster, to profile slow API routes or scheduler/worker paths, to design a performance measurement or regression gate, or to turn performance evidence into a behavior-preserving optimization. Covers the server, the runner dispatch path, the browser suite, and the frontend assets.
---

# Speeding Up REvoCompute

Turn "make it faster" into reproducible measurements and small, evidence-backed
fixes. This is guidance, not a quota: survey broadly, follow measured cost, and
reject attractive changes that do not improve the workload users actually run.

Read [`CLAUDE.md`](../../../CLAUDE.md), the
[architecture invariants](../../../docs/agents/architecture-invariants.md), and
[architecture](../../../docs/developer-guide/architecture.md) first. Performance
work does not exempt you from the ownership rules there.

## Establish scope

Agree on the user-visible endpoint, the workload range, the resource limits, and
the stopping rule before touching code. Name what is excluded: model and network
latency, SIF build time, and scheduler queue wait are usually not the cost being
optimized, and a measurement that includes them is not a product latency claim.

Keep the layers separate. A fast API route does not prove a fast page, and a fast
page does not prove fast dispatch, SLURM startup, or Apptainer launch. Measure
the layer you are changing, and say which layers are out of scope.

## Rank candidates before optimizing

Survey the paths users actually take:

- Submission: validation, schema resolution, input snapshot, artifact hashing.
- Monitoring: status polling, log streaming, operational events, result reads.
- Dispatch: task runtime, resource policy, SLURM submission, runner preparation.
- Browser: first paint, long task and result pages, live status updates, scrolling.

For each candidate name the production consumer, the repeated work, the expected
complexity, and the smallest falsifiable intervention. A suspicious loop or a
large file is not evidence of a bottleneck. Rank by observed latency, occurrence,
and confidence, then start at the top.

## Measure before you change anything

Write down the measurement card before implementing:

| Field | Decision |
| --- | --- |
| User operation | Exact action and externally observable completion condition |
| Workload | Fixed dimensions and construction constants, and why it exercises ordinary and tail use |
| Entry path | The real production call path; which boundaries are mocked |
| Clock | What is included, cold or warm state, start and end points, excluded costs |
| Memory | What must stay reachable, baseline, retained versus transient limits |
| Verdict | Raw samples, the deciding aggregate, and the negative control |
| Behavior | Owning tests that must stay green |

Generate fixed inputs from reviewed constants. Never copy user submissions,
prompts, paths, identities, tokens, or recognizable snippets into fixtures,
logs, or PR text. A benchmark must not depend on the operator's home directory,
the ambient repository, a network service, or private data.

Measure the real path: the HTTP API and the worker for server work, built assets
and the browser suite (`make test-browser`) for frontend responsiveness, and the
inspectable `run/restart.sh` and Compose lifecycle for deployment claims. Do not
add a production export purely for measurement, and do not copy the algorithm
into a "benchmark implementation" — that measures the copy, not the product.

Report every sample, not only the best one. Compare reference and candidate under
comparable conditions, and do not select a lucky run or widen a threshold to hide
a regression.

## Prove the regression, then remove work

Run the unoptimized workload first and save the command, revision, dimensions,
raw measurements, and verdict. Reduce a failing scenario until it still exercises
the real bottleneck, then rank falsifiable hypotheses and use profiles, work
counts, or phase timings to distinguish them.

Patterns worth testing, not automatic prescriptions:

- Remove duplicate parsing, copying, serialization, or hashing once you have
  identified the actual ownership and trust boundary. Same-process borrowing is
  not permission to weaken input validation or durable-format parsing.
- Stream or bound intermediate state instead of retaining every generation;
  include publication and verification obligations the operation requires.
- Prefer the right data structure over repeated scanning or rebuilding, and
  measure the whole consumer path, not the isolated container operation.
- Cache only with explicit invalidation, bounded retention, and a named owner.
  A cache that makes a repeated benchmark look fast has measured nothing.
- Defer work that no one observes yet, then re-measure first access and retained
  state. Deferral is not deletion.

Change one causal factor at a time, then re-run both the focused scenario and its
end-to-end parent. Require a negative control: the tightened assertion must fail
on the original code, or on a controlled reintroduction of the targeted cost. A
threshold generous enough to pass the regression is not protection.

## Preserve behavior and resource ownership

Performance evidence complements functional evidence; it never replaces it. Run
the owning tests for ordering, paging, errors, cancellation, concurrency, and
cleanup. Preserve the immutability of stored inputs and hashes, atomic status
transitions, required validation, and runner readiness semantics. Do not skip
validation, truncate results, or change lifecycle behavior to reach a number.

Reject an optimization when the gain disappears end-to-end, when a typical
workload regresses, when complexity outweighs a small win, or when cancellation,
retention, or durability cannot be explained and tested. Record the rejected
hypothesis briefly instead of expanding scope to justify it.

## Deliver a bounded result

Run [`make test`](../../../Makefile) and the narrow owning tests, plus
`mkdocs build --strict` if a page changed and `git diff --check`. For a
deployment-affecting change, render the Compose files with safe example values
and check shell syntax. Do not re-push before verifying locally.

Summarize as: workload → before/after absolute values and ratio → endpoint and
memory semantics → behavior evidence → negative control → exact checks run →
exclusions. Keep fresh measurements, historical numbers, and CI evidence separate,
and stop at the agreed scope with a short ranked follow-up list.
