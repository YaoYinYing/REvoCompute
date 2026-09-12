# Foundry model assets

Foundry code is BSD-3-Clause at commit `b02eed6a6bdf8f44d14a80cc36e3da13c9f2291c`.
The official checkpoint registry and URLs are recorded in `checkpoint-registry.json`.

Upstream does not publish checkpoint SHA-256 digests or explicit checkpoint license
terms. Operators must review the checkpoint terms, download directly from the recorded
`files.ipd.uw.edu` URLs through the configured proxy, and create
`/mnt/db/weights/revocompute/foundry/model-assets.json`. Runtime never downloads files.

This is operator-pinned identity, not a repository-known upstream hash. The
operator manifest has this shape, with real sizes and lowercase SHA-256 digests:

```json
{"schema_version":1,"assets":[{"id":"rfd3","filename":"rfd3_latest.ckpt","size":1,"sha256":"<64 hex>"}]}
```

Include all three registry IDs. The mounted directory is read-only and every requested
checkpoint is hashed before inference.
