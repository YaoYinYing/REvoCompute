# Architecture

REvoCompute has four boundaries: the HTTP/API layer authenticates and
authorizes; the Core builds a validated TaskDefinition and ExecutionPlan; the
worker submits that plan to Slurm and Apptainer; and the family parser accepts
typed outputs into isolated storage. Redis/Celery transport work but do not own
scientific rules.

The server is authoritative for task definitions, schemas, extensions,
resource policy, and scientific constants. Runner families provide
self-contained runtime contracts and artifacts. Admission checks the shared
current readiness evidence before side effects, while access entitlement is a
separate decision. This separation keeps Core generic and makes provenance,
receipts, and recovery auditable.
