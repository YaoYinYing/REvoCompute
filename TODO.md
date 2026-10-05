# Bounded Evidence and Fixture Discipline

## Objective

Extend the repository guidance established by PR #41 and PR #49 with one missing
review principle:

> reproducibility does not imply committing an entire runtime output directory.

Campaign owners and reviewers must keep durable evidence **proportional to the
claim being proved**. A scientific reference, frontend replay bundle, or
production acceptance record should preserve the smallest sufficient,
independently auditable evidence set rather than snapshotting every generated
file by default.

This is a documentation/guidance-only follow-up. Do not change product runtime
behavior.

---

## 0. Scope and boundaries

Expected implementation scope:

```text
LONG_TASK_HANDLING.md
TODO.md
```

Only touch `CLAUDE.md` / `AGENTS.md` if a genuinely new project-wide invariant
cannot be discovered through the existing instruction to follow
`LONG_TASK_HANDLING.md`. Prefer not to touch them.

Do not modify:

- Runner behavior;
- frontend/server code;
- CI behavior;
- deployment tooling;
- fixture files themselves;
- current Campaign concurrency/authority rules;
- merge permissions;
- the dynamic orchestration rules added by PR #49.

Do not add a generic artifact store or Git LFS policy in this PR.

---

## 1. Add an evidence-footprint rule

Add a concise section to the Multi-agent Campaign Protocol / review guidance that
states:

- durable evidence should be proportional to the claim;
- generated outputs are not automatically source artifacts merely because they
  were produced by a successful run;
- committing an entire output directory is **not** the default reproducibility
  strategy;
- file count and reviewability matter in addition to byte size;
- a small fixture may be scientifically stronger than a full output snapshot
  when each retained file maps to an explicit assertion.

The default question before committing generated outputs should be:

```text
Which claim requires this file to remain in Git?
```

If the answer is only “the program produced it”, do not keep it by default.

---

## 2. Distinguish evidence classes

Document that different verification goals require different durable evidence.

### Scientific reference fixture

Purpose:

> independently verify scientifically meaningful observables and detect adapter
> or implementation regressions.

Prefer:

- a pinned real input;
- upstream/version/method provenance;
- a compact independently generated expected-observable receipt;
- the **minimum sufficient raw upstream files** needed to re-derive the critical
  observables;
- representative raw cases for parser/geometry/contact edge cases;
- explicit tolerances and negative/perturbation tests;
- a reproduction command for rebuilding the full upstream output when the
  executable/environment is available.

Do not default to committing every per-item/per-pocket/per-residue output file
when only a bounded subset is needed to prove the scientific claims.

A complete raw tree is justified only when completeness of that tree is itself a
scientific or protocol claim, or when no smaller fixture can independently
reconstruct the asserted observables.

### Frontend real-result replay

Purpose:

> prove that the production frontend renders authentic Runner result semantics
> and selected real artifact bytes.

Prefer:

- canonical ResultManifest/API projection;
- renderer-required artifact payloads;
- bounded representative payloads;
- hashes/size/reason records for excluded large or binary artifacts;
- sanitized provenance.

Do not turn replay into an archive of the full task result directory.

### Production/live acceptance

Purpose:

> prove that an exact deployment executed through the real scheduler/runtime/API
> path and published a valid result.

Prefer:

- machine-readable receipt;
- exact deployment/task/job/image/input/parameter identity;
- lifecycle and validation state;
- artifact inventory with hashes;
- selected observables needed by the acceptance claim.

Do not check in the entire job workspace merely to prove the run happened.

---

## 3. Preserve independence without snapshot inflation

Clarify that independent validation means the expected result must not merely be
derived through the same production code path being tested.

It does **not** mean every upstream output byte must live permanently in Git.

Acceptable patterns include:

```text
small raw upstream fixture
    -> independent parser/reference builder
    -> compact expected observables
    -> production adapter comparison
```

or:

```text
full real run performed externally/on target
    -> machine receipt + hashes
    -> selected durable raw evidence
    -> independently checked observables
```

When a compact receipt already records complete expected values, retain only
those raw files required to audit/re-derive the highest-value scientific claims,
unless full-tree identity is itself under test.

---

## 4. Add a generated-output review checkpoint

Before a PR with generated fixtures/evidence can reach
`READY_FOR_FINAL_REVIEW`, the owner/reviewer should inspect the evidence
footprint.

Require a short justification when generated files materially dominate the diff
by file count or review surface.

The review should answer:

1. Which explicit claim does each retained class of generated file support?
2. Could the same claim be proven from a compact expected-observable receipt plus
   a representative raw subset?
3. Is the fixture testing scientific semantics, parser behavior, frontend
   rendering, or merely snapshot identity?
4. Are large/binary/volatile outputs represented more cleanly by hashes and
   metadata?
5. Can another developer reproduce the omitted full output from the pinned input,
   version, parameters, and documented command?
6. Would this pattern remain reasonable if applied to a Runner that emits
   hundreds or thousands of files?

The last question is important: do not establish a fixture convention that works
only because the current example happens to be small.

Avoid hard byte/file-count thresholds. A 250 KiB fixture can still be poor
repository evidence if it creates 80 low-signal files, while one larger
human-auditable reference artifact may be justified.

---

## 5. Prefer minimum sufficient fixtures

Document the desired default:

> keep the minimum sufficient raw evidence set that still makes the acceptance
> independently auditable.

For example, when a program emits one global descriptor table plus many
per-object geometry/contact files, a good scientific fixture may contain:

- the complete global descriptor table, when it proves global count/ranking and
  deterministic descriptors;
- a small representative subset of per-object raw files needed to test geometry,
  contact, parsing, or edge-case semantics;
- a compact reference receipt containing the expected global values;
- negative tests proving important claims fail when perturbed.

Do not encode this example as fpocket-specific permanent guidance; keep the
principle generic.

---

## 6. Preserve full-output evidence when it is genuinely the claim

Do not overcorrect into deleting useful evidence.

A complete output set may be appropriate when, for example:

- the contract explicitly requires every artifact to be present;
- parser completeness across all generated members is the behavior under test;
- cross-file relationships cannot be reconstructed from a bounded subset;
- exact raw-byte identity is the acceptance target;
- the full fixture is itself a small, stable upstream conformance corpus.

When full output is retained, require the PR to say why a bounded subset would be
insufficient.

If an archive is considered, note the trade-off:

- an archive can reduce repository path noise and preserve exact bytes;
- but it reduces GitHub diff/review visibility.

Do not recommend compression merely to hide an unnecessarily broad fixture.

---

## 7. Integrate with Campaign orchestration

This rule must complement, not alter, PR #41/#49 orchestration.

The Commander should:

- treat evidence-footprint cleanup as part of the owning PR when it directly
  concerns that PR's fixture design;
- avoid spawning a broad repository cleanup because one PR exposed the pattern;
- surface a generated-output footprint concern during implementation/review,
  before final readiness;
- allow independent Campaign work to continue under PR #49 dynamic orchestration;
- preserve external/human merge authority.

Evidence footprint is a **review-quality constraint**, not a new dependency
class and not a Wave barrier.

---

## 8. Acceptance

Before reporting this guidance PR ready:

1. Read the full Multi-agent Campaign Protocol as one document.
2. Confirm the new text does not imply that generated outputs are forbidden.
3. Confirm it explicitly rejects “commit the whole run directory by default”.
4. Confirm scientific reference, frontend replay, and production acceptance are
   distinguished.
5. Confirm minimum sufficient raw evidence + compact expected observables is the
   default scientific-fixture pattern.
6. Confirm full raw trees remain permitted when completeness/raw identity is
   genuinely the claim and are explicitly justified.
7. Confirm file-count/review-surface concerns are recognized separately from
   byte size.
8. Confirm no hard arbitrary size threshold was introduced.
9. Confirm the guidance remains Runner-neutral and host-neutral.
10. Confirm Commander/merge/concurrency/dependency rules from PR #41/#49 are
    unchanged.
11. Run:

```bash
git diff --check
```

No static test should pin literal documentation wording.

---

## Definition of done

The guidance is complete when a future agent cannot reasonably interpret
“scientifically reproducible evidence” as “check the entire runtime output tree
into Git” without first proving that the full tree is actually necessary.

A reviewer should be able to demand a smaller fixture when the same claim can be
proved with a compact expected-observable record plus a bounded raw subset,
without weakening scientific independence or live acceptance.
