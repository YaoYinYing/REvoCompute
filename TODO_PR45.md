# Fpocket Scientific Reference Runner

## Objective

Establish **fpocket** as the second literature/upstream-grounded scientific
reference Runner in REvoCompute.

GREMLIN_LH proved the reference pattern for a statistical sequence model.
Fpocket should test whether that standard generalizes to a CPU,
structure-input, geometry/pocket-detection program without copying
GREMLIN-specific assumptions.

The evidence chain should become:

```text
primary/upstream method
  -> pinned executable/version and parameters
  -> independent reference case
  -> REvoCompute adapter
  -> durable pocket artifacts
  -> ResultManifest/ResultView
  -> real Runner execution
  -> browser-visible result
```

Do not turn this PR into a general scientific-reference framework migration for
all Runners.

---

## 0. Campaign position and dependency

This is a **Wave 2** PR.

It may run in parallel with the real-result replay PR because the principal
write ownership is the fpocket Runner family and its focused tests.

If Wave 1 introduces reusable production-receipt capture that applies cleanly,
use it for final acceptance rather than writing another handwritten receipt.

Request an exclusive live/deployment lease only for the final real Runner
acceptance.

---

## 1. Establish upstream and literature provenance

Before changing scientific behavior, identify and record:

- fpocket upstream repository/project identity;
- exact version/revision actually installed by the Runner;
- primary method publication(s) appropriate to the implemented algorithm;
- command-line options used by REvoCompute;
- input preprocessing performed by the adapter;
- output files/fields consumed by REvoCompute.

Do not cite a newer fpocket behavior if the image actually contains an older
version.

Pin provenance in a form another developer can reproduce.

---

## 2. Choose a bounded real structural reference case

Select one small, redistributable protein structure with a meaningful pocket
that can be run quickly on CPU.

The case must be:

- real structural data rather than an invented coordinate cloud;
- small enough for CI/developer scientific acceptance where feasible;
- stable under the pinned fpocket version;
- accompanied by exact input hash/provenance.

Prefer an existing repository structure fixture if it is scientifically
suitable; otherwise add one bounded fixture with its provenance/license
documented.

Do not choose a case only because it makes every output trivially zero.

---

## 3. Define scientific observables before writing tolerances

Inspect the pinned upstream output and identify the observables REvoCompute
actually claims to expose.

Potential classes include, as supported by the pinned fpocket output:

- detected pocket count;
- pocket ranking/order;
- pocket score;
- druggability-related score where the selected version defines it;
- volume;
- pocket center/barycenter;
- alpha-sphere count;
- residue membership / lining residues;
- coordinates of pocket representations.

Do not assume every field is scientifically stable enough for a strict golden
assertion.

Classify each observable as one of:

```text
exact/discrete
numerical-with-tolerance
ranking/set-overlap
provenance-only
not suitable for golden acceptance
```

Derive tolerances from measured repeatability/platform behavior and method
semantics. Do not choose broad tolerances merely to make a failing test pass.

---

## 4. Keep the reference independent of production adapter code

The scientific reference must not be produced by importing the same parser or
postprocessing functions under test.

Use the pinned upstream executable/output or a separately maintained,
independently verified reference extraction path.

No `eval` or `exec`.

If a checked-in frozen reference is used, record:

- upstream version;
- input hash;
- command line;
- raw-output hashes where practical;
- reference-extraction version;
- expected observables.

A wrong upstream/version/input identity must fail closed.

---

## 5. Audit the current fpocket Runner semantics

Trace:

```text
task.yaml
runner/runtime command
raw fpocket files
adapter/result publication
expected_files.yaml
ResultManifest/ResultView
frontend renderer
```

Look specifically for places where REvoCompute might:

- rename a scientific metric incorrectly;
- infer pocket ordering incorrectly;
- discard sign/unit/precision;
- confuse pocket rank with pocket id;
- expose a derived quantity as though it came directly from upstream;
- omit a scientifically important file needed to reproduce the displayed
  result.

Fix only defects supported by upstream evidence.

Record intentional deviations explicitly.

---

## 6. Result contract

Ensure the fpocket Result Workspace expresses pocket results with generic
plugins/capabilities rather than Runner-name branches.

A primary view should represent the main user-facing pocket result.

Supporting evidence should preserve enough upstream output to audit the
displayed pockets.

Do not redesign generic ResultManifest or Mol* architecture for fpocket.

If a generic renderer capability is genuinely missing, add the smallest generic
extension with tests and prove another compatible result could use it.

---

## 7. Scientific equivalence tests

Add a focused fpocket scientific acceptance module.

The tests must verify:

- pinned provenance/input identity;
- adapter output against the independent reference;
- pocket identity/ranking semantics;
- selected exact/discrete observables;
- selected numerical observables with justified tolerances;
- result artifact semantics required by the frontend.

A deliberately perturbed reference or adapter output must make the relevant
acceptance test fail.

Keep fast protocol tests separate from scientific acceptance.

---

## 8. Real Runner acceptance

Run the reference case through the real REvoCompute execution path on an
appropriate target:

```text
submission
 -> scheduler/Runner
 -> fpocket executable
 -> published artifacts
 -> ResultManifest
 -> browser result
```

Record exact:

- final head/deployed revision;
- task id;
- scheduler job identity;
- Runner image/version identity;
- input hash;
- parameter snapshot;
- runtime;
- ResultManifest version;
- published artifact hashes;
- scientific acceptance result.

If the production-receipt utility from Wave 1 exists, use it.

Do not call a protocol-only smoke run scientific acceptance.

---

## 9. Browser acceptance

Use the canonical result surface to verify that the reference-case result is
presented with the same scientific meaning established above.

Where the Wave 2 real-result replay bridge is available without creating a
dependency cycle, it may later consume the fpocket result. This PR does not need
to wait for that sibling PR merely to prove fpocket science.

Browser acceptance must not be the source of scientific expected values.

---

## 10. Required gates

Run:

- existing fpocket protocol/result tests;
- new fpocket scientific-equivalence tests;
- relevant result publication/server contract tests;
- targeted browser acceptance;
- appropriate non-browser repository gate;
- documentation strict build when docs change;
- `git diff --check`.

A real final-head Runner execution is required for the scientific-reference
claim.

---

## 11. Scope exclusions

Do **not**:

- retrofit other pocket Runners;
- benchmark fpocket against every pocket-detection package;
- tune fpocket for best benchmark performance;
- redesign scheduler/runtime infrastructure;
- build a new generic scientific framework before the second example proves it
  is needed;
- add frontend Runner-name special cases;
- widen tolerances to hide a regression;
- change unrelated UI.

---

## 12. Definition of done

Fpocket becomes the second reference Runner when a reviewer can trace one real
structure from pinned method/version through independent expected observables,
REvoCompute execution and artifacts, and the browser-visible result, with every
scientific claim bounded by explicit evidence.
