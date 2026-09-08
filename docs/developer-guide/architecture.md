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

Admission checks the shared current readiness evidence before durable side
effects, while access entitlement and transient scheduler capacity remain
separate decisions. This separation keeps Core generic and makes provenance,
receipts, and recovery auditable.
