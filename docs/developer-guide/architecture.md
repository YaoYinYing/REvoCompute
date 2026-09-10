# Architecture

REvoCompute has four boundaries: the HTTP/API layer authenticates and
authorizes; the Core builds a validated TaskDefinition and ExecutionPlan; the
worker submits that plan to Slurm and Apptainer; and the family parser accepts
typed outputs into isolated storage. Redis/Celery transport work but do not own
scientific rules.

Core owns the generic plugin, task, execution, resource, artifact, and
readiness grammar, together with orchestration and validation mechanisms.
Runner families own their TaskTypes, scientific parameter vocabulary,
scientific constants, runtime contract, parser and result semantics,
storyboard/workspace extensions, and family access-policy contribution. A new
family with new scientific vocabulary must not require Core knowledge of its
runner or task IDs.

Every user-facing parameter is fully declared in the owning `task.yaml`,
including type, default or required semantics, constraints, and a meaningful
scientific description. Core projects that declaration unchanged through the
anonymous `GET /compute/api/task-parameters/<task-type>` Draft 2020-12 JSON
Schema endpoint and through the task form contract; it does not own a parallel
parameter-help registry.

The anonymous `/skills.md` resource is a stable API bootstrap guide. It directs
agents to OpenAPI for protocol truth and to the dynamic Task discovery and
parameter-schema APIs; it never enumerates the fleet or becomes a separate
scientific declaration.

Admission checks the shared current readiness evidence before durable side
effects, while access entitlement and transient scheduler capacity remain
separate decisions. This separation keeps Core generic and makes provenance,
receipts, and recovery auditable.

## Ownership Boundary

REvoCompute owns user identity, Runner access and readiness, Task execution,
immutable user-owned Task storage, result manifests, Artifacts, and provenance.
Task ownership is directly user-based through immutable identities such as
`submitted_by_user_id` and the immutable user `storage_key`.

REvoCompute does not own Projects, Project membership or roles, Project
storage, invitations, visibility, or collaboration lifecycle. A future
independent Project Dashboard may reference stable REvoCompute Task and
Artifact identities, but must own its own membership, collection, role,
sharing, and presentation model.

The conceptual integration boundary is the Task ID; submitting/owner identity;
TaskType; task status; result manifest; artifact logical path; artifact metadata
and digest; authorized artifact retrieval; and artifact provenance. This
boundary does not introduce Project APIs, Project ACLs, sharing tables,
compatibility abstractions, generic scope objects, or cross-user artifact reuse.
