# P2Rank model assets

P2Rank's ligandability model is part of its MIT-licensed source and release
tree, so this family does not pre-bake it into the SIF. The operator provisions
the model files read-only beneath
`/mnt/db/weights/revocompute/p2rank`, mounted at the identical container path.

Only the `default` prediction model and the two `default` pocket/residue score
transformers are provisioned. The conserve-d, AlphaFold, PRANK rescoring, and
rescore-2024 models are deliberately not provisioned because this Runner exposes
the `predict` capability only.

| Relative path | Bytes | SHA-256 | Source |
| --- | ---: | --- | --- |
| `default/model.zst` | 23,081,516 | `9c3fc8becd5e5db4a7d7a9026e19f68b0f85fd4723056d71be8fcc7cd2774962` | revision `9808a7723be9a94e2ffc21ab5f724cb6ae4ba01e`, `distro/models/default/model.zst` |
| `default/features.txt` | 583 | `51e8804dd075aff21b4cf4ea5c6075bdb29d17371bc14b3ea364ee4f6b299809` | same revision |
| `default_ZscoreTpTransformer.json` | 117 | `e180e8117a70fcac196a31f9d9f271fac5e489cd24bf1f1aa221c29ecec31109` | same revision, `distro/models/_score_transform/` |
| `default_ProbabilityScoreTransformer.json` | 22,191 | `78a2f1f761abac82ff7d2e86bf8ba18eeeaa282bcb96f078f16e91fd8d4a86b3` | same revision, `distro/models/_score_transform/` |
| `residue/default_ZscoreTpTransformer.json` | 118 | `452ad7169e03712f8857582b6c36ec8f5345e12632b434038baa3d794a13921e` | same revision, `distro/models/_score_transform/residue/` |
| `residue/default_ProbabilityScoreTransformer.json` | 24,454 | `309c0be50143d8a81a9e1c7f30050fb11c00b20e1e3ad4633362d6477ee80be0` | same revision, `distro/models/_score_transform/residue/` |

The digests above were computed locally from the pinned tag `2.5.1`
(release archive `p2rank_2.5.1.tar.gz`, SHA-256
`d243f2d9036ac053fefb9407b5fe1c85f4fe077c519fd975ac585e995feab274`) and match
the blobs committed in the pinned Git revision. The upstream project publishes
no digest manifest.

## Why the build still compiles the model

`distro/models` is part of the pinned source checkout, and Gradle resources for
`distro/` are not separable from the Java build. The definition therefore
builds the jar from the pinned revision and then deletes the entire bundled
`models` directory from the image, after checking the digest of the one file it
deletes. A missing external asset then fails the Task instead of silently
falling back to an embedded copy.

Provision with mode `755` directories and `444` files:

```sh
install -d -m 755 /mnt/db/weights/revocompute/p2rank/default \
                   /mnt/db/weights/revocompute/p2rank/_score_transform \
                   /mnt/db/weights/revocompute/p2rank/_score_transform/residue
install -m 444 <file> /mnt/db/weights/revocompute/p2rank/<relative path>
```
