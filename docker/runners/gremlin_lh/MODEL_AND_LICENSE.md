# GREMLIN_LH provenance, runtime, and license

## Placement

GREMLIN_LH is a dedicated family. The existing `pssm_gremlin` family starts
from one query sequence, searches deployment-managed HHblits and PSI-BLAST
databases, and runs a legacy TensorFlow environment. GREMLIN_LH consumes an
already aligned MSA and fits L2, low-rank/spectral LH, or group-sparse LB Potts
models in a CPU JAX environment. It needs neither model weights nor sequence
databases, so merging the families would couple unrelated runtimes and
execution semantics.

## Pinned source and transcription

- Repository: <https://github.com/sokrypton/GREMLIN_LH>
- Commit: `6b8a6beb426fd31bb10c3fdd398abd3355b782f9`
- Notebook blob: `79cc0fdaba25ff1a6d6cb12ab2a2ebc8358c2c17`
- Notebook file SHA-256: `7f4638aeb835689717a7b497d182cee3bac24128add71a3a7c1c542ddc50c3dc`
- Transcribed source: `GREMLIN_LH_outline_7.ipynb`
- Upstream repository has no tags or release artifacts at intake.

The notebook blob is the hash that pins the transcribed source and is
re-derivable from the file alone (`git hash-object`). The commit was recorded at
intake as the repository revision the blob came from; unlike the blob it cannot
be recomputed offline from the file, which is why the receipt
(`tests/data/gremlin_lh/upstream_reference.json`) records both.

`fit_model.py` transcribes the reusable JAX inference path into a deterministic,
headless command. It retains sequence reweighting, inverse-covariance or zero
initialization, one-body fields, the notebook's scalar-second-moment Adam
optimizer, L2/LH/LB penalties, Frobenius coupling scores, APC correction, and
Hamiltonian/pseudo-likelihood scoring. Paper-specific cells that download
benchmarks, invoke bmDCA, or construct figures are not runtime entrypoints.

Two evident notebook inconsistencies are resolved according to their stated
scientific intent: the gap state is explicitly the first alphabet state rather
than incorrectly indexing the final amino acid plane, and field L2 regularization
uses ordinary division rather than integer floor division. Both corrections are
classified, measured, and disclosed — including their numerical impact and the
uncorrected upstream values — in
[`SCIENTIFIC_TRACEABILITY.md`](SCIENTIFIC_TRACEABILITY.md) §3, and the task
summary captures every effective parameter.

## Assets and network behavior

The TaskType accepts a user-supplied FASTA/A3M alignment. It has no pretrained
weights, no managed database, and no runtime mounts. Normal execution performs
no downloads. The upstream experimental DMS CSV and all paper benchmark archives
are not required to fit a user MSA and are therefore not copied into the SIF.

## Upstream license notice

The only license notice is embedded in the notebook; no repository-level license
file exists at the pinned revision. The notice is reproduced here as required:

> "THE BEERWARE LICENSE" (Revision 42): Haobo Wang and Sergey Ovchinnikov wrote
> this code. As long as you retain this notice, you can do whatever you want with
> this stuff. If we meet someday, and you think this stuff is worth it, you can
> buy us a beer/an apple cider in return.

The scientific data file has no separately stated license. It is neither needed
nor redistributed by this Runner.

## Scientific references

- Wang H, et al. *Disentanglement of Evolutionary Constraints in Statistical Models of Proteins*. PRX Life 2,
  023005 (2024). <https://doi.org/10.1103/PRXLife.2.023005>
- Kamisetty H, Ovchinnikov S, Baker D. *Assessing the utility of coevolution-based
  residue-residue contact predictions in a sequence- and structure-rich era*.
  PNAS 110, 15674-15679 (2013). <https://doi.org/10.1073/pnas.1314045110>
- Correction for Kamisetty et al., PNAS 110, 18734 (2013).
  <https://doi.org/10.1073/pnas.1319550110>. Replaces Fig. 1C/E and its legend;
  the model definition, pseudolikelihood objective, and APC equation used here
  are unaffected.

## Resource envelope

The coupling tensor has shape `L x 21 x L x 21`, so compute and memory increase
at least quadratically with alignment width. Production validation caps input
width at 512, caps optimization at 5,000 updates, runs CPU-only, and defaults to
four BLAS/OpenMP threads. Real Task -> SLURM -> Apptainer measurements and a
candidate SIF receipt remain required before enablement.

The full Python closure is pinned in `requirements.lock`. A direct build on
2026-09-10 with Apptainer 1.4.5 completed its `%test`; the resulting local
candidate was 248 MiB with SHA-256
`985b4271eb6ab32e2c392ea7637579e62c2352977d5d5373ccf1f77ee9389dc9`.
The same SIF completed the manifest-driven smoke case and emitted every declared
artifact. This local checksum is build evidence, not a deployment receipt.
