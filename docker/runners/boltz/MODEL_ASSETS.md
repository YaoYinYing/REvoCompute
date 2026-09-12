# Boltz-1 model assets

The Boltz Runner is pinned to upstream release `0.3.2`, commit
`2355c62c957e95305527290112e9742d0565c458`, under the MIT license. This is
the first upstream release line that uses the confidence-enabled Boltz-1
checkpoint provisioned on this server.

The host resource root `/mnt/db/boltz` is mounted read-only at the identical
container path. Production inference requires these immutable files:

| File | Size (bytes) | SHA-256 | Role |
| --- | ---: | --- | --- |
| `boltz1_conf.ckpt` | 3595352714 | `fea245d912c570ec117b2277c2719f312a6fc109c07b6f6ef741690ee775c2f5` | Boltz-1 structure and confidence checkpoint |
| `ccd.pkl` | 345859128 | `2d3b2f03a3c5665944adba51e33263511e51b21c9cd05d902f9c4b7c1e58d2f4` | Chemical Component Dictionary used by the input parser |

`boltz1.ckpt` is also present in the shared cache. Its SHA-256 is
`82f6ee66aca03664351465848c3daf2a2d4d9333e02d7242575187d9d4616d5e`
and its size is 6921224318 bytes. It belongs to the pre-confidence Boltz-1
release line and is intentionally not consumed or required by this Runner.

The wrapper verifies the required files against `model-assets.sha256` before
starting the upstream CLI and publishes that manifest with every result. It
never enables the upstream MSA service. Protein inputs must provide an A3M or
CSV alignment as a task input, or explicitly use `msa: empty`. Writable
Lightning logs and preprocessing intermediates remain inside the task result
directory; the mounted resource root is never used as a cache.
