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
inputs retain the existing retained pin, so its build identity and readiness do
not move when the other five are activated.

## Read-only preflight

Before building or merging, list the affected families and what each still
needs:

```bash
REVODESIGN_SERVER_ENV=.env.production bash run/restart.sh activation-preflight \
  --runners bioemu2,opendde,freebindcraft,esmfold2,alphafold3
```

The command reads the same readiness resolver as `runner-status`: it builds,
promotes, and mutates nothing. Each row shows the family, current status, build
identity freshness, and next action (`build-sif`, `live-test`, `promote`, or
`none`). Add `--json` for the full readiness rows. Disabled families are listed
because enabling them is part of the activation.

## What a source merge leaves behind

For each changed family, the installed SIF was built from the previous build
identity. After the source merge, readiness re-derives the current identity from
the merged definition and build inputs and reports `BUILD_STALE`. Submission
admission refuses that family, and the refusal names the affected family, the
stale build identity (`BUILD_PROVENANCE_STALE`), and the recovery action
(`build-sif`).

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
   preflight after the merge.
2. **Build candidates before merging.** Run `prepare --build-sif` for the five
   families. This stages `<artifact>.next`; the active SIF is untouched and
   readiness remains `BUILD_STALE`.
3. **Accept each candidate on the target host.** Run `%test`, imports, and a
   representative native inference on the candidate image, then `live-test` so
   the receipt binds the exact candidate SHA-256, build-provenance digest,
   Runtime Bundle digest, execution contract, and every required smoke case.
4. **Confirm the preflight.** All five candidates now report their staged
   promotion action; Foundry still reports `READY` with next action `none`.
5. **Merge the source.** Admission refuses the five changed families. This is
   the only planned refusal window.
6. **Promote in one prepared restart.** The prepared restart verifies each
   candidate's receipt and promotes all staged candidates in the same walk:

   ```bash
   REVODESIGN_SERVER_ENV=.env.production bash run/restart.sh restart --mode=prepared
   ```

7. **Verify readiness.** Run the preflight again. All five families must report
   `READY` with next action `none`, and unrelated families must be unchanged.

If a candidate cannot be built or accepted before the merge, activation cannot
complete in the promotion restart. The only acceptable alternative is a
Maintainer-authorized planned downtime window covering the build, live test,
and promotion steps below; do not merge source early and leave the families
refused indefinitely.

## Fallback: operator order after a merge

If pre-merge preparation was not possible and a planned window is authorized,
the same steps apply after the merge, one family at a time:

1. **Build the candidate** from the merged definition:

   ```bash
   REVODESIGN_SERVER_ENV=.env.production bash run/restart.sh prepare \
     --enabled-runners=<family> --build-sif
   ```

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
See [Deployment Control Reference](deployment-control.md) and
[Runner Family Protocol](../runner-guide/runner-family-protocol.md) for the
readiness states and promotion predicate.
