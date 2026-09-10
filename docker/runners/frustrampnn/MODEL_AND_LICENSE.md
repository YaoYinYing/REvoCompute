# frustraMPNN model and license record

## Source

- Upstream project: `https://github.com/YaoYinYing/frustraMPNN`
- Pinned commit: `3a03cdc300bfe24c4bb70e60207118532bc73b3b`
- Code license: BSD-3-Clause

## External model resources

The two checkpoints are tracked in the pinned repository under `weights/` and
are provisioned without renaming:

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| `fireprot_train_weights.ckpt` | 57,088,707 | `2c9c9c59cb684af1cd631fb745adc6106a2f69c2ab19060ee45a6aa75dde2f20` |
| `megascale_train_weights.ckpt` | 57,088,899 | `eaee71adb7eec366fc672d2aadef87f2c51243042a4518cd897634784dc2da3b` |

They are mounted read-only from
`/mnt/db/weights/revocompute/frustrampnn/`. The SIF excludes the upstream
`weights/` directory, and normal Task execution performs no network download.
