# EvoSplit model and license record

The runtime pins the official EvoSplit repository at commit
`6eedfcd5a0551bd1fecf9c51818be19f9e730e19` (2026-04-20). The repository
contains no release tags or package metadata and is licensed under Apache-2.0.
The implemented workflow is the repository's primary `run_evosplit.py`
clustering method, including its optional two-reference supervised mode.

The family uses the existing authoritative `/mnt/db/weights/esm` resource root,
mounted read-only. `model-assets.json` records the exact official Meta ESM-MSA-1b
model and contact-regression URLs, sizes, and SHA-256 fingerprints. The files
are loaded by path, so normal execution cannot invoke the upstream Torch Hub
download path. No separate model-weight terms were published beside these
files; the upstream ESM code and distribution repository are MIT licensed.
Torch's legacy-checkpoint compatibility override is enabled only in the Runner
process, after both official files pass exact size and SHA-256 verification.

The runtime intentionally omits training-only dependencies from the broad
upstream Conda environment. Core clustering needs PyTorch, NumPy, SciPy,
scikit-learn, Biopython, and Matplotlib. DeepSpeed, Lightning, WandB, PyMOL,
HMMER, HH-suite, and AlphaFold are not used by this inference path.

The separately documented MSA-extension script is not exposed: it launches
shell commands containing user-derived paths, hardcodes `~/tools/reformat.pl`,
assumes an MSA deeper than 1,024 rows, and provides no reliable subprocess
failure propagation. The generic `runESM.py`, AlphaFold, and predicted-structure
clustering utilities overlap existing REvoCompute families and are not part of
the EvoSplit clustering contract.

Primary citation: Li et al., "Disentangling coevolutionary constraints for
modeling protein conformational heterogeneity," Communications Chemistry 9,
146 (2026), DOI `10.1038/s42004-026-01940-9`.
