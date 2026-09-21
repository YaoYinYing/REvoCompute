# FRODOCK assets

FRODOCK ships one immutable data file that this Runner consumes as a mounted
asset: the knowledge-based SOAP pairwise potential, `bin/soap.bin`, located by
the docking executable and required for every run (the binary loads it even when
both SOAP weights are reduced, and aborts with "SOAP-potential file not found"
otherwise).

| Relative path | Bytes | SHA-256 | Source |
| --- | ---: | --- | --- |
| `soap.bin` | 7,536,604 | `791f31ec8ef1ef1466092b425638e926755519c9626f5678ca675ef6c76234fc` | `frodock3_linux64.tgz`, SHA-256 `91b9aeff747346046c7f8c4c92fa5749c9f082d8122ee9d2d4769855d35368f4` |

There are no trained weights and no other assets. The potential is part of the
BSD-3-Clause FRODOCK 3.12 release, not a separately licensed model, so the same
licence covers it.

Provision it read-only at `/mnt/db/weights/revocompute/frodock/soap.bin` with
mode `755` directories and `444` files:

```sh
install -d -m 755 /mnt/db/weights/revocompute/frodock
install -m 444 soap.bin /mnt/db/weights/revocompute/frodock/soap.bin
```

The digest above was computed locally with `sha256sum` from the tarball
downloaded directly from the authoritative chaconlab.org release page; the
upstream project publishes no digest manifest.

## Provisioning state

Provisioned read-only on this host, verified with `sha256sum -c` against
`model-assets.sha256`:

- `/mnt/db/weights/revocompute/frodock/soap.bin` — present, digest matches

The digest above was verified against a copy of the same file extracted from
`frodock3_linux64.tgz`. A missing or altered asset still fails closed with
"FRODOCK asset is missing: soap.bin"; only the host-side provisioning is now
complete.
