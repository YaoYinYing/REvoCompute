# PR #86 Campaign — Local Result Workspace + Evidence Hygiene

> Branch-local implementation checklist. Remove this temporary root TODO
> before declaring final readiness; retain permanent architecture under docs/.
> `CLAUDE.md`, `docs/agents/single-pr-campaign.md` and
> `docs/developer-guide/local-result-workspace.md` govern this campaign.

## /goal

Turn PR #86's parked requirement into a single-PR Campaign delivering a secure
**Open Local Result Folder** entry point in the current post-#104 scientific
Result Workspace, without uploading/recomputing, and without inventing local
server authority. Reconcile the architecture documents with actual code;
perform a carefully verified subtraction/cleanup pass. Commander owns the
coordination; Owners build; Examiner checks UI; Adviser checks architecture;
**independent Acceptance Auditor checks the final submitted content**.

## Gate 0 — evidence and scope before design

- [ ] Refresh main, PR #86 exact branch head, current production deployment,
      CI and PR review state. Confirm #104 has been squash-merged.
- [ ] Capture **actual downloaded server ZIPs** for a structure/trajectory
      case and a table-linked case, with authorized data and observed member
      paths, `manifest.json`, sizes, hashes, missing metadata and ZIP version.
- [ ] Determine whether these existing archives can reproduce the current
      scientific views, logical file associations, and trusted Storyboard
      behavior. Do not mistake `tests/data/*_replay` for user-exported ZIPs.
- [ ] Produce a short threat model and source-compatibility decision, reviewed
      by Adviser, **before** Owners implement a local resolver.

## Gate 1 — role ownership and implementation

- [ ] Commander: one PR, isolated worktrees, bounded compute, precise evidence
      packets, scope/commit control and integration. No feature patch coding.
- [ ] Source-model Owner: smallest typed bounded local/remote read contract
      supporting logical IDs, scientific view associations, table/byte reads,
      streaming limits, cancellation, errors and explicit source identity.
- [ ] Import/security Owner: chosen local folder, safe path resolution,
      digest/size checks, duplicate-normalized paths, malicious HTML/JS,
      permissions, revocation and no implicit remote upload.
- [ ] Scientific-UX Owner: reuse current Mol*/trajectory/matrix/candidate/
      entity scientific primitives, allowed installed Storyboards and honest
      fallback. No Runner-name conditional Core branches, no second results UI.
- [ ] Browser acceptance Owner: authentic ZIP-derived fixtures and malicious/
      malformed cases, Remote regression, real scientific interaction,
      network interception, downloads, cancellation and viewer teardown.
- [ ] Evidence/Cleanup Owner: direct+implicit CI-consumer inventory, license
      checks, evidence/cleanup ledger, externalization eligibility; no
      speculative deletions.
- [ ] Independent Campaign Adviser: scientific semantics, architecture,
      security, scope and exact-head review.
- [ ] Independent Examiner: independent real browser actions and sanitized
      screenshots, scientific selection, Local/Remote states, offline-claim
      limitations, no-upload proof and errors at exact head.
- [ ] **Independent Campaign Acceptance Auditor**: independent final audit of
      exact tree, commit messages, PR description, CI, reviews, evidence,
      cleanup and truthful readiness claims. No coding and no self-certifying.
- [ ] Keep shared files under an exclusive integration owner; no extra PRs.

## Gate 2 — bounded product vertical slice

- [ ] Render one actual extracted scientific result in the existing Result
      Workspace without reupload or Runner compute; retain file inventory,
      traceable limitations and correct local file-name vocabulary.
- [ ] Render second kind of result (linked table/selection) only when actual
      ZIP metadata supports it. Explicitly mark missing trusted Task Storyboard
      as unsupported, never execute archive-provided JS or HTML.
- [ ] Preserve existing Remote Result flow and task-scoped authorization.
      No new deletion/quota policy, full network-offline shell, caching service,
      or server-side import hidden inside this PR.
- [ ] Test security: path traversal, escaped symlinks, duplicate names,
      mismatch hashes, oversized binary/CSV/XTC/JSON, stale permission,
      cancellation, HTML/JS inertness and unexpected external network requests.

## Gate 3 — scientific evidence cleanup, narrowly scoped

- [ ] Baseline from #104: ~9.5 MB new test/evidence files, including 143
      `tests/data/storyboards` files / ~6.66 MB and one 4.70 MB ESMDynamic
      HTML. **The HTML and replay data support required CI; retain initially.**
- [ ] Map every candidate's explicit tests and implicit output globs, source
      sensitivity/license, reuse frequency, SHA-256 and CI dependency.
- [ ] Keep small CI cases and needed real-result replay files in Git.
      **Only large, repeatedly used, CI-independent data** qualifies for an
      optional external Release/archive, subject to permissions and hashes.
- [ ] Verify archive upload/download/extraction and consumers before deleting
      redundant in-Git copies. Do not create fake Release references.
- [ ] Document every `KEEP/EXTERNALIZED/REMOVED/BLOCKED` decision. Zero
      binary deletions is acceptable if all discovered large files serve CI.
- [ ] Clean outdated architecture prose and unnecessary duplicate documents;
      remove this root TODO only at the final handoff.

## Gate 4 — final acceptance, separate from implementation

- [ ] Run server/Runner boundary CI, browser tests, frontend typecheck/build,
      archive threat tests, strict MkDocs and baseline remote-result regression
      at the **exact final SHA**.
- [ ] Examiner gives independent hands-on browser verdict with actual actions,
      scientific visualization evidence, screenshots, exact head and stated
      fixture/production source; does not mistake mock for live execution.
- [ ] Adviser independently evaluates architecture/scientific meaning.
- [ ] **Acceptance Auditor** verifies final commits and proposed squash
      message, clean tracked tree, TODO removal, claims vs evidence, labels,
      CI, review dispositions, data cleanup, and no unverified deletions.
      Its independent PASS is mandatory before READY_FOR_FINAL_REVIEW.
- [ ] Report final exact head, supported archive classes, limitations,
      unresolved P2 decisions and production readiness; stop before squash
      merge and before deployment unless maintainer separately authorizes.
