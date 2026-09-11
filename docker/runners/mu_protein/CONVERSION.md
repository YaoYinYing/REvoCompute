# Mu-Protein checkpoint conversion gate

No Mu-Protein TaskType is registered yet. The pinned upstream revision intentionally
disabled checkpoint loading after a security incident, and the remaining code fails
on undefined checkpoint variables. Runtime promotion still requires sanitized tensor
state and reproduction of an upstream example score.

The exact 104-sequence normalization dataset is present in the pinned official GitHub
revision despite a second, stale developer-local path later in the same source file.
`scientific-evidence.json` records its repository path, Git blob identity, SHA-256,
shape, and the two upstream reproduction candidates. The upstream TEM-1 WT annotation
is a two-value range rather than a checkpoint-specific golden score, while the explicit
example in `examples/baseline.py` has no published output.

`fetch_asset.py` accepts only an asset ID from `asset-registry.json`. It downloads from
the immutable official Figshare file URL, verifies the published byte size and MD5,
computes a local SHA-256, and atomically installs the raw checkpoint. It never accepts
a checkpoint path or URL.

Build `mu_protein_converter_v1.sif` from `conversion.def`, then run:

```text
./fetch_asset.py muformer_encoder
./fetch_asset.py musearch_tem1_muformer
./prepare_assets.sh muformer_encoder
./prepare_assets.sh musearch_tem1_muformer
```

`prepare_assets.sh` launches the converter unprivileged with a read-only raw mount,
a writable sanitized mount, a clean environment, no home directory, and an isolated
network namespace. The converter uses `torch.load(weights_only=True, mmap=True)` with
a role-specific allowlist, validates a string-to-tensor state dictionary, and writes
safetensors plus checksummed JSON metadata. The encoder permits only
`argparse.Namespace`; the target additionally permits the exact inert NumPy scalar
metadata globals found by static pickle inspection. It never falls back to unsafe
pickle loading. Shared tensor storage is detected and only repeated storage references
are cloned before safetensors serialization. The converter environment is installed
from the complete Python 3.11 `requirements.lock` with `uv pip sync --require-hashes`.

Default directories are `/mnt/db/weights/revocompute/mu_protein` and
`/mnt/db/weights/revocompute/mu_protein/sanitized`. Operators may override the roots
with `MU_PROTEIN_RAW_ROOT` and `MU_PROTEIN_SANITIZED_ROOT`; individual checkpoint paths
remain non-configurable.
