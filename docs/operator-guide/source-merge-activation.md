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

Foundry is unchanged: its definition and declared build inputs retain the
existing retained pin.

## What a source merge leaves behind

For each changed family, the installed SIF was built from the previous build
identity. After the source merge, readiness re-derives the current identity from
the merged definition and build inputs, finds no SIF or receipt for it, and
reports `BUILD_STALE`. Submission admission refuses that family, and the refusal
names the affected family, the stale build identity (`BUILD_PROVENANCE_STALE`),
and the recovery action (`build-sif`).

This is intentional fail-closed safety, not silent activation. A merge, a green
CI run, or a passed Doctor check never makes a family READY. Only a SIF built
from the merged recipe, accepted on the target host for that exact build
identity, and promoted can do so.

A source merge to these five families must therefore be paired with an
operator-planned rebuild and re-acceptance window: schedule the candidate
builds, live tests, and promotions for each family before or immediately after
merging, so the admission refusal window is planned rather than discovered.

The family remains on its previous recipe until the candidate is promoted: a
deployment that keeps the old SIF is not silently served the new code, because
the old SIF still contains the old executable bytes. The previous SIF and its
evidence remain the rollback reference.

## Operator order per changed family

1. **Build the candidate** from the merged definition:

   ```bash
   REVODESIGN_SERVER_ENV=.env.production bash run/restart.sh prepare \
     --enabled-runners=<family> --build-sif
   ```

   This stages `<artifact>.next`; the active SIF is untouched.
2. **Validate the candidate** with its `%test`, imports, and a representative
   native inference on the candidate image.
3. **Live-test on the target host** so the receipt binds the exact candidate
   SHA-256, build-provenance digest, Runtime Bundle digest, execution contract,
   and every required smoke case:

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
See [Deployment Control Reference](deployment-control.md) and
[Runner Family Protocol](../runner-guide/runner-family-protocol.md) for the
readiness states and promotion predicate.
