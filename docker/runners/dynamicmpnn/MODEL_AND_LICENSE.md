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

Provision the ProteinMPNN checkpoint before candidate validation:

```text
/mnt/db/weights/revocompute/dynamicmpnn/
└── model_params/
    └── proteinmpnn_v_48_020.pt
```

The family mounts the semantic resource root read-only. The checkpoint is not
included in the SIF, and normal Task execution performs no network download.
Record the source URL, license/access terms, byte size, and SHA-256 in the
operator asset manifest when provisioning it. The exact resource identity must
be captured by target-host live-test evidence before enablement.

## Citation

Dauparas et al., *Robust deep learning-based protein sequence design using
ProteinMPNN*, Science 378 (2022), doi:10.1126/science.add2187.
