# Restricted Runner access

REvoCompute roles and Runner entitlements are independent. A role (`admin`, `user`, or `guest`) controls authority over
REvoCompute. An entitlement records that a person may consume a restricted scientific resource. Administrators do not
automatically receive entitlements, while ordinary users may receive any entitlement an operator verifies.

This includes proprietary software, non-commercial or academic packages, controlled databases, private model weights,
unpublished collaborator assets, and restricted compute environments. REvoCompute does not decide whether a license
permits a particular person or project. It gives the server operator a consistent, auditable way to record that decision
and enforce it at task admission.

## Authorization model

Every submission passes these independent checks:

```text
authenticated active account
        ↓
admin / user / guest role rules
        ↓
personal or project task authorization
        ↓
runtime-family access policy
        ↓
submitting user's effective entitlements
        ↓
existing resource policy (including allow_gpu_use)
        ↓
persist upload snapshot and create task
```

An administrator can manage users without being licensed to run proprietary software. A project owner cannot lend an
entitlement to project members. Browser sessions, Bearer tokens, and API keys all resolve to the same submitting user and
therefore receive the same decision.

## How the server represents a proprietary Runner

The four configuration layers remain separate:

| Layer | Responsibility |
| --- | --- |
| `config/task_types.yaml` task type | Scientific inputs, parameters, outputs, and presentation |
| `runtime_families` entry | Shared executable environment and optional stable `access_policy` reference |
| `config/access_policies/<id>.yaml` | Portable authorization, request, notice, and verified license metadata |
| `config/runners/<family>.yaml` | Deployment-specific paths, mounts, environment, defaults, and resource limits |

Attach a policy to the runtime family, not every task, because software and data restrictions normally follow the shared
runtime. All tasks using that family then receive the same admission rule. A family without `access_policy` stays public
to otherwise-authorized REvoCompute users.

The policy format is deliberately small. IDs use lowercase letters, digits, `_`, or `-`; required entitlements are a
non-empty unique list; `match` must be `all`; and `requestable` is a boolean. Unknown keys or policy references stop the
server at startup. Policy files cannot contain expressions, callbacks, or executable code.

Optional `notice` text explains the state to users. Optional `license` name and URL should come from verified upstream or
contract material. Do not copy legal wording from memory. Keep secret keys, host paths, image names, license files, and
private administrative evidence out of policy metadata because catalog clients receive it.

## Intake checklist for proprietary software and assets

Before enabling the Runner, the operator or maintainer should:

1. Obtain and retain the authoritative license/agreement outside this repository.
2. Determine the smallest stable eligibility statement the operator can actually verify.
3. Choose a durable policy ID and entitlement ID; avoid names tied to one user, email domain, or temporary deployment.
4. Add the policy file and reference it from the runtime family.
5. Provision licensed binaries, weights, databases, or credentials through existing deployment-owned mounts/secrets.
6. Test startup validation, anonymous/authenticated catalog state, request/grant/revoke/expiry, and pre-upload denial.
7. Confirm `allow_gpu_use` separately when any task in the family requires GPU admission.

The policy registry authorizes use; it does not distribute proprietary material. Deployment mounts and secrets remain the
operator's responsibility and are never exposed through the catalog API.

## Operator workflow

Users request a Runner policy from the restricted Runner's create-task screen. The server resolves the policy's required
entitlements and creates all missing request rows atomically; the browser never submits entitlement identifiers. The User
Control page shows those pending audit rows and each user's Runner access. An administrator can approve or reject a row,
or grant an entitlement directly. A direct grant atomically approves and links a matching pending request when one exists.
Every grant records the administrator, controlled basis, time, optional expiry, optional note, and originating request.
Revocation marks the audit record instead of deleting it.

An effective grant is unrevoked and either has no expiry or expires in the future. Expiry and revocation deny future task
submissions immediately. A task admitted before revocation continues normally; use the existing task cancellation flow
when an already-running job must stop.

`allow_gpu_use` remains a separate resource gate. A restricted GPU Runner requires both GPU authorization and every
entitlement declared by its policy. Project membership never supplies an entitlement; the submitting user must hold it.

Grant bases are intentionally bounded: `lab_member`, `institutional_collaborator`, `individually_verified`, or `other`.
Profile fields such as affiliation, PI name, country, username, and email domain can inform a human review but never create
an entitlement. A user's request reason is evidence for review, not self-authorization.

Grant and request records are append-only audit history. Rejected requests may be resubmitted later. The database prevents
duplicate pending requests and serializes grant creation so one user cannot receive multiple simultaneously effective
grants for the same entitlement. Administrative notes remain available only through admin endpoints and are never included
in submission-denial responses.

## Request and approval sequence

```text
User opens restricted task
  → catalog reports policy and personal state
  → user submits the policy ID and a bounded reason
  → server atomically creates the policy's missing entitlement request rows
  → pending audit rows appear in User Control
  → administrator verifies external eligibility
      → approve: grant append + request approval in one transaction
      → reject: request audit updated, no grant created

Administrator already knows eligibility
  → direct grant with basis, optional expiry, and optional note
  → any matching pending request is approved and linked in the same transaction
```

Approval is one backend transaction. The browser never creates grants or reproduces entitlement business rules. A crash or
validation failure cannot leave an approved request without its corresponding grant.

## Submission and runtime behavior

The web process resolves the task type, its runtime family, and its policy after request validation but before saving
uploaded content. Missing, expired, or revoked entitlements return HTTP 403 with only the policy ID and whether it is
requestable. The route does not create a task row, durable workspace, Celery message, SLURM job, Docker container, or
Apptainer process on denial.

Workers do not re-evaluate licenses after admission. This preserves the explicit rule that revocation controls future
submissions and does not kill valid running work. Operators can cancel an existing task separately. Task records need not
copy private grant history; the admission decision is based on the current user's database records at submission time.

## Operational verification

Access policies are part of the portable deployment contract. Prepared restart preflight parses every policy document and
resolves every runtime reference before the existing service is stopped. The deploy stamp retains the task-registry digest
and also records a deterministic configuration-contract digest over `task_types.yaml` and all access-policy YAML files.
After changing policies, restart through the normal deployment process so web and worker registry views agree. A safe
verification checks:

- startup fails for malformed policy YAML or an unknown runtime policy reference;
- anonymous catalog responses reveal only that a Runner is restricted and its public notice/license metadata;
- an active user without a grant receives 403 before workspace creation;
- an admin without a grant receives the same 403;
- a granted user succeeds, subject to role/project/resource checks;
- revoked and expired grants fail immediately on the next submission;
- API-key submission matches Bearer submission;
- a restricted GPU task needs both the entitlement and `allow_gpu_use`;
- existing unrestricted Runners remain unchanged.

Database backups must include the user/auth SQLite database because it now contains the entitlement and access-request audit
records. Restoring only task data would not restore authorization history.

## Runner maintainer workflow

Create a strictly declarative file under [`config/access_policies/`](config/access_policies/README.md), then reference its
stable policy ID from the runtime family in `config/task_types.yaml`. Put licensing/approval descriptions in that policy,
not in task definitions or machine-specific runner YAML. The catalog API supplies browser state, and the shared task
submission route enforces it before upload persistence, task creation, Celery, SLURM, Docker, or Apptainer.

Test valid loading, malformed fields and identifiers, missing policy references, catalog state, grants/expiry/revocation,
request review, and rejection before task/workspace creation. This mechanism records operator authorization; it does not
determine legal eligibility. The server operator remains responsible for interpreting and applying external license terms.

## Production example: AlphaFold 3

`alphafold3` is the first production runtime using this restricted Runner contract. It is separate from the existing
AlphaFold2 `alphafold` family and attaches `alphafold3_noncommercial` at the runtime-family level, so the same policy
covers both scheduler stages. A user requests the policy; an operator reviews eligibility and grants its entitlement
through the generic audit workflow. Administrator role alone does not grant use, and `allow_gpu_use` remains an
additional requirement for submission.

The task accepts one upstream AlphaFold 3 JSON document without rewriting its scientific fields. Stage 1 runs the local
database pipeline without a GPU and records the generated `<job>_data.json`. Stage 2 verifies that artifact has not
changed, runs inference on a GPU without repeating the database pipeline, and publishes upstream mmCIF, confidence,
ranking, provenance, and terms files through the generic Result Workspace.

The image is built from google-deepmind/alphafold3 revision `c0f97eda2f1f482fd94d3a38bece18c7069b4a5c`. The local
historical `/repo/alphafold3` `native-run` checkout informed only the deployment's database mount layout.
`config/runners/alphafold3.yaml` narrowly mounts the AF3 database root, reduced BFD, and
`/mnt/db/weights/alphafold3` read-only into scheduled containers. These paths and assets are absent from public catalog
metadata.

AlphaFold 3 source is licensed under Apache-2.0. The model parameters, generated output, third-party databases, and
database search software have distinct terms that operators must review. The access policy links to the current official
[Model Parameters Terms of Use](https://github.com/google-deepmind/alphafold3/blob/main/WEIGHTS_TERMS_OF_USE.md) without
reproducing them or treating approval as proof of legal eligibility.
