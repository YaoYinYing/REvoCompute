# Runner Adaptation and Deployment Handoff

Last updated: 2026-09-11 (Asia/Shanghai)

## Resume here

Read `AGENTS.md`, `LONG_TASK_HANDLING.md`, `IMPLEMENTATION_STATE.md`, and
`docs/runner-guide/wait-list.md` before changing code. This work is on branch
`feat/runner-adaptation-remaining`.

The repository was checkpointed at:

- `803c6f5 feat: checkpoint batch C runner integrations`
- `1927884 fix: validate RFdiffusion2 motif atom selections`

The pre-deployment recovery stash is intentionally retained:

```text
stash@{0}: On feat/runner-adaptation-remaining: checkpoint: batch C runner integrations before deployment
```

Do not drop it until delivery is complete. Check `git status --short` before
resuming; the intended handoff boundary is a clean tracked worktree.

## User constraints

- Use official sources only. Do not use mirrors.
- Use the configured proxy for downloads. A user-authorized direct-connect
  diagnostic was tried only for Protenix and also failed.
- Keep weights outside SIF images and mount them read-only.
- Build Apptainer images serially. Concurrent builds previously collided through
  generic `/tmp/build-temp-*` cleanup.
- A runner is not promoted until direct-SIF validation and real
  Task -> SLURM -> Apptainer acceptance succeed, followed by authenticated public
  API validation.
- Do not expose credentials in commands, logs, commits, or reports. Put temporary
  credentials in mode-0600 files, then revoke and remove them.
- Continue through PR checks, deployment, and live tests once work resumes.

## Production and wait-list state

Production was last verified healthy at 23/23 runner families `READY`. The
documented wait list still contains eight families until live acceptance and
promotion change it:

1. EvoSplit
2. RFdiffusion2
3. Foundry
4. PPIformer
5. Mu-Protein
6. Protenix
7. Pallatom
8. GeoDock

Current production families:

```text
gremlin,pythia_ddg,esm,opendde,bioemu,easifa,mpnn,prime,
placer-rfdiffusion,alphafold,colabfold_af2,esmdynamic,freebindcraft,
alphafold3,codontransformer,gremlin_lh,dynamicmpnn,frustrampnn,fampnn,
boltz,simplefold,chai1,esmfold2
```

## Implemented runner work

The checkpoint contains complete runner-family implementations for EvoSplit,
RFdiffusion2, Foundry, PPIformer, Pallatom, and GeoDock, plus the secure
Mu-Protein asset conversion path. See `IMPLEMENTATION_STATE.md` for detailed
contracts and `docs/runner-guide/wait-list.md` for the current intake record.

RFdiffusion2's unsupported JSON-Schema `object` parameter was fixed in `1927884`.
`contig_atoms` is now a bounded string grammar such as
`A106:NE,CD,CZ;A166:OD1,CG`; parsing rejects malformed, duplicate, non-string,
empty, and oversized values before inference while producing the upstream dict
override.

## Verification state

The combined runner gate before the RFdiffusion2 fix was:

```text
130 passed, 1 skipped
```

The focused post-fix gate was:

```bash
pytest -q tests/test_rfdiffusion2_runner.py tests/test_parameter_contract_architecture.py
```

Result: `12 passed`. Python compilation, Draft 2020-12 smoke-parameter
validation, and `git diff --check` also passed.

`make test` was run before the fix. It reached 100% but did not exit after
teardown and was interrupted. Its relevant outcomes were:

- one real failure: the RFdiffusion2 `contig_atoms` object schema; now fixed and
  covered by the focused passing gate above;
- 13 browser-test errors because Chromium cannot launch under the host sandbox,
  matching the previously documented environment limitation;
- no other observed product failures before the 100% mark.

Do not describe that interrupted run as a clean full-suite pass. On resume, run
the combined scoped gate again, then a broad non-browser gate or `make test` in
an environment where Chromium can launch.

## Validated images and assets

Final direct images already validated with embedded and explicit `%test`:

```text
/mnt/data/srv/revodesign/server-slurm/images/validation/pallatom_v1.sif
sha256 a9e27c7cbabebe026d8c50ebe9e18f3df18d8e9672fd89a0418f33071df50a9e

/mnt/data/srv/revodesign/server-slurm/images/validation/evosplit_v1.sif
sha256 3f857d9d9e586ed3e48e8104c8a96b85a48fbf59662c9053e681964c3448233c
```

Do not delete these images.

Provisioned read-only assets include:

- RFdiffusion2 `RFD_173.pt`: 1,338,843,322 bytes,
  SHA-256 `590e126057f780afc1249d29545f0f90635562b1a3df5aff013afcfc39c3d3c3`.
- PPIformer: four files under `/mnt/db/weights/revocompute/ppiformer/weights/`;
  checksums are recorded in its manifest.
- Pallatom `params_Pallatom.npz`: 71,002,706 bytes,
  SHA-256 `57dff1c37cb1d99984ab664a7dc96e2a44afb100ea6f1f3c397dbe838124bc2f`.
- GeoDock checkpoint: SHA-256
  `4a323ebaba152285a2444dcbf68de2dba7ec77f7d61a6d8b693c75169900d162`;
  ESM2 and contact-regression assets are also provisioned.
- Both official Mu-Protein checkpoints are provisioned with published MD5 and
  observed SHA-256 receipts; see the wait-list document.

## RosettaCommons licensing research

This section is an engineering disposition, not legal advice.

Do **not** create one blanket `RosettaCommons Non-commercial` policy for every
RosettaCommons project. The official download catalog is a mixed-license index:
classic Rosetta/PyRosetta and legacy Rosetta-DL are restricted, while many newer
tools are BSD, MIT, or Apache licensed.

### Classic Rosetta and PyRosetta

- Rosetta is source-available, not OSI open source. Its free license permits only
  internal noncommercial use and excludes commercial services, work for
  for-profit entities, and use for commercial advantage.
- PyRosetta has parallel restrictions and requires a valid Rosetta entitlement.
- Redistribution is prohibited. A paid commercial license is required for
  commercial use and fee-for-service work.
- The standard commercial site license does not itself authorize making Rosetta
  available to third parties over the Internet. Public/API service requires a
  bespoke written grant from UW/CoMotion.
- Rosetta-derived molecule IP has no stated reach-through, but that does not
  relax software access or service restrictions.

Therefore, a policy identifier such as `rosetta_software_noncommercial` is
reasonable only for runners that actually contain/use classic Rosetta or
PyRosetta, and only for internal eligible users. It must not imply that a public
API is permitted. A separate commercial/API entitlement would need to reflect
the operator's executed UW agreement.

Official sources:

- https://rosettacommons.org/software/download/
- https://github.com/RosettaCommons/rosetta/blob/main/LICENSE.md
- https://github.com/RosettaCommons/rosetta/blob/main/LICENSE.PyRosetta.md
- https://rosettacommons.org/software/licensing-faq/
- https://els2.comotion.uw.edu/product/rosetta
- https://rosettacommons.org/2024/03/08/announcing-rosettas-transition-to-a-public-repository-including-licensing-changes/

### Legacy Rosetta-DL

The Rosetta-DL license expressly covers software, data, and weights. It allows
internal nonprofit/noncommercial research only, prohibits external transfer,
and requires a paid agreement for commercial or fee-based services. Apply a
distinct policy such as `rosetta_dl_noncommercial` only to artifacts actually
under that license.

Source:

- https://github.com/RosettaCommons/Rosetta-DL/blob/main/LICENSE.md

The download catalog currently labels RFdiffusion, RoseTTAFold, DeepAb,
FvHallucinator, MaSIF, Protein-Seq-Des, and trRosetta2 as Rosetta-DL. The current
RFdiffusion repository license, however, explicitly applies BSD terms to source
and referenced weights. This conflict should be clarified before commercial
deployment.

### RFdiffusion2

- Official catalog and repository label its code BSD-3-Clause.
- The stock license does not expressly state that separately hosted RFD2
  checkpoint files are covered. Hold commercial/public deployment until written
  UW/IPD confirmation or an explicit operator legal acceptance of that risk.
- The upstream environment documents PyRosetta, but the supported REvoCompute
  path disables silent output and side-chain idealization and does not install
  PyRosetta. Prove this path with a real run and retain regression guards before
  claiming that Rosetta/PyRosetta terms do not attach.
- Critical: upstream vendors `lib/chai` under the Chai Discovery Community
  License, which prohibits commercial use, drug discovery, and all third-party
  service offerings. The current SIF clones the full tree. Remove
  `/opt/rfdiffusion2/lib/chai` from the image and prove the supported path has no
  Chai imports/references before any public API deployment.
- Preserve embedded third-party notices for rf2aa/SE3Transformer and
  se3_flow_matching.

Sources:

- https://github.com/RosettaCommons/RFdiffusion2/blob/main/LICENSE.md
- https://raw.githubusercontent.com/RosettaCommons/RFdiffusion2/main/setup.py
- https://rosettacommons.github.io/RFdiffusion2/installation.html
- https://github.com/RosettaCommons/RFdiffusion2/blob/main/lib/chai/LICENSE.md

### Foundry

- Foundry code, RF3, MPNN, and RFD3 are cataloged as BSD-3-Clause.
- Foundry has no Rosetta/PyRosetta dependency, so classic Rosetta restrictions do
  not attach merely because RosettaCommons owns the repository.
- Official documentation downloads checkpoints, and the official default Docker
  image includes them. Docker Hub describes Foundry as fully BSD-3-Clause. This
  is favorable context, but the repository license never expressly scopes its
  grant to separately hosted checkpoints.
- Keep Foundry's commercial/public deployment held for written checkpoint-scope
  confirmation or explicit operator legal acceptance. Do not redistribute
  checkpoints in the meantime; keep them externally provisioned and read-only.

Sources:

- https://github.com/RosettaCommons/foundry/tree/production
- https://github.com/RosettaCommons/foundry/blob/production/LICENSE.md
- https://hub.docker.com/r/rosettacommons/foundry
- https://raw.githubusercontent.com/RosettaCommons/foundry/production/src/foundry/inference_engines/checkpoint_registry.py

### Useful explicit precedents

RFDpoly and the current original RFdiffusion license explicitly apply BSD terms
to source plus referenced model weights. That explicit wording is what is absent
from Foundry and RFdiffusion2.

- https://github.com/RosettaCommons/RFDpoly/blob/main/LICENSE.md
- https://github.com/RosettaCommons/RFdiffusion/blob/main/LICENSE

## Other blockers

- Protenix: official ByteDance endpoints fail TLS through the required proxy.
  Two bounded user-authorized direct probes, including IPv4/TLS 1.2, also failed
  with `SSL_ERROR_SYSCALL`. No mirror was used and no partial file remains.
- Mu-Protein: secure tensor-only conversion exists, but the legacy
  Fairseq/Torch inference closure and official score reproduction are not yet
  validated. A developer-local normalization CSV remains unavailable.
- GeoDock: bundled checkpoint is in an MIT repository, but the external Meta
  ESM2 weight-use scope still needs explicit operator/legal acceptance.
- GitHub CLI authentication was invalid when last checked. Push/PR creation may
  require re-authentication.
- The previous public-API test credential is invalid. Create a temporary,
  fully-revoked test identity during the authorized deployment workflow.

## Recommended resume sequence

1. Confirm `git status`, both checkpoint commits, and `stash@{0}`.
2. Add tests and an image-build change that removes RFdiffusion2's `lib/chai`
   subtree; prove the supported launcher path has no Chai or PyRosetta dependency.
3. Re-run the combined runner and architecture gates.
4. Finish direct SIF builds/tests serially: PPIformer, GeoDock, RFdiffusion2,
   Mu converter, then Foundry where legally useful. EvoSplit and Pallatom images
   are already validated.
5. Promote only legally/scientifically cleared families. PPIformer is the
   clearest unrestricted candidate; Pallatom requires its existing noncommercial
   entitlement. EvoSplit remains technically clear subject to its asset checks.
6. Run real Task -> SLURM -> Apptainer living tests and record walltime, CPU,
   host memory, GPU memory/utilization, manifests, logs, and artifacts.
7. Prepare and restart the union of old and newly accepted runners; verify all
   runner readiness and old-runner regressions.
8. Create a temporary authenticated API test identity, grant only required
   entitlements, submit public API smoke tests, then revoke and remove it.
9. Update `IMPLEMENTATION_STATE.md` and the wait list from actual acceptance
   evidence, checkpoint, push, open/update the PR, batch review feedback, and
   babysit CI/redeployment through success.

No Apptainer build, pytest process, deployment, or live-test process should be
running at handoff time.
