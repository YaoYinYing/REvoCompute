# PR6 Implementation State

This file is the current implementation record for PR6. It is not a promise
that every configured Runner is production-ready.

## Current Refactor Checklist

- [x] Enforce production service identity independently of the invoking operator.
- [x] Restore generic fail-closed admission for technically non-READY families.
- [x] Fail live-test acceptance closed on configured execution UID/GID and every observed Slurm scheduler identity.
- [x] Apply configured scheduler username to receipt/readiness identity matching.
- [x] Replace HTTP submission's deployment-controller readiness resolver with a lightweight shared admission attestation.
- [x] Share candidate server-image preparation across one `live-test --all` invocation.
- [x] Bind live-test validation identity to YAML bytes and fixture content hashes.
- [x] Remove the obsolete legacy live-test executor request protocol.
- [x] Remove committed MkDocs output and keep Pages publication artifact-only.
- [x] Consolidate documentation to one canonical owner per topic.
- [x] Remove implemented families from the adaptation wait list.
- [x] Audit every removed Runner Dockerfile against its current direct Apptainer definition.
- [x] Run target-host acceptance for the currently deployed EasIFA, AlphaFold 2, and AlphaFold 3 subset.
- [ ] Re-run exact-current acceptance and prepared activation for the other 11 families before restoring the full fleet.

## Delivered

- Runner-family plugins, task manifests, direct Apptainer definitions, Doctor,
  live-test receipts, and staged SIF promotion are implemented in the owning
  family trees under `docker/runners/`.
- AlphaFold 2 follows the pinned current upstream revision and uses the
  refreshed pipeline patch and `uv`-based dependency installation.
- The MkDocs Material site has one normative published owner per audience:
  `user-guide/`, `operator-guide/`, `runner-guide/`, `developer-guide/`,
  `reference/`, and `agents/`. Legacy root documents remain source references,
  not competing site namespaces.
- Documentation CI runs `mkdocs build --strict`; the main branch publishes the
  generated site through the GitHub Pages artifact/deploy workflow.

## Readiness

Doctor, active SIF provenance, required smoke coverage, and exact target-host
live receipts are evidence for Runner-family readiness. `enabled` or configured
does not imply `READY`. `runner-status` is the operator view of the shared
readiness contract used by production submission admission: new submissions to
a technically non-READY family fail closed before durable task, upload, queue,
or Slurm side effects. Access entitlement and transient scheduler capacity are
separate decisions, and a later readiness change does not cancel tasks already
running.

## Validation record

- `mkdocs build --strict` passes locally.
- Repository non-browser test gate passes: 752 passed, 4 skipped (3 warnings).
- Focused Runner contract tests and Doctor checks pass in the repository test
  environment.
- Target-host acceptance is complete for the currently deployed EasIFA,
  AlphaFold 2, and AlphaFold 3 subset. Exact-current acceptance for the other
  11 families and full-fleet prepared activation remain incomplete.
- Deployment/service identity remains independent of the invoking operator.
  The accepted candidate workers executed the scientific path as UID 129, GID
  137 and every accepted Slurm job reported scheduler user `revodesign`.

## Target-host acceptance history (2026-09-07)

- Historical acceptance attempt was against `320b0e4882687f5318c0de66c5f58be6e0e75042`.
- Current PR branch head under repair is `6640c68` (working-tree fixes continue from this pushed head).
- Earlier acceptance attempts used an outdated environment selection and a
  restricted Codex mount namespace. They did not establish production-host
  readiness or a PASS receipt. Maintenance remained enabled and services were
  not activated.

### Corrected environment evidence

- Correct environment is `.env.production.v7-slurm`; configured identity is `revodesign:revodesign`, numeric `129:137`, matching `getent passwd/group`.
- Strict Doctor across all discovered Runner Families passed with zero diagnostics.
- `runner-status --all --json` reports enabled `easifa` as `BUILD_STALE`: its active SIF exists but provenance is stale and no valid live receipt exists. Required next action is `build-sif` followed by live test.
- No production PASS receipt has been issued or promoted. The prior
  controller-identity failure was a repository defect: operator identity must
  not be compared with service identity. The corrected design delegates live
  scientific execution to a candidate one-off worker container, where actual
  execution UID/GID and every Slurm scheduler identity are checked. A sandbox
  Apptainer socket error is not production-host evidence.
- Candidate worker repair is implemented and focused worker/controller tests
  pass. A real target-host EasIFA acceptance is still required before prepared
  deployment can proceed. Keep maintenance enabled until that ordered sequence
  produces an exact current receipt.
- Live-test acceptance now rejects mismatched execution UID/GID, missing or
  mixed Slurm scheduler identities, and records the structured identity evidence
  in failed cases. Receipt validation applies the same scheduler identity check
  to every recorded workflow stage.
- The worker validates every request-declared fixture hash against the mounted
  fixture before copying it, and its DB import may create the run root before
  execution; only isolated result/workspace/upload children require fresh
  creation. The old underspecified executor request schema is rejected rather
  than treated as a compatibility path.
- Production admission reads only the controller-published per-runner
  attestation under `SERVER_DIR/readiness/`; controller readiness derivation is
  performed once after deployment, while missing or malformed evidence fails
  closed. The shared `RunnerReadinessStatus` type owns the READY definition for
  both controller and application code. Admin resource-policy updates remove
  the attestation immediately, providing deterministic invalidation without
  request-time SIF hashing or Doctor execution.
- Readiness publication runs through the configured service UID/GID in a
  throwaway server container, creates mode-0755/0644 service-owned storage, and
  atomically swaps a complete staged fleet into place. Restart invalidates
  evidence before runner-tree materialization and all stop/mutate steps;
  publication or finalizer failure removes partial evidence, leaving admission
  fail closed.
- Restart resolves and validates the configured service identity before it
  invalidates admission evidence. Username/group-only deployments therefore
  use their resolved numeric identity for service-context cleanup, while a
  conflicting explicit UID/GID fails without removing the current evidence.
- Final TODO blocker repair is implemented in the working tree: live-test uses
  the canonical server image build, launches a one-off candidate worker, mounts
  the selected Runner contract read-only, streams SIF hashes, captures every
  workflow-stage scheduler identity, and does not require operator membership
  in `RUNNER_GID`. The sandbox retry reached Docker image build but was blocked
  by denied access to `/var/run/docker.sock`; this is not target-host evidence.
- The latest local CI-equivalent non-browser run passed 752 tests with 4
  skips; GitHub Actions status/logs remain externally unavailable from this
  sandbox.

## Target-host acceptance (2026-09-08)

- Production operator is `yinying`; the selected environment is
  `.env.production.v7-slurm`; configured and host-resolved service identity is
  `revodesign` UID 129, GID 137.
- Strict Doctor across all enabled Runner Families passed with zero errors.
- Initial `runner-status --all --json` reported EasIFA `BUILD_STALE` with no
  current receipt. The existing `.next` candidate was verified against its
  current build provenance and SIF hash; no unrelated family was rebuilt.
- The first target-host EasIFA live-test reached candidate server image build,
  then exposed a repository defect: the one-off worker argv omitted the
  `docker compose` executable and began with `-f`. The focused fix is
  `6640c68`; its worker tests pass and the fix was pushed to the existing PR
  branch. The prior run's exact report is retained under the deployment
  `images/live-tests/easifa/` directory.
- GitHub Actions for `6640c68` are green: REvoCompute Tests, Server Compose
  FullStack, and build all passed. A post-fix target-host rerun still requires
  approved Docker/Slurm/Apptainer host access; prepared activation has not been
  attempted.
- The post-fix rerun from exact PR head `301a179` rebuilt the current EasIFA
  candidate (`sha256:86c4780163e2d9c7f9d6f11950c82ed57381a38aca72882e2fbdf6734377e53f`)
  and exposed two additional target-boundary defects before scientific
  acceptance could pass. Commit `16c79c7` restores exact-candidate
  `apptainer inspect` / `apptainer test` validation on the target host instead
  of attempting unsupported nested Apptainer execution inside the unprivileged
  one-off worker. Commit `7e6c268` points each candidate worker at its own
  isolated server root so production input verification reads the seeded
  fixture from the live-test upload tree rather than the production upload
  directory. The focused live-worker, executor, protocol, and Slurm tests pass
  (58 passed), and host-side validation of the exact candidate passes.
- The rerun from `7e6c268` proved one-off worker identity `129:137`, submitted
  Slurm job `4480`, and showed scheduler `USER=revodesign`. The job could not
  run because the only GPU node is `DOWN* (Not responding)`: `slurmctld` is
  active, but host `slurmd.service` has been failed since 2026-09-07 10:09 CST.
  Non-interactive recovery is blocked because restarting `slurmd` requires the
  host sudo password. The pending acceptance job was cancelled through the
  configured `revodesign` worker identity, leaving no orphaned Slurm job.
- Production Compose services remain healthy and maintenance is off. No PASS
  receipt was issued, EasIFA remains `BUILD_STALE`, and prepared activation was
  not attempted. After an operator runs `sudo systemctl restart slurmd`, rerun
  `live-test --runner easifa` from the latest exact PR head and continue only
  if the receipt records execution identity `129:137` and scheduler user
  `revodesign`.

## Dockerfile-to-Apptainer definition audit (2026-09-09)

The last Dockerfiles before their removal in `8dbb0e3` were compared with the
current definitions for all 14 Runner families. The comparison covered base
images, source repositories and revisions, package sets and pins, downloaded
assets and checksums, source patches, copied Runner files, runtime environment,
entry points, and external model/database mounts. This is a static migration
audit; a static match is not a substitute for an exact-current live receipt.

| Runner family | Audit result | Material differences and evidence |
| --- | --- | --- |
| `alphafold` | Intentional drift, live verified | Upstream changed from `c77e5d2` to `e5c2cdd`; JAX/NumPy changed from `0.4.35`/`1.26.4` to the upstream-compatible `0.4.26`/`1.24.3`; OpenMM and pdbfixer are now explicit. The staged patch, HH-suite, databases, parameters, and entry point remain present. Current target-host live test and API curl passed. |
| `alphafold3` | Intentional drift, live verified | CUDA base changed from 12.6.3 to 12.9.1. The AF3 source revision, HMMER checksum and patch, five pinned CMake dependency revisions, locked `uv` environment, databases, models, XLA settings, and entry point remain present. Current target-host live test and API curl passed. |
| `bioemu` | Functionally preserved; revalidation pending | Torch, JAX, BioEmu and constraints are preserved. Checkpoints and ColabFold parameters are external read-only mounts. The portable cache path replaces the Docker username-specific path. No exact-current `129:137` receipt is published. |
| `colabfold_af2` | Functionally preserved; revalidation pending | The same `1.6.2-cuda12` upstream image, entry point, and read-only `/mnt/colabfold` parameter mount are used. No exact-current `129:137` receipt is published. |
| `easifa` | Intentional drift, live verified | Bullseye changed to Bookworm after Bullseye mirror failures. The EasIFA source revision and pinned Hugging Face environment archive revision/SHA-256 are unchanged. The archive is the packaged Python/CUDA environment, not inference weights. Runtime EasIFA and ESM checkpoints come only from `/mnt/db/weights/easifa2` and `/mnt/db/weights/esm/checkpoints`, mounted read-only; Torch's legacy hub path is linked to that provisioned mount. Current target-host live test passed. |
| `esm` | Functionally preserved; revalidation pending | CUDA/Torch, all explicit Python dependencies, fork revision, helper scripts, read-only checkpoint mount, and entry point are preserved. No exact-current `129:137` receipt is published. |
| `esmdynamic` | Functionally preserved with image-composition drift; revalidation pending | Source revisions, cu126 Torch stack, OpenFold patch, stereo-chemical data and `TORCH_HOME` are preserved. The SIF retains the CUDA development base and compiler environment that the Docker multi-stage runtime discarded. This is a size/hardening difference, not a missing runtime component. |
| `freebindcraft` | Functionally preserved; revalidation pending | FreeBindCraft and ColabDesign revisions, JAX/OpenMM/OpenCL dependencies, bundled executables, read-only AF parameters and environment are preserved. No exact-current `129:137` receipt is published. |
| `mpnn` | Functionally preserved; revalidation pending | All five source revisions, the dependency file, baked HyperMPNN weights, removed duplicate LASErMPNN weights, external LigandMPNN/ThermoMPNN read-only mounts, and entry point are preserved. No exact-current `129:137` receipt is published. |
| `opendde` | Functionally preserved; revalidation pending | OpenDDE GPU package, HMMER/Kalign, root directory, external read-only data tree and entry point are preserved. No exact-current `129:137` receipt is published. |
| `placer-rfdiffusion` | Functionally preserved; revalidation pending | Both source revisions, bool-override patch, CUDA/Torch/DGL/e3nn stack, Python path, external RFdiffusion models and entry point are preserved. No exact-current `129:137` receipt is published. |
| `prime` | Functionally preserved; revalidation pending | Torch and scientific package pins, both external model directories, code manifest and entry point are preserved. Model loading is local-only. No exact-current `129:137` receipt is published. |
| `pssm_gremlin` | Intentional hardening; revalidation pending | The formerly floating Mambaforge base is pinned to `24.9.2-0`; the GREMLIN environment, scripts, database mounts and entry point are preserved, and the environment `PATH` is explicit. No exact-current `129:137` receipt is published. |
| `pythia_ddg` | Functionally preserved; revalidation pending | The source revision, baked checkpoints, CPU Torch dependency set, symlinks and entry point are preserved. No exact-current `129:137` receipt is published. |

### Cross-cutting migration findings

- Docker image users, `RUNNER_USERNAME`, ownership rewrites, and `USER` directives
  were deliberately removed. Apptainer executes as the Slurm allocation user;
  current acceptance proves UID 129, GID 137 and scheduler user `revodesign`.
- Docker `WORKDIR` directives were not translated into SIF metadata. This does
  not change the production path: Slurm supplies `--chdir=<task output>` and
  invokes the absolute `/app/revocompute/run.sh` path. Runner-owned resources
  are resolved through absolute paths or the script directory.
- Docker multi-stage builds were flattened because direct Apptainer definitions
  do not use Docker build stages. Consequently several SIFs retain Git/build
  packages, and ESMDynamic retains a CUDA development base. This increases
  image size and attack surface but does not remove the former runtime content.
- No inference weight was moved into `/tmp`. All operator-provisioned model and
  database mounts remain read-only. EasIFA's Torch hub points at the read-only
  ESM checkpoint mount. BioEmu uses temporary directories only for generated
  embedding/SO(3) scratch data, and ColabFold uses `/tmp` only for ordinary
  cache/config state while model parameters are read from read-only
  `/mnt/colabfold`.
- Runtime proxy variables remain cleared as in the Dockerfiles. Network fetches
  needed to construct a SIF, including the pinned EasIFA Hugging Face archive,
  occur during the build and may use the operator-selected build proxy.
- No missing source tree, pinned revision, dependency group, patch, copied
  Runner script, required environment variable, entry point, or external
  model/database mount was found in the 14-family static comparison.

### Current production consequence

The static migration audit passes, but full-fleet restoration does not. On
2026-09-09, `runner-status --all` reports only `alphafold`, `alphafold3`, and
`easifa`, all `READY`; those are the only readiness attestations currently
published. Their current live receipts record execution UID/GID `129:137` and
scheduler user `revodesign`. Production API curls completed through the real
API -> worker -> Slurm -> Apptainer -> result path for AlphaFold 2 and AlphaFold
3; the latest task IDs are `94874e5621b5d5b375b155e77853c6f0` and
`176b3d6602ed59ceed5276aa9c42d62e` respectively.

The 11 remaining families have historical 2026-09-06 live receipts, but those
receipts predate the current service identity and current code. They must be
rebuilt or matched to exact current provenance, live-tested as `129:137`, and
included in a successful prepared activation before the server can be called a
fully restored 14-family fleet. The next concrete action is to resume the full
prepared redeploy at BioEmu, then continue through the remaining families
without weakening exact-receipt admission.

## Open assessment items

- Concurrent restart finalization and admin resource updates do not yet share a
  generation or lock. A future resource revision should prevent an older
  in-flight readiness calculation from republishing evidence after an admin
  update invalidates it.

Before a Runner leaves the adaptation wait list or is admitted to production,
pin its upstream revision and assess its scientific I/O contract, executable
entry point, dependency/runtime environment, CPU/GPU and scheduler resources,
weights/databases and other assets, license/access constraints,
Docker/Apptainer feasibility, artifact types, storyboard needs, testing
strategy, and runtime-family placement.
