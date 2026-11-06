# Source merges and Runner activation

A source merge and a Runner activation are separate decisions. Merging a change
to a family's SIF definition or declared build inputs changes the build identity
but does not build, test, promote, or enable anything. This page defines the
boundary operators must observe after such a merge.

## Families with changed build identity

The upstream-refresh campaign changes the direct Apptainer definition and/or
declared build inputs for five families:

| Family | Changed build identity |
| --- | --- |
| BioEmu2 | source commit, dependency lock |
| OpenDDE | source commit, dependency lock |
| FreeBindCraft | source commit, base image, dependency manifest |
| ESMFold2 | source commit, dependency lock |
| AlphaFold3 | source commit, HMMER patches |

Foundry is unchanged and is the control: its definition and declared build
inputs retain the existing audited executable pin, so its build identity and
readiness do not move when the other five are activated. The upstream delta is
documentation-only and does not justify a rebuild.

Two upgrades also change upstream defaults: OpenDDE v1.2.0 defaults to BF16 with
TF32 off, and ESMFold2 v3.4.2 defaults its ESMC backbone to fp8. OpenDDE keeps
sending its explicit Task values (`dtype=fp32`, `enable_tf32=true`) and records
them with the result. ESMFold2's `esmc_precision` is an adapter constant (bf16,
recorded with every prediction), not a Task value. Either way the effective
choice is visible rather than silent. Each family's `upstream.json` is the
durable provenance record.

## Read-only preflight

Run the preflight before or after `prepare`; it only reads readiness. Include
Foundry so its unchanged row is observed rather than assumed:

```bash
REVODESIGN_SERVER_ENV=.env.production bash run/restart.sh activation-preflight \
  --runners bioemu2,opendde,freebindcraft,esmfold2,alphafold3,foundry
```

The command reads the same readiness resolver as `runner-status`: it builds,
promotes, and mutates nothing, including the env file. Each row shows the
family, current status, build identity freshness, and next action (`build-sif`,
`live-test`, `promote`, or `none`). Add `--json` for the full readiness rows.
Disabled families are listed because enabling them is part of the activation.

Resolution order determines what each row describes. A family present in the
materialized instance snapshot resolves from that snapshot; a family absent from
it resolves from the checkout. Before `prepare` stages `<sif>.next`, an
instance-snapshot row describes the active deployment artifact; after `.next` is
staged, that row describes the staged candidate. A family absent from the
snapshot can report before `prepare`, because its row comes from the checkout.

## What a source merge leaves behind

For each changed family, the installed SIF was built from the previous build
identity. The merged tree derives a new identity from the changed definition and
build inputs, but admission reads the published attestation, and only a prepared
restart republishes it. The merge alone therefore activates nothing: the changed
families keep serving their existing identities until that restart. During the
prepared restart, attestations are cleared and admission fails closed. Promotion
runs before republication, so a successful prepared restart publishes `READY`. A
restart that completes without promoting a changed family republishes
`BUILD_STALE` (`BUILD_PROVENANCE_STALE`), and admission refuses that family,
naming the recovery action (`build-sif`), until a candidate is built,
live-tested, and promoted.

This is intentional fail-closed safety, not silent activation. A merge, a green
CI run, or a passed Doctor check never makes a family READY. Only a SIF built
from the merged recipe, accepted on the target host for that exact build
identity, and promoted can do so.

## Merge and promotion window

The preferred order keeps the admission refusal window to a single prepared
restart. Candidate artifacts are built and accepted before the source merge, so
promotion alone completes activation:

1. **Freeze the merge tree.** Integrate `origin/main` into the release branch
   and build candidates from that exact head. A later fast-forward into `main`
   must leave every declared build input byte-identical; verify with the
   preflight after the candidates are staged (step 4), because before `prepare`
   an instance-resolved row describes the deployment, not the candidate.
2. **Build candidates before merging.** Stage the five SIFs; the active SIFs and
   the published admission identity are untouched, so the existing families keep
   serving while the preflight reports `BUILD_STALE` for the new tree.

   ```bash
   REVODESIGN_SERVER_ENV=.env.production bash run/restart.sh prepare --build-sif
   ```

   Do not pass `--enabled-runners` here. It overrides the deployment's
   configured set for the whole window: `prepare` replaces
   `SERVER_DIR/docker/runners` with only the listed families, and an interrupted
   run leaves the snapshot narrowed. A bare `prepare` materializes every family
   configured by `ENABLED_TASKRUNNERS`, and `build_slurm_images` stages only the
   missing or stale candidates, so unrelated families stay in the deployment
   snapshot and their active SIFs are untouched.

3. **Accept each candidate on the target host.** Run `%test`, imports, and a
   representative native inference on the candidate image, then `live-test` so
   the receipt binds the exact candidate SHA-256, build-provenance digest,
   Runtime Bundle digest, execution contract, and every required smoke case.
4. **Confirm the preflight.** Run it with the list above and record the
   observed rows. The candidate rows are visible here because step 2 prepared
   the instance; all five candidates must report their staged promotion action,
   and Foundry must report `READY` with next action `none`.
5. **Merge the source.** The merge activates nothing by itself: the published
   attestation still describes the old identities, so submissions continue on
   the existing SIFs. The next prepared restart clears attestations and fails
   closed during the walk, then promotes and republishes `READY` for each family
   whose candidate was accepted. A changed family that is not promoted is
   republished as `BUILD_STALE` and refused until its candidate is built,
   live-tested, and promoted.
6. **Promote in one prepared restart.** The prepared restart verifies each
   candidate's receipt and promotes all staged candidates in the same walk:

   ```bash
   REVODESIGN_SERVER_ENV=.env.production bash run/restart.sh restart --mode=prepared
   ```

7. **Verify readiness.** Run the preflight again with the list above. All five
   families must report `READY` with next action `none`, and the observed
   unrelated rows, including Foundry, must be unchanged.

If a candidate cannot be built or accepted before the merge, activation cannot
complete in the promotion restart. The only acceptable alternative is a
Maintainer-authorized planned downtime window covering the build, live test,
and promotion steps below; do not merge source early and leave the new
identities unpromoted indefinitely.

## Fallback: operator order after a merge

If pre-merge preparation was not possible and a planned window is authorized,
the same steps apply after the merge, one family at a time:

1. **Build the candidate** from the merged definition:

   ```bash
   REVODESIGN_SERVER_ENV=.env.production bash run/restart.sh prepare --build-sif
   ```

   A bare `prepare` keeps the configured enabled set and rebuilds only the
   families whose candidate is missing or stale, so the other enabled families
   remain in the snapshot.

2. **Validate the candidate** with its `%test`, imports, and a representative
   native inference on the candidate image.
3. **Live-test on the target host** so the receipt binds the exact candidate
   identity:

   ```bash
   REVODESIGN_SERVER_ENV=.env.production bash run/restart.sh live-test \
     --runner <family> --collection smoke
   ```

4. **Promote the candidate** with a prepared restart, which moves the receipted
   `.next` artifact into place.
5. **Re-enable and admit** only after promotion. New submissions then resolve
   the promoted identity; queued and running Tasks are never mutated.

Continue each family independently. A receipt or promotion for one family does
not authorize another, and no evidence is inherited across build identities.
The previous SIF and its evidence remain the rollback reference.

## Five-family handoff: artifacts, prerequisites, failure, verification

Apply the order above to `alphafold3`, `bioemu2`, `esmfold2`, `freebindcraft`
and `opendde` one family at a time. Never hand-edit a receipt, build record or
staged identity; absent evidence means NOT READY.

| Step | Action | Artifact and evidence left behind |
| --- | --- | --- |
| Build | `restart.sh prepare --build-sif` | `images/<family>_v1.sif.next`, `<sif>.next.build.json`, and `images/evidence/<family>/<sif-sha256>.build.json` |
| Image checks | `apptainer inspect`, the definition's `%test`, Doctor | captured `%test` and Doctor output; a failed check leaves the candidate staged but unpromotable |
| Live test | `restart.sh live-test --runner <family> --collection smoke` | `images/live-tests/<family>/*.json` report and `images/evidence/<family>/<sif-sha256>.<identity>.receipt.json`; a PASS activates the candidate Runtime Bundle and republishes readiness |
| Promote | `restart.sh restart --mode=prepared` | `.next` becomes the active `.sif`; `promote-sifs` runs before `up`, and the deploy stamp records the restart |
| Verify | admin fleet API or `runner-status --all --json` | the row and submission checks below |

### Per-family prerequisites

Confirm these before building. Anything the repository does not establish is
`UNKNOWN, operator to confirm`.

| Family | Assets / paths | Licence | Network, accelerator, time |
| --- | --- | --- | --- |
| alphafold3 | `/mnt/alphafold3/models`, `/mnt/alphafold3/databases`, `/mnt/alphafold3/reduced_bfd/` | Apache-2.0 code; Google model-parameter terms, authorized receipt required | offline; GPU required; memory/walltime `UNKNOWN, operator to confirm` |
| bioemu2 | `/mnt/db/weights/bioemu2`, verified against `model-assets.sha256` before loading | MIT code and weights | MSA network path required; GPU required; memory/walltime `UNKNOWN, operator to confirm` |
| esmfold2 | `/mnt/db/weights/revocompute/esmfold2`, verified by `assets.json` sizes and SHA-256 | MIT (head, CCD, ESMC-6B) | offline; GPU required; ESMC-6B memory/walltime `UNKNOWN, operator to confirm` |
| freebindcraft | `/mnt/db/bindcraft/af_params`; upstream pinned Linux CUDA manifest | MIT code; mounted AF2 2022-12-06 params CC BY 4.0 | offline; upstream validated on RTX 5090 only, production-GPU fit/walltime `UNKNOWN, operator to confirm` |
| opendde | `/mnt/db/opendde` (checkpoint and search databases); HF manifest revision `eddd563c…` | Apache-2.0 code; checkpoint terms `UNKNOWN, operator to confirm` | MSA/template network path required; GPU required; memory/walltime `UNKNOWN, operator to confirm` |

### Failure and rollback

- **Live test fails partway.** The one-off live-test worker exits non-zero and
  the running stack is untouched: no receipt or binding is published. Leave the
  candidate staged, keep the stack up, and record the failure with its logs. Do
  not edit a receipt or build record.
- **Abandon a staged candidate.** Before any prepared restart, remove
  `<sif>.next` and `<sif>.next.build.json`. A bare `prepare` also replaces a
  stale candidate. The prepared restart validates staged images inside
  `activate-revision`, after `stop`, so an invalid `.next` left in place aborts
  the walk with the stack already down; if that happens, run `restart.sh up`,
  remove the candidate, and retry. Remove a `<sif>.promote-backup` only after
  confirming the active SIF is the intended one.
- **Genuine regression or stale stamp.** Treat a failure as a candidate
  regression only when the candidate's `sif_sha256`,
  `build_provenance_digest`, `configuration_digest` and
  `test_definition_digest` all match the values resolved from the current tree.
  If any differ — including when `CONFIG_DIR/.deploy-stamp` names an older
  commit — the failure is an identity/stamp mismatch: rebuild from the current
  tree and re-run the live test before changing code.

### Verification

`GET /compute/api/auth/admin/runners` (or `runner-status --all --json`) must
show, for each of the five, `readiness.status == "READY"`,
`readiness.reason_code == "READY"`, `readiness.next_action == "none"`,
`readiness.active_image.state == "ACTIVE"`, `readiness.evidence.receipt_valid
== true`, `readiness.evidence.build_provenance_current == true`, and
`readiness.active_image.sha256` equal to the accepted candidate's digest. A
submission for a family that is not READY is refused with HTTP 503 carrying
`runner`, `status`, `reason`, `message` and `next_action`.

For every untouched family, compare `status`, `reason_code`,
`build_provenance_digest` and `sif_sha256` with a snapshot taken before the
window; they must be unchanged. `foundry` is the named control. The untouched
set is deployment-defined by `ENABLED_TASKRUNNERS`, so record that snapshot
rather than assuming a fixed roster.

See [Deployment Control Reference](deployment-control.md) and
[Runner Family Protocol](../runner-guide/runner-family-protocol.md) for the
readiness states and promotion predicate.
