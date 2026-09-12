# FAMPNN Runner family

This family adapts FAMPNN sequence design, sidechain packing, and site-saturation
mutation scoring from `richardshuai/fampnn` commit
`aaf788b1502ad95d5c5a84455cfc53f2544f3b45` (MIT). It remains separate from
the CPU MPNN family because upstream was validated with PyTorch 2.4.1 and CUDA
12.1 and performs full-atom diffusion on an accelerator.

Provision the three upstream checkpoints without renaming them:

```text
/mnt/db/weights/revocompute/fampnn/
├── fampnn_0_0.pt          # sidechain packing
├── fampnn_0_3.pt          # sequence design
└── fampnn_0_3_cath.pt     # mutation scoring
```

Normal task execution never downloads models. Operators should record SHA-256
checksums and the source commit in their deployment asset inventory before
enabling the family.

The files are tracked by the pinned upstream Git commit with these identities:

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| `fampnn_0_0.pt` | 42,304,481 | `afbdfda29e6f2a1bd340971bb226638afb1bf460cfbc29f115d3b5964622c006` |
| `fampnn_0_3.pt` | 42,304,481 | `8969b3f1f3c941178076c7800952595a18b56fd3828d15bb993d3ef537938a05` |
| `fampnn_0_3_cath.pt` | 33,902,872 | `81112a9b8d436d9baf5233a3603bac911c75b9782ced59dae5a2726316802218` |

Citation: Shuai et al., *Sidechain conditioning and modeling for full-atom
protein sequence design with FAMPNN*, bioRxiv (2025),
doi:10.1101/2025.02.13.637498.
