# Architecture Invariants

REvoCompute's normative agent contract is
[`CLAUDE.md`](https://github.com/YaoYinYing/REvoCompute/blob/main/CLAUDE.md) at the
repository root. It states the rules that must not regress, and automated
contributors read it directly.

This page deliberately does **not** restate those rules. It explains why each
class of invariant exists, what it looks like in practice, and where to read the
surrounding design. If this page and `CLAUDE.md` disagree, `CLAUDE.md` wins. If
either disagrees with running code or a machine-readable contract, the code or
contract wins.

## Why the invariants exist

REvoCompute is a multi-tenant service that runs scientific software it does not
own, on hardware it does not control, for users who must be able to trust the
provenance of a result months later. The invariants are the small set of
properties that keep that possible as the runner fleet grows from a handful of
families to dozens.

Almost every invariant is a defence against one failure mode: **a fact copied
into a second place, where it silently goes stale.** That is why the rules
concentrate on ownership rather than on style.

## One owner for every fact

*The pressure:* a duplicated constant is correct on the day it is copied. It
becomes wrong only later, and then it is wrong in the copy nobody is looking at.
This repository has already lived through it: a root `RUNTIME_FAMILIES.md` copy
drifted three families behind the page under `docs/`, and five other root guides
had forked from their canonical pages.

*In practice:* scientific parameter vocabulary, defaults, and constraints belong
to the owning `task.yaml` and reach clients only through the projected API. A
frontend, a `runner.yaml`, an adapter, or a Markdown page may describe *how to
use* a parameter but must not restate its value or meaning.

*Read more:* [Architecture](../developer-guide/architecture.md),
[Task Contract](../runner-guide/task-contract.md), and
[Writing Documentation](../developer-guide/documentation.md), which defines what documentation may
and may not own.

## The server owns science; families own vocabulary

*The pressure:* a generic server that branches on runner names accumulates a
special case per scientific method. That does not scale past a few families, and
it puts scientific interpretation in code that has no scientific context.

*In practice:* Core owns the generic grammar — plugin loading, task validation,
resource policy, execution, artifact acceptance, readiness. A family owns its
TaskTypes, constants, runtime contract, parsers, and result semantics. Adding a
family with genuinely new vocabulary must not require a Core change.

*Read more:* [Plugin Kernel](../developer-guide/plugin-kernel.md),
[Execution Model](../developer-guide/execution-model.md), and
[Plugin Manifest](../runner-guide/plugin-manifest.md).

## Inputs are named roles with immutable provenance

*The pressure:* inferring scientific meaning from upload order or a file
extension is invisible when it breaks. A `.pdb` may be a receptor, a ligand, or a
decoy, and the difference is scientific, not syntactic.

*In practice:* a task declares named roles with logical types, accepted formats,
and cardinality. The server preserves the user's original bytes and hashes as an
immutable snapshot; anything a runner prepares afterwards is a separate
provenance artifact that never replaces the original.

*Read more:* [Task Contract](../runner-guide/task-contract.md) and
[Personal Task Storage](../operator-guide/personal-task-storage.md).

## Readiness is evidence, not a flag

*The pressure:* a mutable "ready" boolean is a claim with no expiry. It stays
true after the image it described is rebuilt or the receipt it rested on goes
stale.

*In practice:* readiness is derived from current Doctor output, the active SIF,
and a live-acceptance receipt whose hashes still match. Because it is derived,
`runner-status` never repairs anything and admission can fail closed before any
durable side effect. Entitlement and scheduler capacity remain separate
questions with separate answers.

*Read more:* [Runner Readiness](../operator-guide/runner-readiness.md) and
[Deployment Control Reference](../operator-guide/deployment-control.md).

## Prefer removal over accommodation

*The pressure:* compatibility layers are cheap to add and expensive to delete.
Each one multiplies the number of states the system can be in, and every state
needs its own test and its own documentation.

*In practice:* when a path is obsolete, remove it and update its callers rather
than keeping both. The documentation redesign followed the same rule: duplicated
root guides were deleted or replaced by symlinks instead of being kept in sync
by hand.

*Read more:* [Writing Documentation](../developer-guide/documentation.md) for how the same rule
applies to pages and repository-root files.
