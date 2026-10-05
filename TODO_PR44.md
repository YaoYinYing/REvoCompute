# Real Runner Result Capture and Frontend Replay

## Objective

Extend the frontend Runner fixture infrastructure from PR #38 with a **test-only
real-result capture/replay bridge**.

PR #38 proves frontend behavior against deterministic canonical API fixtures.
This PR must add the complementary ability to take a bounded, sanitized result
from a real Runner execution and replay its canonical API surface to the real
production frontend.

The purpose is to answer:

> Does the frontend render the same manifest and artifact bytes that a real
> Runner published?

This is not a production mock mode and not a scientific-equivalence system.

---

## 0. Campaign position and dependency

This is a **Wave 2** PR.

Before implementation begins, rebase onto the merged Wave 1 changes that affect
production receipt/evidence capture if they have landed.

The capture format should reuse machine-readable production evidence when
available rather than inventing a second provenance record.

Do not begin by changing the frontend. The first design problem is the
test-evidence boundary.

---

## 1. Preserve the PR #38 boundary

Keep these invariants from PR #38:

- serve the real built production frontend;
- mock only the HTTP/API boundary inside Playwright/test code;
- use canonical API vocabulary;
- fail on unexpected API requests;
- keep task-scoped artifact routes task-scoped;
- do not add production fake endpoints;
- do not mutate Runner manifests for fixture convenience.

The existing synthetic fixture library remains useful for state/error coverage.
Real-result replay complements it; it does not replace it.

---

## 2. Define a bounded replay bundle

Create one test-only representation of a captured Runner result.

A replay bundle should contain only what is required to reconstruct the
frontend-visible result surface, for example:

- capture schema/version;
- task identity and task type;
- safe task/result metadata;
- canonical ResultManifest response;
- storyboard response when applicable;
- logical-file metadata;
- bounded artifact payloads used by frontend renderers;
- sha256/size for every captured byte payload;
- provenance pointer to the production/live acceptance receipt when available.

Do not serialize arbitrary task-store rows or entire filesystem trees.

Keep the bundle deterministic and inspectable.

---

## 3. Capture from canonical production outputs

Provide a capture path that starts from a real completed task/result and reads
through canonical server/result ownership.

Requirements:

- verify the task is terminal;
- verify ResultManifest task identity;
- resolve only files inside the task result root;
- follow the same logical-file/artifact projection the product exposes;
- capture only files required by declared views/storyboard plus explicitly
  selected small evidence;
- compute sha256 from actual bytes;
- sanitize secrets/private host details before persistence;
- fail on required view sources that cannot be resolved.

Do not infer roles from filenames when the canonical result projection already
owns the role.

---

## 4. Size and binary policy

This must not turn the repository into an artifact archive.

Define a conservative per-file and per-bundle size policy.

Small textual/scientific payloads may be checked in when they materially support
browser acceptance.

For larger files:

- prefer a scientifically equivalent bounded representative already produced by
  the same Runner;
- or capture only the subset required by the renderer;
- never truncate a format in a way that makes the bytes cease to be the real
  artifact represented by the manifest.

If an artifact cannot reasonably be checked in, keep hash/provenance evidence
and document why that renderer needs another acceptance mechanism.

Do not add Git LFS as part of this PR.

---

## 5. Replay through the existing fixture router

Teach the existing `tests/frontend_fixtures` boundary to mount a replay bundle
without duplicating canonical schemas.

The replay path must serve:

- the captured ResultManifest;
- task-scoped artifact/download routes;
- table/projection/logical-file routes as applicable;
- storyboard data;
- any bounded renderer source bytes.

A mismatched task id must still return 404.

The frontend must not be able to tell whether the canonical response came from
a synthetic scenario or a captured real-result bundle.

Do not add `/test/*` production routes.

---

## 6. Initial GREMLIN_LH real result

Use the existing GREMLIN_LH 2KL8 real result as the first capture/replay case.

Capture enough authentic result material to exercise:

- raw coupling matrix;
- APC coupling matrix;
- ranked-pairs table;
- filtered alignment;
- scalar fit summary;
- storyboard/logical files used by the result workspace;
- direct artifact download for at least one captured scientific artifact.

Verify every replayed payload hash against the capture receipt/bundle metadata.

The browser assertions should verify renderer semantics and task/file identity,
not hard-code incidental CSS structure.

---

## 7. Round-trip and drift guarantees

Add tests that prove:

```text
real capture -> replay bundle -> HTTP projection
```

preserves the canonical frontend-visible semantics.

At minimum:

- ResultManifest equality after normalization of explicitly volatile fields;
- artifact bytes hash equality;
- logical-file identity;
- view ids/plugins/roles/sources;
- task scoping;
- required artifact failure;
- corrupt byte/hash failure;
- unsupported oversized artifact failure;
- sanitization of secret-bearing metadata.

A replay bundle must fail loudly when it no longer satisfies the current
OpenAPI/result contract.

---

## 8. Browser acceptance

Drive the production bundle with the replayed GREMLIN result and verify:

- all declared captured views mount;
- matrices use their declared scale semantics;
- the ranked-pair table consumes the real table;
- alignment content comes from the captured artifact;
- scalar summary values come from the real JSON;
- download returns the exact captured bytes;
- no unexpected API call is hidden by a wildcard route;
- no CSP/console regression appears.

Use existing PR #38 helpers and existing GREMLIN browser acceptance where they
fit. Delete duplicated stubs rather than creating another harness layer.

---

## 9. Required tests and gates

Run focused tests for:

- capture schema;
- canonical payload validation;
- path containment;
- secret sanitization;
- size limits;
- checksum validation;
- task scoping;
- capture/replay round trip;
- GREMLIN real-result browser acceptance.

Then run the repository browser gate appropriate to the touched frontend test
infrastructure and the non-browser contract tests for result publication.

Run `mkdocs build --strict` if developer documentation changes.

Run `git diff --check`.

No production deployment is required merely to replay an already captured,
provenanced result. A new production capture requires the Campaign deployment
lease.

---

## 10. Scope exclusions

Do **not**:

- replace synthetic fixture scenarios;
- create a production mock mode;
- create fake production endpoints;
- redesign ResultManifest;
- create a new frontend schema;
- implement scientific artifact equivalence;
- commit large model/checkpoint files;
- capture credentials or private user data;
- special-case GREMLIN inside generic router code;
- redesign Result Workspace UI.

---

## 11. Definition of done

The PR is complete when one bounded, sanitized, provenance-bearing real
GREMLIN_LH result can be replayed through the PR #38 test boundary and the real
production frontend renders and downloads the exact captured scientific bytes.

The evidence must make the distinction explicit:

```text
synthetic fixture -> frontend state/behavior contract
real-result replay -> frontend compatibility with authentic Runner output
scientific reference test -> scientific correctness
```

Those three claims must remain separate.
