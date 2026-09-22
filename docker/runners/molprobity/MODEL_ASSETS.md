# MolProbity reference data

MolProbity validation uses no trained model or checkpoint, but it does need
reference data that the `cctbx-base` wheel deliberately does not ship:

- **Top8000 rotamer and Ramachandran contour tables** — `mmtbx.rotamer`
  resolves these as `chem_data/rotarama_data` and refuses to score a structure
  when they are missing.
- **Chemical-component restraint dictionary** — `mmtbx.monomer_library`
  resolves this as `chem_data/geostd` (or `chem_data/mon_lib`). Without it
  model interpretation fails with "Cannot find CCP4 monomer library".

Both are provisioned read-only beneath
`/mnt/db/weights/revocompute/molprobity` and mounted at the identical container
path. The image contains no copy: the definition only creates a
`<prefix>/chem_data` symlink to the mount.

| Provisioned payload | Bytes | SHA-256 | Source |
| --- | ---: | --- | --- |
| `rotarama_data/` (27 `.data` contour grids, extracted) | 52 MB | per-file digests in `model-assets.sha256` | `rlabduke/rotarama_data` revision `e6cf02e6e5becf466dbbc28eb73a9cb034a5c1c6` (file source SHA-256 `2f500a76642d9a17d9f0a50cc73b0268e37d1dd7c0eb712e844c3233fa2a0fa5` for `rota8000-arg.data`) |
| `geostd/` (CCP4/GeoStd restraint dictionary, `.cif` only) | 745 MB in 55,742 `.cif` files | list/energy files in `model-assets.sha256` | `phenix-project/geostd` revision `4e1c1c0444d9ab9c4a1e01626011ea0f62fddb16` (`list/mon_lib_list.cif` SHA-256 `00e63e4ec2d7231681679b9123158e2621a040930799a74f39483e79ef7fe91a`) |

The committed `model-assets.sha256` covers every file the adapter verifies
before a run: the rotarama `.data` grids it reads, `geostd/list/mon_lib_list.cif`,
`geostd/list/geostd_list.cif`, `geostd/ener_lib.cif`, and
`geostd/geostd_ener_lib.cif`. A full per-file manifest for the contour grids ships alongside as
`rotarama-data.sha256`; the 55,742-file GeoStd tree is identified by its pinned
commit plus the four list/energy files above rather than by a committed digest
list, and the operator can regenerate one with
`find geostd -name '*.cif' -type f -exec sha256sum {} +`.

## Two caches the operator must generate, not download

`cctbx-base` ships no usable reference-data cache. Two derived artifacts are
built once on the host, against the exact mounted data, and then verified like
any other asset:

1. `rotarama_data/rotarama.dlite` + `rotarama_data/*.pickle` — produced by
   `mmtbx.rebuild_rotarama_cache` (the cache provisioned on this host hashes to
   `4c240458db5294bd0091191981fa75e7861311a4eba13762e7b80639b5d17ab3` for
   `rotarama.dlite`). `RotamerEval` compares source mtime/md5 against this dlite
   and raises "*.pickle files are missing or out of date" when they disagree, so
   it must be regenerated whenever the `.data` files change.
2. Nothing for GeoStd: its `.cif` files are consumed directly, so the archives
   are simply unpacked.

## Provisioning record (verified locally on the build host)

The tables below were computed from the actual tree, not from documentation.

- `rlabduke/rotarama_data` `e6cf02e6e5becf466dbbc28eb73a9cb034a5c1c6` contains
  27 `.data` files totalling 52 MB; `git archive` of that revision hashes to
  `065f4d8871aabd7f14ee06b21ca6774c07072bb1565a470cd28f50dda82fec06` (7,995,044 bytes).
- `phenix-project/geostd` `4e1c1c0444d9ab9c4a1e01626011ea0f62fddb16` contains
  1.9 GB of `.cif` plus Amber `.mol2`/`.frcmod` files. Only the `.cif` subset is
  provisioned (745 MB); the Amber files are not read by MolProbity and are
  dropped. A `.cif`-only `tar.gz` of that subtree hashes to
  `860fee6aef8892a71536fc2325514ec14a83846bccdbdce5c1ce20839e115b52` (181,748,005 bytes).

Provision with mode `755` directories and `444` files.

## Why the layout is a symlink, not a copy

`libtbx` resolves `chem_data/rotarama_data` through its environment's
`repository_paths`, which includes the virtual-environment prefix.
`mmtbx.chemical_components` independently probes
`chem_data/chemical_components`. The definition therefore creates
`<prefix>/chem_data` as a symlink to the single mounted resource root, which
makes both resolvers find the read-only mount without placing a second copy in
the image. A dedicated `<prefix>/chem_data` directory that already exists in the
base image would defeat this, so the definition removes the empty directory
first.

The mount itself therefore has to present both names. `chem_data/geostd` is the
CCP4/GeoStd restraint dictionary, and `chem_data/chemical_components` is a
symlink to it, because that is the second path the resolver probes.

## Provisioning state

The `cctbx-base` wheel is installable, the validation code is verified, and the
read-only reference-data mount is provisioned on this host. Verified with
`sha256sum -c` from `chem_data/`:

- `chem_data/rotarama_data/` — 27 `.data` contour grids, `rotarama-data.sha256` all OK
- `chem_data/geostd/` — 55,742 `.cif` files; the 31 entries of `model-assets.sha256` all OK
- `chem_data/chemical_components` — symlink to `geostd`, so
  `mmtbx.chemical_components.find_data_dir()` resolves

The derived rotarama cache **is** provisioned: `mmtbx.rebuild_rotarama_cache`
was run once inside the built image against this mount, producing
`rotarama.dlite` and 23 `.pickle` files beside the contour grids. Without them
`RotamerEval` raises "chem_data/rotarama_data/*.pickle files are missing or out
of date" and `rotalyze` fails. The `.pickle` files carry the absolute source
paths of the `.data` files they were built from, so the cache must be
regenerated if the mount path or the contour grids ever change.

A missing or altered asset still fails closed with "MolProbity reference data is
missing: chem_data/rotarama_data".
