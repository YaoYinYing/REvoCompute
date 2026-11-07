# Foundry model assets

Foundry source and the model weights referenced for download are BSD-3-Clause at
commit `d078b24d6d0e6f8607e9a0311128f4a897f83953`. The installed source is git
checkout at that commit. The existing image label `rc-foundry==1.0.0` is not a
published PyPI distribution identity; it must not be read as one. Correcting that
baked label requires a separately authorized image rebuild, which this PR does
not perform.

The upstream `production` HEAD is
`0d0b0ba44fab7ca76aa4b625c014ce5964c7d284`; compared with the installed pin, it
deletes one documentation file and changes no executable code. The installed
pin is deliberately retained. This observation is documentation-only and does
not change the existing image build identity.

The official checkpoint registry
URLs and the SHA-256/size identities observed from the three operator-provisioned
downloads on 2026-10-19 are recorded in `checkpoint-registry.json`.

Upstream does not publish checkpoint SHA-256 digests. Operators must review the
BSD-3-Clause terms, download directly from the recorded `files.ipd.uw.edu` URLs through
the configured proxy, verify the repository-recorded identity, and create
`/mnt/db/weights/revocompute/foundry/model-assets.json`. Runtime never downloads files.

The operator manifest independently records the mounted identity and has this shape,
with the registry's real sizes and lowercase SHA-256 digests:

```json
{"schema_version":1,"assets":[{"id":"rfd3","filename":"rfd3_latest.ckpt","size":1,"sha256":"<64 hex>"}]}
```

Include all three registry IDs. The mounted directory is read-only and every requested
checkpoint is hashed before inference.
