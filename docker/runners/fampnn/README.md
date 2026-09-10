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

Citation: Shuai et al., *Sidechain conditioning and modeling for full-atom
protein sequence design with FAMPNN*, bioRxiv (2025),
doi:10.1101/2025.02.13.637498.
