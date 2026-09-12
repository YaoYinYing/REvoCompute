# PPIformer model assets

Provision `weights.zip` from the official PPIformer Zenodo record into the operator-managed directory
`/mnt/db/weights/revocompute/ppiformer/weights`. The directory is mounted read-only at runtime; checkpoints are not
baked into the SIF and the runner never downloads assets.

- Record: https://zenodo.org/records/12789167
- Record DOI: `10.5281/zenodo.12789167`
- File: `weights.zip`
- Size: `534,824,849` bytes
- Zenodo checksum: `md5:127844ea04063b1bc48a01c0eb92c42e`
- Archive SHA-256: `e17a1363e0363467d48337d8992c8412282d54544b0c52468f97e5ce7ac43717`
- License recorded by Zenodo: Creative Commons Attribution 4.0 International (`CC BY 4.0`)

The extracted inventory and SHA-256 checksums are in `model-assets.sha256`. The unrelated dataset-cache archive from
the record is intentionally omitted because submitted structures are processed locally into task-scoped scratch.
