# dynamicMPNN model and license record

## Source

- Upstream project: `https://github.com/TCoulth/dynamicMPNN`
- Pinned commit: `af351ee737bdb2ca2804a308d9abc8fd7c303270`
- Code license: MIT
- Runtime: CPU PyTorch 2.2.1, matching the upstream inference dependency

The public TaskType exposes the benchmarked dynamic pI and surface-patch
controls plus motif avoidance. Upstream's experimental motif-insertion path is
not exposed because the pinned README states that it was not benchmarked.

## External model resource

The pinned upstream
`https://github.com/TCoulth/dynamicMPNN/blob/af351ee737bdb2ca2804a308d9abc8fd7c303270/get_model_params.sh`
downloads the original ProteinMPNN checkpoint from
`https://files.ipd.uw.edu/pub/ligandmpnn/proteinmpnn_v_48_020.pt`.
Reuse the already managed LigandMPNN resource:

```text
/mnt/db/weights/ligandmpnn/
└── proteinmpnn_v_48_020.pt
```

The file is 6,681,301 bytes and has SHA-256
`c9cb4a671d79604111231f8dbfc7c590e06f1197453b7a6854ac6661a642f5bd`.
The family mounts this resource root read-only. The checkpoint is not included
in the SIF, and normal Task execution performs no network download.

## Citation

Dauparas et al., *Robust deep learning-based protein sequence design using
ProteinMPNN*, Science 378 (2022), doi:10.1126/science.add2187.
