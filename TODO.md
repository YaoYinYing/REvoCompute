# TODO — Publication Trust Boundary Closure

## Context

This PR is a focused post-#58/#65 security closure. The trust-boundary architecture already exists on `main`: Core-owned ingress validation, immutable input snapshots, server-owned publication anchors, publication-state gating, verified artifact descriptors, and quarantine semantics.

Do **not** redesign that architecture. Close the remaining publication-side race/resource-exhaustion gaps found after #58 merged, and make the boundary executable under adversarial filesystem mutation.

Governing invariant:

> Runner output is an untrusted filesystem namespace. No pathname, manifest, archive, download, or projection becomes trusted merely because it lives under a Task result directory.

## Scope

### 1. Replace pathname trust with descriptor-relative containment

Audit every publication/read path that currently relies on absolute-path validation plus a final-component `O_NOFOLLOW`.

Implement one canonical descriptor-relative opener/walker rooted at the trusted Task result directory.

Requirements:

- open the trusted result root once;
- walk every intermediate component relative to the parent directory descriptor;
- refuse symlinks at **every** component;
- refuse `.`, `..`, empty components, absolute paths, overlong/invalid components, and path normalization ambiguity;
- require intermediate components to be directories;
- require final artifacts to be private regular files under the existing hard-link policy;
- do not reopen an already-validated absolute pathname;
- keep the verified descriptor open through identity/hash/read operations whenever practical;
- fail closed on any mutation between enumeration and open;
- preserve current publication/quarantine reason semantics rather than inventing a parallel vocabulary.

The same primitive should be reused by finalization, manifest reads, artifact download, archive creation, MCP artifact retrieval through the canonical server boundary, and any other consumer of published result bytes.

### 2. Enforce publication capacity **before** unbounded hashing

Current publication limits must bound work, not merely the final accepted manifest.

For each candidate artifact:

- obtain size from the verified descriptor before hashing;
- compare it against the remaining per-file/aggregate publication budget before streaming;
- never hash an artifact that is already known to exceed the remaining budget;
- bound the hashing loop to the verified size;
- detect growth, shrinkage, inode substitution, or other identity change during the read and reject rather than silently hashing an unbounded stream;
- preserve streaming behavior; do not read large scientific artifacts into memory.

A rejected over-capacity artifact must produce bounded publication evidence and must not hold the worker in an unbounded read.

### 3. Make writer and reader manifest limits one contract

The publication writer must never successfully anchor/install a manifest that the canonical reader is guaranteed to reject.

- establish a single canonical maximum serialized manifest byte limit used by both writer and reader;
- check the **serialized bytes actually being anchored** before publication succeeds;
- ensure artifact-count and manifest-size ceilings are mutually compatible;
- preserve explicit capacity-guard evidence when a result set exceeds publication limits;
- never mark a Task finished with a manifest that canonical readers classify as unreadable solely because the writer emitted an oversized manifest.

Do not silently truncate a scientific result into a false success.

### 4. Re-audit publication consumers

After implementing the canonical descriptor boundary, prove that these surfaces consume the same publication authority:

- result projection;
- individual artifact download;
- result ZIP/archive;
- MCP result/artifact projection through the canonical server path;
- republish/retry;
- legacy unanchored/quarantined results.

No surface may fall back to `os.path.isfile()`, a raw pathname read, or a cached ZIP that bypasses publication state.

### 5. Failure-injection and adversarial tests

Add deterministic tests for at least:

- intermediate directory replaced with a symlink between enumeration and open;
- final-component symlink;
- hard-link substitution;
- non-regular files;
- artifact larger than remaining publication budget;
- artifact that grows while hashing;
- artifact truncated/replaced while hashing;
- manifest exactly at and just above the reader/writer ceiling;
- many ordinary artifact records approaching the manifest ceiling;
- archive/download refusal for quarantined or identity-mismatched publications;
- retry after failed publication without a false `manifest.published` state.

Prefer descriptor/barrier-based deterministic races over sleeps.

### 6. Architecture and compatibility

Preserve:

- #58/#65 publication anchor/quarantine model;
- Resource Accounting/Data Lifecycle from #59/#66;
- Task/ResultManifest schemas unless a security fix strictly requires a compatible extension;
- HTTP/Web/MCP authorization and concealment semantics;
- Runner scientific outputs and result goldens.

Do not absorb deterministic Slurm placement, Admin reporting, general input-validator redesign, or Runner test ownership (#71).

If #71 advances `main`, reconcile test locations to its ownership rules without changing this PR's security scope.

## Acceptance gates

- focused publication-boundary unit tests;
- deterministic race/failure-injection tests;
- archive/download/MCP projection regression tests;
- required exact-head CI;
- fresh security/adversarial review against the frozen final head;
- reviewer explicitly checks that no intermediate-component symlink escape, unbounded over-capacity hash, or writer/reader manifest-limit mismatch survives.

Record exact-head evidence in the PR thread. Delete this `TODO.md` before final review.

Do not merge.
