---
name: revocompute-prose
description: Use when writing, reviewing, trimming, or auditing prose in REvoCompute — docstrings and code comments, docs/ pages, task.yaml and plugin.yaml descriptions, diagnostics and error messages, CLI output, and agent-facing text such as the /skills.md bootstrap. Also use when a diff needs its comments removed.
---

# REvoCompute Prose Standard

Write enough to preserve the contract, then remove reasoning transcripts,
repetition, and decoration. A contract here is an obligation, invariant,
precondition, postcondition, or compatibility promise that a caller, callee,
implementer, or user relies on. This is guidance, not a script.

`docs/developer-guide/documentation.md` owns page structure, section ownership,
and the "documentation explains machine-owned facts but never copies their
values" rule. This skill owns editorial judgment — what to keep, add, or cut.
Link to that page rather than restating it. [`CLAUDE.md`](../../../CLAUDE.md)
stays normative if the two ever disagree.

Comments describe non-obvious contracts or rationale that code cannot express;
they do not restate what the code already implies.

## Preserve the complete proposition

Before editing, identify every proposition in the passage and preserve each
relevant one:

- actor and action;
- condition, timing, and ordering;
- modality — must, may, never;
- negative guarantee and exception;
- ownership, side effect, failure mode, and consequence.

Remove adjectives, repetition, and narration only when every factual clause
survives and the result is clearer. A smaller word count is not by itself an
improvement. Keep a complete local contract at the point of use — behavior,
failure, ownership, consequence — and link to the owning page for architecture,
rationale, algorithms, and history. One explanation has one home; an essential
contract fact may repeat locally.

Keep non-obvious rationale when omitting it could plausibly cause misuse or an
incorrect simplification. Otherwise state the consequence and link the rationale
to its owner.

## Required coverage by location

This is not a one-way shortening pass. Add or restore prose when code, types, and
structure do not communicate a required fact. Do not add a comment when the fact
is already obvious at that point.

- **Public docstrings:** document caller-visible return distinctions, raised
  exceptions, side effects, ownership, timing, cancellation, and durability.
- **Internal comments:** orient non-local or complicated local structure —
  invariants, ordering, ownership, trust boundaries, surprising failures. Delete
  control-flow narration and code restatement.
- **Module docstrings:** the module's role, responsibilities, dependencies, and
  non-obvious design choices, linked to their owning explanation.
- **Tests:** explain only non-obvious test design — why a fixture, assertion,
  real entry path, or indirect observation is necessary. Delete walkthroughs.
  Do not add tests that read static files to assert their contents; the testing
  policy in `CLAUDE.md` owns that rule.
- **`docs/` pages:** the reader's contract — configuration, semantics, failures,
  limitations, extension points — at the owning level. Link to the owning
  `task.yaml`, `plugin.yaml`, or OpenAPI document instead of copying a value.
- **`task.yaml` and `plugin.yaml` descriptions:** these are projected into the
  API and the UI, so treat the wording as behavior. Describe the role or
  parameter's meaning and constraints; never duplicate a default the file
  already declares.
- **Diagnostics and error messages:** name the failing subject or path, the
  violated rule, and the correction when it is not obvious. Remove execution
  narration.
- **Agent-facing text** — `revocompute/static/skills.md`, CLI help, route
  docstrings surfaced in OpenAPI: wording is behavior. Change it only with the
  owning contract in view, and keep it consistent across the places a client
  actually reads.
- **Frontend strings:** keep copy and its accessibility names, titles,
  placeholders, and format templates consistent, and update the browser contract
  that observes them (`make test-browser`) in the same change.

Preserve searchable mechanism names and meaningful modal, temporal, or negative
emphasis. Normalize decorative emphasis only.

## Workflow

1. Confirm the scope and the current branch or PR base. Do not inspect unrelated
   branches.
2. Read the owning code or document before judging a passage.
3. Inspect the whole requested scope, not only the largest files. Use searches
   and word counts to find candidates, then judge them semantically.
4. Classify each candidate as keep, add, trim, restore, or defer. Apply a change
   only when it is clearly right; do not manufacture edits to hit a target.
5. Update the owner before its derivatives. When a generated artifact or a page
   quotes another, fix the source first and regenerate.
6. Satisfy every required gate in [`CLAUDE.md`](../../../CLAUDE.md) first, then
   the narrow relevant checks: `mkdocs build --strict` for any page or
   `mkdocs.yml` change and `make test-browser` for a visible string. Run
   `git diff --check` before pushing.
7. Report the scope inspected, the changes made, the deliberate keeps, the
   deferred cases, and the checks actually run.

## Borderline decisions

A case is borderline only when two versions both satisfy the complete-proposition
rule and trade accepted principles. A rewrite with one proposition-preserving
answer is not borderline — just apply it.

When a case is genuinely borderline, present the two or three viable versions,
recommend one, and state the factual difference between them. Do not offer
inferior distractors, and do not weaken a proposition to make progress.
