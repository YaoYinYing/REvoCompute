# Additional MPNN models

## frustraMPNN (separate family)

The dedicated `frustrampnn` family pins `YaoYinYing/frustraMPNN` commit
`3a03cdc300bfe24c4bb70e60207118532bc73b3b` (BSD-3-Clause). It predicts a
site-saturation local-frustration table rather than designing sequences.
Provision `fireprot_train_weights.ckpt` and `megascale_train_weights.ckpt`
under `/mnt/db/weights/revocompute/frustrampnn/`, record their SHA-256 values,
and mount the directory read-only. Runtime downloads are not used.

Citation: Beining et al., *FrustraMPNN: An ultra-fast deep learning tool for
proteome-scale analysis of deep mutational single-residue local energetic
frustration in proteins*, bioRxiv (2026), doi:10.64898/2026.01.22.701012.

## dynamicMPNN

The `dynamicmpnn` TaskType pins `TCoulth/dynamicMPNN` commit
`af351ee737bdb2ca2804a308d9abc8fd7c303270` (MIT). The project is a direct
LigandMPNN adaptation and therefore shares this family's PyTorch 2.2.1 CPU
runtime. It exposes the benchmarked pI and surface-patch controls plus motif
avoidance. The upstream README says motif insertion was not benchmarked as of
2026-04-21, so that experimental path is intentionally not public.

Provision `proteinmpnn_v_48_020.pt` beneath
`/mnt/db/weights/revocompute/dynamicmpnn/model_params/`. Cite Dauparas et al.,
*Robust deep learning-based protein sequence design using ProteinMPNN*,
Science 378 (2022), doi:10.1126/science.add2187, and record the dynamicMPNN
repository revision in derived-work provenance.
