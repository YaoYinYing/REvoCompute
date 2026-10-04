# Fleet Result Contract Audit and Real-artifact Renderer Goldens

## Objective

Combine two closely related goals:

1. statically audit the **entire Runner fleet** for internally coherent result
   contracts; and
2. establish a small **real-artifact browser golden matrix** for the generic
   Result Workspace renderer classes.

The first goal answers:

> Does every shipped Runner declare a result contract the server can satisfy?

The second answers:

> Have the generic renderers actually consumed authentic bytes produced by real
> Runners?

Do not execute every Runner and do not create one browser fixture per Runner.

---

## 0. Campaign position and dependencies

This is a **Wave 3** PR.

It depends on the merged real-result capture/replay bridge from Wave 2.

Rebase onto that merged main before implementation.

If the fpocket scientific-reference PR has also merged, use its real result when
it adds useful renderer coverage, but do not make this PR depend on fpocket
unless the Commander determines that dependency is necessary.

---

## 1. Fleet-wide static result-contract audit

Discover every shipped task through the canonical production loader.

For every task/result declaration, verify the relationship among:

- `task.yaml result_workspace`;
- `expected_files.yaml`;
- declared artifact roles;
- required/optional source selectors;
- source path/glob semantics;
- server artifact preview/capability projection;
- storyboard required/optional logical files;
- generic renderer mapping requirements.

This audit is structural/semantic. It does **not** claim the Runner executable
actually produces scientifically correct output.

---

## 2. Required invariants

At minimum enforce generic invariants such as:

- every required ResultView source can be satisfied by a declared result-tree
  location/pattern;
- a primary ResultView is unique under existing contract rules;
- required storyboard logical files refer to declared/publishable files;
- ResultView role/source semantics do not contradict declared artifact roles;
- renderer mappings include the fields required by that plugin;
- file formats/types are compatible with the renderer they feed;
- optional sources remain optional through publication/projection;
- a source selector cannot escape the task result root;
- duplicate/ambiguous declarations fail with an actionable task/view id.

Use canonical parsers and projection functions rather than reimplementing a
parallel YAML linter.

---

## 3. Audit every Runner; fix only real defects

Run the audit across the full discovered fleet.

For each failure:

- determine whether the manifest is wrong, the expected-file declaration is
  wrong, or the generic validator lacks a legitimate construct;
- fix the narrow owner;
- add a regression test that would have caught it.

Do not bulk reformat Runner manifests.

Do not change a Runner's scientific output merely to satisfy a mistaken generic
assumption.

If a defect changes execution/live-validation identity, surface that explicitly
and follow receipt invalidation rules.

The known Boltz `considerations` YAML typing defect from PR #38 should be
checked here if it still exists on the rebased main; fix it if still present,
but do not make unrelated Boltz runtime changes.

---

## 4. Define renderer coverage by capability, not Runner count

Build a compact coverage matrix for generic result plugins/classes actually
shipped by REvoCompute.

Prioritize representative authentic results for classes such as:

- matrix;
- entity table;
- alignment;
- scalar summary;
- metric series;
- candidate/structure collection;
- image/ndarray where these are real production surfaces;
- evidence bundle / logical-file grouping where it exercises distinct behavior.

The exact matrix should be derived from current manifests after rebase.

Do not create fifty-five golden pages because there are fifty-five task types.

---

## 5. Real-artifact provenance rule

Every entry in the browser golden matrix must be backed by authentic bytes
produced by the stated Runner execution, not a hand-authored lookalike.

For each captured result record:

- Runner/task identity;
- source task/live-test receipt;
- input and parameter identity as appropriate;
- artifact sha256;
- ResultManifest/view id that consumes it;
- any sanitization performed.

Use the Wave 2 replay bundle format.

Small bounded artifacts may be checked in under the replay policy.
Do not commit large structures/checkpoints merely for visual coverage.

---

## 6. Prefer orthogonal representatives

Select the smallest set of real Runner results that covers the renderer grammar.

GREMLIN_LH should naturally cover:

- matrix;
- entity table;
- alignment;
- scalar summary.

Use other already accepted or cheaply reproducible Runners for remaining
classes.

Prefer existing real acceptance artifacts before launching new expensive jobs.

If GPU hardware is unavailable, do not fabricate GPU Runner evidence. Use
previously proven, provenance-bearing artifacts when available and record the
limitation.

---

## 7. Browser golden assertions

For each selected renderer, assert scientific/contract semantics rather than
pixel-perfect styling.

Examples:

- source artifact hash is the captured hash;
- correct view/plugin consumes the intended source;
- declared units/direction/scale survive projection;
- matrix dimensions/labels come from the real artifact;
- table columns/keys correspond to real data;
- structure candidates can be opened by the canonical Mol* path;
- direct download returns exact bytes;
- optional evidence absence does not break the primary result;
- task-scoped routes reject another task id;
- no unexpected API requests, CSP errors, or console errors.

Use screenshots only where human-visible layout/renderer behavior genuinely
benefits from them. Do not create a large pixel snapshot maintenance burden.

---

## 8. Contract-negative fixtures

Add small intentionally invalid manifests/contracts that prove the audit catches:

- missing required source;
- incompatible renderer/source type;
- orphan storyboard requirement;
- duplicate/ambiguous source ownership;
- malformed renderer mapping;
- invalid role relationship;
- path escape.

These negative cases may be synthetic; the browser golden data must remain real.

---

## 9. CI/gate placement

The fleet static audit should be cheap enough to run in ordinary CI without
Runner images, weights, databases, scheduler, or GPU.

The real-artifact browser goldens should replay checked-in bounded evidence and
therefore also avoid requiring live execution in ordinary CI.

A new live execution is evidence acquisition, not a routine CI dependency.

Run:

- full fleet result-contract audit;
- result publication/server contract tests;
- replay/capture contract tests;
- targeted real-artifact Playwright matrix;
- repository browser gate;
- appropriate non-browser suite;
- docs strict build when docs change;
- `git diff --check`.

---

## 10. Subtraction pass

After the generic audit and real-artifact goldens are in place, identify older
tests that manually duplicate the same result payload shape.

Remove only demonstrably redundant stubs.

Keep synthetic tests that cover error/state combinations the real golden set
does not cover.

Do not delete scientific equivalence tests merely because a browser golden
exists.

---

## 11. Scope exclusions

Do **not**:

- execute the full Runner fleet;
- build one fixture per Runner;
- redesign ResultManifest;
- redesign Mol*;
- add Runner-name renderer branches;
- convert this into general UI polish;
- claim scientific correctness from static manifest validation;
- claim scientific correctness from successful rendering;
- add a large binary artifact archive.

---

## 12. Definition of done

The PR is complete when:

1. every discovered Runner passes one generic, canonical result-contract audit
   or has a narrowly justified/fixed declaration; and
2. every major generic result renderer is exercised by at least one
   provenance-bearing authentic Runner artifact where operationally feasible.

The resulting evidence should make the hierarchy explicit:

```text
fleet audit          -> declarations are internally satisfiable
real-artifact replay -> renderers consume authentic Runner bytes
scientific acceptance -> numerical/scientific correctness
```

Do not collapse these into one claim.
