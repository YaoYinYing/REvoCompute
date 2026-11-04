# Runner Family Protocol

Every family under `docker/runners/<family>/` MUST satisfy this contract before
the deployment accepts a submission to any of its TaskTypes. This page is the
normative entrypoint: it names the owners, the identity classes, the family
lifecycle, and the release gate. The linked pages own field syntax and
machine-owned values; this page never restates them.

## Ownership

| Owner | Owns |
| --- | --- |
| Family author | `plugin.yaml`, `.def`, `run.sh` and adapters, `task.yaml`, `test.yaml`, `expected_files.yaml`, Storyboards, and family tests |
| Server Core | discovery, Doctor, registry validation, planning, scheduling, admission, receipts, and readiness evaluation; it MUST NOT branch on a family name |
| Operator | `runner.yaml`, deployment env, host mounts, resource policy, and access-policy documents |
| Maintainer | merge, candidate promotion, deployment, and activation authorization |

A fact has one owner. The owning `task.yaml` is the scientific parameter and
input contract, the owning `plugin.yaml` and `.def` are the family identity, the
deployed `runner.yaml` is the machine-local configuration, and exactly one page
in this site explains each human-facing contract.

The family author must substantiate the user-relevant operations offered by
each registered Task against the **pinned upstream** implementation, and
review meaningful upstream releases before upgrading. This is a
**development and acceptance practice**, not a new runtime scientific
capability registry: Core discovers Task definitions without knowing the
scientific meaning of a particular Runner. The investigation procedure is in
[Adding a Runner](adding-a-runner.md#review-upstream-capabilities-before-adapting)
and mode-level evidence belongs to [Test Plan](test-plan.md#scientific-mode-coverage).

## Identity classes

A family change moves one or more of four independent identities. Classify every
changed file or field before building:

| Identity | What it covers | Release consequence |
| --- | --- | --- |
| Build | the direct `.def` and every mutable file declared by `runtime.build_inputs` | rebuild the SIF, then revalidate |
| Runtime Bundle | the content digest of repository code declared by `runtime.runtime_overlay` | keep the SIF, revalidate |
| Execution | the contract that changes accepted inputs, parameters, stages, outputs, resources, invocation, or live-test coverage | keep the SIF, revalidate |
| Presentation | user-visible metadata with no execution effect | deploy only |

Build freshness is evaluated first: a simultaneous build and execution change
reports `BUILD_STALE`, not merely `VALIDATION_STALE`. The detailed per-file
change list is in [Runtime Bundles](runtime-bundles.md#change-impact), which
also owns bundle identity, entrypoint resolution, pinning, retention, and
rollback.

## Lifecycle and release gate

A family moves through one lifecycle:

1. **Declare** the scientific contract, runtime identity, task contracts, result
   contract, and test plan.
2. **Validate statically** with Doctor. A contract failure stops here.
3. **Build a candidate** SIF as `<artifact>.next`. The active SIF is unchanged.
4. **Accept on the target host**: run the exact candidate through the production
   worker, Slurm, Apptainer, mounts, parser, and artifact contract.
5. **Receipt**: record a PASS bound to the exact identities that ran.
6. **Activate**: promote the receipted SIF with a prepared restart; a Runtime
   Bundle is published by the PASS that validated it.
7. **Admit**: new submissions resolve the active readiness evidence.
8. **Operate and roll back** without mutating a queued or running Task.

The release gate is satisfied only when all of the following hold for the
family and every TaskType that accepts submissions:

- strict Doctor passes for the family;
- the active or candidate SIF has a current build identity and passes
  `apptainer inspect` and `%test`;
- every overlay family has a published Runtime Bundle binding, and the receipt
  covers that exact digest;
- the execution contract and `test.yaml` are current, and the receipt covers
  every required `smoke` case;
- the target-host run observed the declared scientific output and accepted the
  declared artifact tree and required views;
- required weights, databases, mounts, service identity, and resource policy
  were present, and a restricted family declares its access policy;
- the evidence names the exact SIF, bundle, build provenance, configuration,
  test definition, fixtures, and execution account; no older acceptance is
  inherited by a changed identity.

Green CI, a merged pull request, a passing adapter fake, or a receipt for
another identity does not satisfy this gate. A family that cannot satisfy it is
withheld from submission as **NOT READY**, with the reason and recovery
recorded. Nothing may be made to look READY to complete an inventory.

## Scientific input roles

The owning `task.yaml` declares every input as a named role with a stable role
ID, logical type, accepted formats, and cardinality. Core, the API, the immutable
input snapshot, Runner dispatch, and artifact reuse all address that role; none
of them assign scientific meaning from upload order, a filename, or an
extension. Original inputs and hashes are preserved as an immutable snapshot,
and Runner-prepared files and logs are separate provenance artifacts. Record
cardinality counts files; a multi-record file is normalized by the owning family
into work items. [Task Contract](task-contract.md) owns the declaration.

## Output and artifact identity

A Task's result contract is owned by exactly one directory: the family root, or
the Task's own directory when it ships `expected_files.yaml`. Logical files,
their declared `role`, required views, and Storyboard composition come from that
contract; the server never infers them from a published filename. Only declared
artifacts are accepted, and a missing required artifact or view fails the Task.
Prepared files and preparation logs never replace user inputs. See
[Where a Task's result contract lives](adding-a-runner.md#where-a-tasks-result-contract-lives)
and [Structure Presentation Contract](structure-presentation.md).

## Stage and result evidence

A family that exposes meaningful execution phases emits
`REVODESIGN_STAGE:<id>` markers on stdout for stages declared by its owning
contract. Multi-item families publish per-item state and a derived task outcome
through the shared persistent lifecycle. A stage marker and a successful
sibling item are progress evidence, not proof that the Task succeeded.

A live-test receipt records the case identity, effective execution account,
Slurm jobs, SIF and bundle identities, execution-contract and test digests,
timing, resource observations, logs, parsed outputs, and artifact acceptance.
It also binds `configuration_digest`, which includes the effective resource
snapshot of every required smoke Task. A per-task resource-policy edit therefore
invalidates only receipts covering that Task; a global default edit changes
every inheriting Task's resolved policy and invalidates every affected family's
receipt. Only the target host produces that evidence. See
[Persistent Execution](persistent-execution.md) and
[Live Testing and Receipts](../operator-guide/live-testing.md).

## Testing evidence levels

Evidence is ranked. A lower level never substitutes for a higher one.

| Level | Establishes | Cannot establish |
| --- | --- | --- |
| Static contract | manifests parse, Doctor and registry rules hold, schemas and coverage are declared | that any executable runs |
| Adapter fake | family-owned parsers, command builders, and normalizers behave correctly against fakes | the real upstream CLI, GPU, or container |
| Real CLI | the pinned upstream tool runs on a minimal scientific input | Slurm, the production account, mounts, or acceptance receipts |
| Target-host Slurm + Apptainer | the full production path, scheduler, account, resources, parser, and artifact acceptance | scientific equivalence beyond the declared reference cases |

CI may exercise static and fake levels. It MUST NOT issue a PASS receipt or be
described as HPC scientific acceptance. Only target-host `live-test` can
authorize promotion. [Test Plan](test-plan.md) owns the declaration;
[Testing and CI](../developer-guide/testing.md) owns lane policy.

## Readiness, admission, and refusal

`READY` means the exact active SIF, its Runtime Bundle binding, its execution
contract, and its test plan are current and a receipt covers every required
`smoke` case. The states and their corrections are owned by
[Runner Readiness](../operator-guide/runner-readiness.md).

Readiness is one of several independent facts:

- **Access** is the calling user's entitlement to a restricted family. It never
  changes readiness.
- **Capacity** is transient scheduler and accelerator availability. A READY
  family may be queued or busy.
- **Infrastructure** is platform health. Degradation is reported, not folded into
  readiness.
- **Resource availability** is whether the deployed weights, databases, and
  mounts are present. Readiness does not inspect them; a missing resource fails
  the live test as `RESOURCE_MISSING`, and an accepted Task can fail at
  execution. See [Runner Weights and Model Assets](model-resources.md).

Production admission fails closed. A new submission to a disabled family, an
unknown family, a non-READY family, a Task omitted from the accepted scope, or a
family without resolvable readiness evidence is refused before upload
publication, quota reservation, or scheduler submission. A malformed or missing
attestation is treated as unavailable, never as permission. Admission applies to
new submissions only; queued and running Tasks keep their pinned identities.

`READY` is eligibility for a new submission, not authorization. Authentication
and access entitlement still apply, and neither READY nor a green build
authorizes a merge, deployment, or submission on the maintainer's behalf.

## Activation and rollback

Merge does not activate anything. Server deployment is `restart --mode=prod`
(or `--mode=prepared` for locally prepared artifacts). Activation changes what a
new submission binds, and it is maintainer-authorized.

- **SIF**: `prepare --build-sif` stages a candidate; `live-test` validates the
  exact candidate; `restart --mode=prepared` is the only promotion path. A SIF
  never replaces the active artifact because it built or passed a test.
- **Runtime Bundle**: the PASS publishes exactly the digest it validated. A
  changed binding is published by `setup` or `restart` only with a receipt for
  that family, digest, SIF provenance, configuration, and test definition.
- **Rollback**: return a family to an earlier accepted immutable identity. Only
  Runtime Bundle rollback has a documented operator command, `rollback-bundle`;
  it is receipt-gated and leaves a durable hold. SIF rollback is not a
  documented operator command; restoring a prior SIF is a maintainer-controlled
  decision, never a rebuild or a file copy. A full live-test PASS is the explicit
  forward move. See [Runtime Bundles](runtime-bundles.md#rolling-back) and
  [Deployment Control](../operator-guide/deployment-control.md#commands).

Neither activation nor rollback touches an already queued or running Task.

## Exceptions

A declared absence is a contract answer, not a bypass:

- a family with no `runtime_overlay` has no Runtime Bundle identity;
- a declarative family may have no pytest tests;
- a family with no redistribution basis declares no demo;
- a family that makes no numerical claim may declare only a `smoke` collection;
- GPU, network, and restricted-access requirements are declared capabilities,
  not implicit assumptions.

Withheld and **NOT READY** are valid release outcomes. There is no exception to
target-host acceptance for a family that accepts submissions, no hand-edited
receipt or readiness value, and no activation, deployment, or promotion without
the maintainer's authorization. A presentation-only change may deploy without a
new SIF or live test because it moves no execution identity.

## Repository test ownership

The family owns executable logic tests under `tests/fast/` and pinned scientific
acceptance under `tests/scientific/`, with shared support in
`docker/runner_testkit/`. Keep fixtures, references, goldens, and regeneration
utilities inside the family-root `tests/` namespace; deployment materialization
excludes it. Tests protect behavior, never static manifest, definition, or
documentation text. [Testing and CI](../developer-guide/testing.md) owns
collection and lane policy.
