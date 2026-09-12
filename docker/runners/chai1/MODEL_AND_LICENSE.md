# Chai-1 model and license record

This runner pins the official `chaidiscovery/chai-lab` release `v0.6.1` at commit
`8d5ac0f93e9b6ea4c3a6545c253a6381c0f3694b`. The upstream source repository and the
Chai model weights are described by the upstream README as Apache-2.0. The underlying
ESM-2 project is MIT licensed.

The upstream distribution does not provide SHA-256 checksums for its eight inference
assets. `model-assets.json` records the official URLs, byte sizes, and HTTP ETags observed
during intake without downloading the payloads. Provisioning must download directly from
`chaiassets.com` through the configured proxy, calculate SHA-256 for every completed file,
and replace each `null` digest before enabling the runner. The runtime verifier fails closed
while any digest is absent or mismatched.

The `conformers_v1.apkl` data file is required even for protein-only inference. No separate
asset-level license or NOTICE for that conformer data was found in the pinned source release;
operations and legal review should resolve that provenance before production enablement.

Assets are external to the SIF and mounted read-only at
`/mnt/db/weights/revocompute/chai1`. Their relative paths must match `model-assets.json`
exactly because Chai discovers them through `CHAI_DOWNLOADS_DIR`.

This offline contract accepts single-sequence inference or uploaded aligned Parquet MSAs.
It never calls the MSA service. Template support is excluded because Chai v0.6.1 downloads
template coordinates from RCSB during preprocessing; enabling it would violate the runner's
network-free execution contract.
