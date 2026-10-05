# Independent Campaign Advisor

## Objective

Add an **Independent Campaign Advisor** to the multi-agent Campaign protocol.

The Advisor observes the Campaign across its full lifecycle and independently evaluates whether the Commander is still driving the shortest correct path to merge. It exists to catch scope drift, artificial dependencies, excessive evidence, coordination churn, and governance overhead that the Commander may not notice while operating the Campaign.

The Advisor is not another reviewer or approval layer.

## 1. Organizational independence

The relationship is:

~~~
                    Human
                   /     \
                  /       \
         Commander       Advisor
             |               |
      owners/reviewers       |
             |               |
             +--- Campaign --+
~~~

The Advisor:

- is outside the Commander's authority;
- is not assigned work by the Commander;
- is not part of the Commander's ordinary implementation/review scheduling pool;
- reports material advice directly to the human and may also notify the Commander;
- forms its judgment from primary repository/Campaign evidence, not only Commander summaries.

The Commander must not repurpose the Advisor as an implementation owner, ordinary reviewer, reserve agent, deployment operator, or merge agent.

The Advisor must not assign owners/reviewers, acquire deployment leases, edit implementation PRs by default, merge/close PRs, or become a second Commander.

Platform-wide hard concurrency limits still apply.

## 2. Distinct objective

Make the role split explicit:

~~~
Owner      -> optimize implementation
Reviewer   -> optimize implementation correctness
Commander  -> optimize safe Campaign delivery and merge throughput
Advisor    -> optimize direction and minimize unnecessary work / coordination entropy
~~~

The Advisor's governing question is:

> Is the Campaign still solving the right problem by the shortest correct path?

It should preferentially identify work that can be removed, narrowed, deferred, collapsed into another PR, converted from a hard dependency into a final-integration dependency, or supported by a smaller evidence set.

The Advisor is not rewarded for inventing more tasks.

## 3. What the Advisor evaluates

### Scope

Challenge whether:

- a PR still serves its useful product goal;
- a PR is validating behavior owned by a third party;
- an acceptance claim exceeds REvoCompute's responsibility;
- a small feature is turning into a framework without need;
- a PR should be narrowed, collapsed, deferred, or closed.

### Dependencies

Challenge whether:

- a dependency is truly a hard implementation dependency;
- downstream work could proceed with only final integration blocked;
- a shared resource is being mistaken for a whole-PR dependency;
- the critical path is unnecessarily serial.

### Evidence proportionality

For each major claim ask:

~~~
what exactly does this PR claim?
what is the minimum sufficient independently reviewable evidence?
~~~

Flag both insufficient evidence and excessive evidence for an unnecessary claim.

### Campaign throughput

Observe signals such as:

- open versus merged PR count;
- age of merge-near PRs;
- conceptual review round trips;
- blocked/idle time;
- rebase/recovery churn;
- temporary branch proliferation;
- repeated live executions;
- diff/scope growth;
- new governance/meta-work;
- practical merge distance.

These are diagnostic signals, not rigid thresholds.

## 4. Lifecycle

The Advisor spans the whole Campaign, but is not a mandatory gate on every PR.

### Campaign start

Independently review the Campaign goal, PR/TODO scopes, dependency DAG, expected evidence cost, critical path, and likely over-scope.

Produce a short advisory identifying likely bottlenecks, artificial dependencies, and high-cost claims.

### Mid-Campaign health review

After meaningful accumulated work, assess:

- actual progress versus plan;
- merge throughput;
- review churn;
- scope drift;
- coordination overhead;
- blocked time;
- whether protocol compliance is displacing delivery.

### Pre-close review

Before Campaign completion, assess:

- whether the original goal was achieved;
- whether any PR/branch has lost independent value;
- whether temporary state is cleaned up;
- which lessons deserve durable protocol changes;
- which issues are one-off and should not become policy.

Do not automatically create governance work for every lesson.

## 5. Event-triggered advisories

The Advisor may inspect out of cycle when, for example:

- a PR receives more than one new conceptual blocker across review rounds;
- implementation expands materially beyond the original goal;
- a PR starts introducing a general framework;
- a large fixture/evidence tree appears;
- an expensive deployment/GPU/live run is about to be repeated;
- open PR count stops falling while review activity grows;
- blocked PRs dominate actionable work;
- temporary branches accumulate;
- the Commander materially changes the DAG or acceptance strategy;
- new governance/meta work is proposed during an active Campaign;
- the human requests an independent health check.

These trigger inspection, not automatic failure.

## 6. Advisory output

Use a concise decision-oriented form:

~~~
CAMPAIGN ADVISORY

Health:
ON TRACK | WATCH | INTERVENE

Observation:
...

Why it matters:
...

Recommendation:
...

Commander response:
ACCEPT | PARTIAL + rationale | REJECT + rationale
~~~

Order multiple findings by Campaign impact.

The Advisor should identify the shortest correct path, not enumerate every possible improvement.

## 7. Relationship with Commander

Advisor findings are non-blocking by default.

The Commander remains responsible for scheduling and execution and should acknowledge material advice with ACCEPT, PARTIAL + rationale, or REJECT + rationale.

If the Commander rejects material advice, preserve both the advisory and the rationale for the human.

The Advisor must not silently take over coordination.

## 8. Escalation

The Advisor may escalate directly to the human only for Campaign-level red flags such as:

- the Campaign is solving the wrong problem;
- a scientific/product claim materially exceeds evidence;
- a major irreversible architecture choice lacks justification;
- security/privacy risk;
- the Campaign is clearly stalled and local review loops are not converging;
- a material blocker is repeatedly ignored without rationale.

Escalation asks for a human decision. It does not grant veto or merge authority.

## 9. Independent evidence

The Advisor must not rely exclusively on Commander summaries.

For health reviews, independently inspect enough primary evidence to challenge strategy, including as relevant:

- Campaign instructions;
- PR bodies and TODOs;
- current heads/diffs;
- important review findings;
- CI/live acceptance;
- dependency relationships;
- branch inventory.

Deep line-by-line review is not required unless the Campaign-level question needs it.

## 10. Anti-bureaucracy constraints

Do not create:

~~~
Owner -> Reviewer -> Advisor -> Commander -> Human -> Merge
~~~

Advisor approval must not be required before ordinary review, merge, checkpoints, deployment, or routine fixes.

Do not create an Advisor checklist on every PR.

Do not turn every advisory into a new issue or PR.

Prefer subtraction.

A useful Advisor often says:

~~~
do less
narrow the claim
merge the nearly-finished PR first
this dependency is only final-integration
this framework is unnecessary
this evidence can be smaller
~~~

## 11. Merge-oriented coordination

The Commander should continue estimating practical merge distance:

~~~
PR | remaining blockers | conceptual steps to merge
~~~

The Advisor may challenge the estimate when a blocker is artificial, scope should shrink, a "small" step expands the claim, or a merge-near PR is being starved by lower-value work.

Call out when the Campaign is maximizing activity instead of reducing merge distance.

## 12. Scope of this PR

This is governance documentation only.

Do not add a runtime agent framework, orchestration service, CI, GitHub bot, merge permission, mandatory approval gate, or larger implementation-agent budget.

Integrate the Advisor into the existing Campaign guidance with the smallest coherent documentation change.

If another Campaign-document PR (for example branch-lifecycle guidance) lands first, reconcile after it merges rather than overwriting it.

This PR must not become a dependency of the current implementation Campaign.

## Acceptance

The final guidance must make all of these explicit:

1. Advisor is organizationally independent of Commander.
2. Advisor observes the full Campaign lifecycle.
3. Advisor optimizes direction and reduction of unnecessary work.
4. Commander cannot use it as an ordinary implementation/review slot.
5. Advisor has no implementation, deployment, merge, or routine approval authority.
6. Advisor independently inspects primary Campaign evidence.
7. It performs start, mid-Campaign, and pre-close health reviews.
8. It can issue event-triggered advisories.
9. Advisories are non-blocking by default.
10. Material disagreement remains visible to the human.
11. Exceptional Campaign-level risks may be escalated to the human.
12. No new mandatory approval chain is introduced.
13. The protocol explicitly prefers faster safe convergence and fewer unnecessary tasks over governance accumulation.

Run:

~~~
mkdocs build --strict
git diff --check
~~~

and the repository's expected documentation-only CI path.

Bring the exact head to READY_FOR_FINAL_REVIEW.
