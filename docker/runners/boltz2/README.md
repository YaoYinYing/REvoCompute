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
digest and is refused, not silently accepted. Before execution, provision the exact
files through the reviewed operator asset process, extract `mols.tar` to `mols/`,
verify licensing and provenance, and commit the five verified SHA-256 lines (four
files plus the `mols` tree) into `model-assets.sha256`. The image and runtime must
never download them. No receipt or ready state exists.

Expected host and container mount: `/mnt/db/weights/boltz2` (read-only).
Writable cache, scratch, and output remain task-local.

## Build and acceptance

The direct Apptainer definition pins upstream source and installs upstream's
documented CUDA extra. No dependency lock exists yet: commit a resolved lock
after the first verified build, before any scientific acceptance. Run Doctor and
family fast tests without assets. A candidate SIF can be built and its CLI
tested without weights, but scientific smoke cannot pass until all four files
and hashes are provisioned. The next action is to provision and review those
assets, update the manifest, build the SIF, then run both smoke cases on the
target Slurm/Apptainer host and record exact resource observations. This family
is not ready for submissions before those steps.
