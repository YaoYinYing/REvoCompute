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
