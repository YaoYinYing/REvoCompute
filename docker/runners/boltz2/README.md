# Boltz-2 Runner Family

This is an independent family for upstream Boltz 2.2.1 at commit
`b1ebfc46ecf57f5414e0d1a6f9027bbb122c53bc` (MIT). Boltz-1 remains in
`docker/runners/boltz/` and is unchanged.

## Operations

`boltz2_predict` publishes upstream mmCIF structures and confidence JSON.
`boltz2_affinity` additionally requires one protein target, one ligand chain and
one upstream `properties.affinity` entry. Affinity is not advertised for nucleic
acid targets or other ligand scenarios. `affinity_pred_value` is the model's
`log10(IC50)` prediction with IC50 in µM; lower values indicate stronger
predicted binding. It is not measured affinity, binding free energy, or
experimental validation. `affinity_probability_binary` is an upstream
binder-versus-decoy prediction score.

Each protein must explicitly use `msa: empty` or reference a supplied A3M/CSV
via a path confined to the uploaded alignment role. An omitted MSA is rejected
rather than silently treated as single-sequence mode. No online MSA option is
exposed. YAML is accepted only through named input roles; arbitrary path-bearing
references and non-local MSA paths are rejected. Upstream mmCIF and JSON are
retained without conversion.

## Assets: ASSET_BLOCKED

`/mnt/db/weights/boltz2` is absent at implementation time. Do not infer readiness
or create/download model assets. The read-only mount must contain all of:

- `ccd.pkl` — upstream Boltz-1 CCD dictionary consumed by Boltz-2 YAML parsing.
- `mols.tar` and extracted `mols/` — Boltz-2 molecular component library. The
  extracted `mols/` tree is what `load_canonicals` actually reads at inference,
  so it is bound by a deterministic SHA-256 tree digest recorded in
  `model-assets.sha256` under the name `mols` (per-file SHA-256 over each regular
  file, keyed by its relative path, symlinks refused). `mols.tar` is also
  byte-verified; the operator extracts it once — the family never extracts or
  downloads at runtime.
- `boltz2_conf.ckpt` — structure/confidence model checkpoint.
- `boltz2_aff.ckpt` — affinity model checkpoint.

The upstream v2.2.1 downloader identifies these names, but does not publish
immutable SHA-256 values or a complete size inventory. Consequently the committed
`model-assets.sha256` is deliberately unpopulated (comments only) and the adapter
fails closed with `ASSET_BLOCKED`. Tampering with any extracted molecule file —
even while `mols.tar` and both checkpoints are byte-identical — changes the tree
digest and is refused, not silently accepted. The image and runtime never
download assets. No receipt or ready state exists.

### Provisioning and acceptance runbook

1. Obtain the four files from the pinned upstream distribution and record the
   source URL, licence, version, size, and SHA-256 for each.
2. Place them under the host root `/mnt/db/weights/boltz2` with directory `755`
   and file `444`; extract `mols.tar` once to `/mnt/db/weights/boltz2/mols`.
   Do not copy the assets into the SIF or a task workspace.
3. Review every licence; Boltz-2 model assets require an explicit entitlement
   decision before any submission is enabled.
4. Generate the extracted tree digest with `adapter._tree_digest(mols_dir)` and
   commit the five reviewed lines (four files plus `mols`) to
   `model-assets.sha256`. Any later mutation of `mols/` must fail verification.
5. Mount the root read-only at the same container path; confirm the service UID
   can read every file and that compute nodes see the same tree.
6. Build the candidate SIF as `boltz2_v1.sif.next`, run `apptainer inspect` and
   `%test`, run strict Doctor, then run both `test.yaml` smoke cases on the
   target Slurm/Apptainer host. The candidate build must record the resolved
   dependency lock digest and `%test` output; the smoke receipt must record the
   exact SIF, bundle, source commit, asset digests, MSA provenance, seed,
   effective walltime, CPU/RSS, GPU memory, GPU utilisation, and the accepted
   artifact tree. Absent any of these, report `NOT READY`.

## Dependencies

`requirements.lock` is a fully pinned, hash-locked closure resolved from the
pinned upstream `pyproject.toml` plus `constraints.txt` with:

```bash
uv pip compile pyproject.toml --extra cuda -c constraints.txt \
  --python-version 3.11 --python-platform x86_64-unknown-linux-gnu \
  --generate-hashes --no-annotate -o requirements.lock
```

The resolution selected CUDA 12.6 wheels (`torch==2.7.0`,
`cuequivariance==0.5.1`, `numpy==1.26.4`) and the matching
`nvidia/cuda:12.6.3-cudnn-runtime-ubuntu22.04` base. Two consecutive resolutions
were byte-identical. This proves reproducibility of the resolver output, not a
successful build: the candidate SIF must still install the lock with
`--require-hashes` and record `%test`.

## Output integrity

Every published `*_model_*.cif` must contain at least one `_atom_site` row with
finite `Cartn_x/y/z`, an atom identity, and a residue identity; a zero-byte or
header-only file fails the Task. An affinity Task additionally fails if upstream
does not publish `affinity_*.json`. The affinity values remain model predictions,
not measured affinity.

## Build and acceptance

The direct Apptainer definition pins the upstream source commit and installs the
committed hash-locked dependencies. Run Doctor and family fast tests without
assets. A candidate SIF can be built and its CLI tested without weights, but
scientific smoke cannot pass until all assets and reviewed digests are
provisioned. This family is not ready for submissions before the runbook above
completes.
