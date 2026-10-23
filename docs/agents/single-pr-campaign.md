# Single-PR Campaign Protocol

> Procedure supplement to [Long-task Handling](long-task-handling.md). Root `CLAUDE.md`
> remains normative. Based on independently reviewed evidence from PR #104;
> no role in this protocol can authorize a merge or production promotion.

## Roles and separation of duties

One Campaign PR may host multiple isolated Owner worktrees and one integrated
branch. Detailed technical findings belong in the **one PR's review threads**.

| Role | Responsibility | Separation |
| --- | --- | --- |
| Commander | Exact-base discovery; resource/scope scheduling; evidence handoff; serialized integration; compact control ledger | Does not implement product patches or self-certify |
| Feature/Task Owners | Domain code and focused regression evidence | No uncoordinated concurrent edits to shared files |
| Runner Evidence Producer | Optional delegated, authorized real computation through normal production API and cost budget | Cannot invent receipts or substitute synthetic fixtures for published output |
| Independent Campaign Adviser | Architecture, scientific semantics, ownership, threats and merge risk | Independent of implementations |
| Examiner (Examer) | Real browser controls, visual screenshots, observable science, failures, lifecycle, exact SHA | Independent of feature owners; not a screenshot-only or CI-only role |
| **Campaign Acceptance Auditor** | **Final independent check of the actual submitted code, commits, diff, tests, evidence, cleanup and PR claims** | Must not be Commander, Owner, Adviser or Examiner for this PR; never patches implementation |

Reserve an independent reviewer slot when needed; avoid saturating the
6–9-agent capacity or shared GPU with speculative parallel work.

## Pipeline

```text
Exact-head inventory → real evidence / feasibility → scoped Owner design
→ implementation in isolated worktrees → one-PR integration
→ CI + actual-result browser acceptance (Examiner)
→ independent science/architecture challenge (Adviser)
→ **final submitted-content attestation (Acceptance Auditor)**
→ READY_FOR_FINAL_REVIEW → maintainer decides squash-merge
```

An Owner's `READY`, passing CI, screenshots, Examiner acceptance,
or Adviser approval **is not transitive**. Each has its own evidence level and
exact revision. A new edit after acceptance requires impact-based rechecking.

## Final Acceptance Auditor — mandatory stop gate

At the **current exact PR head**, independently verify:

1. **Submitted Git tree:** precise head/base, changed files, commit history,
   proposed squash title/body, accidental generated binaries, temporary root
   TODO, credentials, unrelated files, obsolete stubs and code/doc drift.
2. **Claims against evidence:** PR description, checklist and release notes
   distinguish implemented, experimental, blocked, synthetic replay, production
   computation, and deployed/browser-observed behavior.
3. **Tests:** checks really ran on this head, required lanes succeeded,
   warnings and known flakes accurately described; run additional focused
   regressions where warranted, not meaningless reruns of the whole GPU fleet.
4. **Independent reviewer records:** Examiner's actual browser interactions
   and sanitized screenshots, Adviser's technical verdict, resolved P0/P1
   review findings and explicit P2 decisions.
5. **Cleanup:** compare new test outputs against baseline; check direct
   references **and implicit output-contract glob dependencies**; assert no
   CI-needed evidence was silently deleted or externalized; verify recoverable
   artifact digests, licenses, and links for any approved Release assets.
6. **Final PR deliverable:** new code, docs, scientific outputs and acceptance
   claims are mutually consistent; no unresolved production deployment,
   readiness recertification, server-deletion or privacy obligations are
   disguised as completed work.

The Auditor posts a directly reviewable, succinct independent
`ACCEPTANCE_AUDITOR_PASS | ACCEPTANCE_AUDITOR_REJECTED |
ACCEPTANCE_AUDITOR_BLOCKED` verdict in the PR thread, naming the **exact
head SHA**, tests/review links, unsupported claims, and remaining issues.
It does not patch the tree or manufacture missing evidence. A patch after
PASS requires a new differential audit.

**Commander cannot announce READY_FOR_FINAL_REVIEW without this Auditor PASS.**
Maintainer alone authorizes squash-merge and subsequent production promotion.
After an authorized merge, Commander checks main's merged SHA and hands off
operational tasks; a merge is not a deployment.

## PR #86 specificity

For local-result viewing: capture actual downloaded ZIP semantics before coding,
separate untrusted local source bytes from server-approved manifest authority,
use installed allowlisted renderers rather than archive-provided scripts, test
no-upload behavior and real structure/table interactions. Subtraction must
follow [Evidence Retention and External Archives](../developer-guide/evidence-retention.md)
and must not silently remove CI material.
