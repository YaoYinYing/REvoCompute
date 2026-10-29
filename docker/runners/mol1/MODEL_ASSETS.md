# Mol-1 model and reference assets

Mol-1 inference needs operator-provisioned weights and reference files; a
missing file stops the run before the checkpoint is loaded. The model does not
download weights or reference data during a task. Template use downloads PDBe
hit structures into task scratch on every run (see Runtime decisions). This
page records the pinned identities and the mount layout; it does not copy
upstream documentation.

## Pinned upstream

| Item | Value |
| --- | --- |
| Repository | <https://github.com/molence/Mol-1> |
| Commit | `7480cc41a7c64b5c517709184bdc81c08dbd5fdb` (2026-10-28) |
| Source archive SHA-256 | `917d2b5492f4f9f6034650af7e6c88b9886f99a2e31f2c7aa60d4de7c7f43990` |
| Distribution | `molence` 1.0.0 |
| Code license | Apache-2.0 (derived from Protenix `bd54a05d047b8925a241056f36d619700604068a`, Apache-2.0) |
| Python | 3.12 or 3.13 |

The source is installed from the pinned commit; the SIF does not vendor it in
this repository. The release host publishes the checkpoint and archives under
the same project; no separate weights license is published. Reference data
derives from wwPDB, the Chemical Component Dictionary, and PDB sequence
clusters, and remains operator-managed under those publishers' terms. The
upstream README marks its citation section "coming soon", so the Task carries
no citation rather than an unpublished one.

## Layout under `MOL_ROOT_DIR`

`MOL_ROOT_DIR` is `/mnt/db/weights/mol1` on the target host: runner weights live
under `/mnt/db/weights/<model>/`, mounted read-only at the same path.

```text
$MOL_ROOT_DIR/
├── checkpoint/mol-1-base.pt
├── common/
│   ├── components.cif
│   ├── components.cif.rdkit_mol.pkl
│   ├── clusters-by-entity-40.txt
│   ├── obsolete_release_date.csv
│   ├── obsolete_to_successor.json          # template use only
│   └── release_date_cache.json             # template use only
└── search_database/
    └── pdb_seqres_20261001.fasta           # template search only
```

`run.sh` exposes this read-only mount through a fresh task-private writable
root: it creates an empty `mmcif/` directory and symlinks `checkpoint/`,
`common/` and `search_database/` into it, then points `MOL_ROOT_DIR` at that
root. Template featurization downloads PDBe structures into `mmcif/` on every
run, and the whole scratch root disappears with the allocation. There is no
operator-managed `mmcif/` cache.

## Artifact identities

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| `checkpoint/mol-1-base.pt` | 2,393,615,173 | `d5b83a86884aa6870565b1a249e8f13c232dfc6dfa311089ab0c7868212b6bd6` |
| `common/components.cif` | 518,765,615 | `64f53e4d72c8f919d9d2afd34183df7c0b6211929dfe0eeb865fad82cd1374d5` |
| `common/components.cif.rdkit_mol.pkl` | 149,618,245 | `b59c9ec2ee52b8e695d8669096d0496933ff374b8bf7d2e56025387d22df863a` |
| `common/clusters-by-entity-40.txt` | 22,559,913 | `d0de9ca3939d83592a451901c50d52c17dcfc0d60119986f1a44d839d40f9c00` |
| `common/obsolete_release_date.csv` | 145,877 | `8b9d080c9bccaaa20f71dffa214c0fd19e2a6f76710d4415e2ae7aff457a7fa2` |
| `common/obsolete_to_successor.json` | 82,029 | `1bf12b00e56822e90891f5b352232dad4a13a660e89399423e0dc85b22102661` |
| `common/release_date_cache.json` | 13,015,253 | `0020fbfb2881cee7c21f2d9136569c371b9cf2939e54dea312afcbd3ba50d188` |
| `search_database/pdb_seqres_20261001.fasta` | 391,402,052 | `a2c9c533845fa9e7c8c76c79b902587eaf563730e4694803af475bc13a961f03` |

The archives those files come from:

| Archive | Bytes | SHA-256 |
| --- | ---: | --- |
| `common.tar.gz` | 228,632,768 | `f6f953dac716bf89b46799738c85f5e0d4626e0cc905bb805a161671fd5cf898` |
| `search_database.tar.gz` | 63,566,707 | `66cf966d64c9f346e55f9d2121d47ebb1d046a88e93437c149e91d3fdfbcf57d` |

All are published at
`https://mol-1-release.oss-cn-shanghai.aliyuncs.com/`. The training-only
`mmcif_msa_template.tar.gz` (9.8 GB) is not used by inference and is not pinned
here.

## Provisioning

```bash
export MOL_ROOT_DIR="${MOL_ROOT_DIR:?set the operator asset root}"
mkdir -p "$MOL_ROOT_DIR/checkpoint"
curl -fL -o "$MOL_ROOT_DIR/checkpoint/mol-1-base.pt" \
  https://mol-1-release.oss-cn-shanghai.aliyuncs.com/checkpoint/mol-1-base.pt
curl -fL -o /tmp/common.tar.gz https://mol-1-release.oss-cn-shanghai.aliyuncs.com/common.tar.gz
curl -fL -o /tmp/search_database.tar.gz \
  https://mol-1-release.oss-cn-shanghai.aliyuncs.com/search_database.tar.gz
tar -xzf /tmp/common.tar.gz -C "$MOL_ROOT_DIR"
tar -xzf /tmp/search_database.tar.gz -C "$MOL_ROOT_DIR"
(cd "$MOL_ROOT_DIR" && sha256sum -c /path/to/repo/docker/runners/mol1/model-assets.sha256)
```

`model-assets.sha256` is verified on every run. With templates enabled,
`search-assets.sha256` is verified too, but its `search_database/` entry is
required only for `template_mode: search`: supplied templates read the
release-date indexes and never run the sequence search.

## Runtime decisions

- **CUDA 12, PyTorch 2.10.** The target A100 host driver predates CUDA 13, so
  the image uses the upstream `cuda12` stack: torch 2.10 with cuequivariance
  0.10.0 cu12 operator wheels. The upstream default Triton is installed by
  torch.
- **PyTorch LayerNorm.** The fused LayerNorm extension compiles CUDA at first
  use. This is a runtime image without nvcc, so `LAYERNORM_TYPE=torch` is set.
  A devel image with a matching toolchain can enable `fast_layernorm`.
- **Token admission.** `MOL1_MAX_TOKENS` (default 800 in `runner.yaml`) bounds
  the conservative token estimate before the checkpoint is loaded. Peak device
  memory grows roughly with the square of the token count and is card-specific;
  the upstream measurements on a 95 GiB Blackwell are not a 40 GiB A100 fit
  claim. Raise the bound only after measuring the target card.
- **MSA search.** `msa_mode: search` uploads protein sequences to
  `https://api.colabfold.com`. The upstream client retries a connection error
  forever, so the runner probes the service first and bounds the search step by
  `MOL1_SEARCH_TIMEOUT` (default 3600 s). Search is refused when any protein or
  RNA MSA is supplied: upstream re-searches every protein chain in a job with
  one missing chain, replacing supplied MSAs. Prediction never searches: all
  paths must exist before the checkpoint loads.
- **Template search.** `template_mode: search` runs HMMER against
  `pdb_seqres_20261001.fasta` and requires `msa_mode: search`. Template use with
  `.a3m` hits downloads each hit structure from
  `https://www.ebi.ac.uk/pdbe/entry-files/download/<id>.cif` on every run into
  the task-private `mmcif/` directory. Inline JSON templates do not need that
  download.
- **Not offered.** RNA MSA search (its Rfam/RNAcentral/NT-RNA databases are not
  distributed with this family), `.hhr` template uploads, and `.mol` ligand
  uploads (convert to `.json` templates or `.sdf`/`.mol2`).
