# fpocket scientific reference

This record grounds the `fpocket` Runner in its upstream implementation and
method literature, and states exactly which of its published numbers are stable
enough to be a golden acceptance claim. It is the fpocket counterpart of
`gremlin_lh/SCIENTIFIC_ACCEPTANCE.md`.

## 1. What is modeled

The Runner runs the upstream **fpocket** pocket-detection program unchanged and
publishes a normalized view of its raw output. It reimplements no geometry.

- Upstream: <https://github.com/Discngine/fpocket>, git revision
  `4bb0d8447f62fee77e2c3c29f54b5fcaf5e2c066` (tag `4.2.3`), MIT licensed.
- Method publications fpocket's algorithm is grounded in:
  - Le Guilloux, Schmidtke & Tuffery, *BMC Bioinformatics* **10**, 168 (2009),
    `10.1186/1471-2105-10-168` — the Voronoi/alpha-sphere detection method.
  - Schmidtke & Barril, *J. Med. Chem.* **53**, 5858–5867 (2010),
    `10.1021/jm100574m` — the druggability score.
- CLI options the Runner passes, each verified against the upstream option
  macros in `src/fparams.h`:

  | Runner parameter | flag | default |
  | --- | --- | --- |
  | `min_alpha_sphere_radius` | `-m` | 3.4 |
  | `max_alpha_sphere_radius` | `-M` | 6.2 |
  | `min_alpha_spheres_per_pocket` | `-i` | 15 |
  | `clustering_distance` | `-D` | 2.4 |
  | `volume_monte_carlo_iterations` | `-v` | 300 |
  | write mode (fixed) | `-w p` | PDB |

- Input preprocessing: none. The Runner copies the resolved `structure` input
  byte-for-byte into the workspace (`run.sh`) and analyzes it unchanged; every
  chain in the file is analyzed together. The only transform is the transport
  copy, and the input's SHA-256 is recorded in `fpocket-run.json`.
- Output consumed by the Runner: `<stem>_out/<stem>_info.txt` (one descriptor
  block per pocket) and `<stem>_out/pockets/pocket<N>_{vert.pqr,atm.pdb}`.
  `normalize_results.py` republishes the descriptor values verbatim and derives
  the pocket centre and the contacted-residue set from those files.

Release-number note: the compiled-in banner is `fpocket 4.0` for fpocket and its
`mdpocket`/`tpocket` siblings regardless of the `4.2.3` tag, so the banner is a
fingerprint, not a version. The build identity is pinned by the fetched git
revision; `upstream.json` records it and the SIF `%test` only greps the banner.

## 2. Reference case

PDB **1SUO** — mammalian cytochrome P450 2B4 with bound
4-(4-chlorophenyl)imidazole, X-ray, 1.9 Å (`10.1074/jbc.M403349200`, released
2004-07-20). It is a real repository fixture (`tests/data/pdb/1SUO.pdb`,
SHA-256 `372ded91…9fe76`); no coordinates were invented for this work. It is a
single chain with a heme cofactor (HEM) and a co-crystallized inhibitor (CPZ),
and the run is fast on CPU.

The case is deliberately *not* trivial: fpocket detects **40** pockets and the
leading one contacts the heme cofactor — its contacted-atom file lists `HEM`
HETATM lines. This is recorded as a **hetero/cofactor contact, not a ligand or
active-site claim**: the input also carries the co-crystallized inhibitor `CPZ`,
and **no reported pocket contacts `CPZ`**, so calling pocket 1 a "ligand-binding
pocket" would be unsupported. The acceptance asserts the cofactor contact and
explicitly asserts the absence of a CPZ contact, so the wording cannot drift back
into the wider claim. A case whose output was all zeros would prove nothing, so
the acceptance also requires a non-zero pocket count.

The frozen raw output is checked in at `tests/data/fpocket/1SUO_out/` — the
complete `1SUO_info.txt` (40 pockets) and every `pocket<N>_{vert.pqr,atm.pdb}` —
together with the file hashes and a tree digest in the reference. It is a full
`scientific`-tier run of the 1SUO structure, not a subset: an earlier partial
snapshot that carried only the first two pockets was replaced so the frozen tree
is exactly what the Runner would publish for the reference case.

## 3. Observables and their classification

Each published observable is classified before any tolerance is chosen:

| Observable | Class | Basis |
| --- | --- | --- |
| pocket count | exact | upstream prints one block per reported pocket |
| pocket identity (`pocket<N>`) | exact | fpocket numbers reported pockets contiguously after sorting |
| ranking (descending score) | ordering | fpocket sorts by score; ties are broken upstream |
| score, druggability, SASA, radius, ... | exact | the Runner republishes upstream's own printed value, four decimals, no recomputation |
| pocket volume | not-golden | upstream Monte-Carlo estimate, RNG seeded from the wall clock |
| alpha-sphere / vertex count | exact | `<stem>_info.txt` and `pocket<N>_vert.pqr` agree by construction |
| contacted-residue set | exact | re-derived from `pocket<N>_atm.pdb` PDB columns |
| contacted-atom count | exact | count of ATOM/HETATM lines |
| hetero residue contact | exact | HETATM residue names in the contacted-atom file (a factual contact statement, not a ligand/active-site claim) |
| pocket centre | numerical-with-tolerance | mean of the pocket's alpha-sphere centres |

**Centre tolerance.** fpocket's own `set_pockets_bary` (`src/pocket.c`) computes
the pocket centre as the mean of the pocket's alpha-sphere centres, and that is
exactly what `normalize_results.py` re-derives from `pocket<N>_vert.pqr`. Both
sides average the same coordinates; the only difference is the normalizer's
four-decimal rounding, whose half-unit-in-last-place is 5e-5 Å. The acceptance
bound is **2e-4 Å** — a margin over rounding, not a range that would hide a wrong
centre.

**Why the centre is not exact.** It is a derived quantity, so it is separated from
the descriptors that are published verbatim; the tolerance follows from float
reduction order and printing precision, and was not chosen to make a test pass.

**Repeatability (measured, not assumed).** On the pinned image the leading
pocket's `score`, `druggability_score`, alpha-sphere count, mean radius, volume
score, and SASA were byte-identical across repeated runs, and the pocket count was
40 in eight consecutive runs; the derived centre was identical too. The
`volume_angstrom3` field alone varied (251–270 Å³ over three runs, ~8%), because
fpocket seeds its RNG from `time(NULL)` (`src/utils.c`). That is why the volume is
classified `not-golden` and excluded from the cross-run comparison while the
reference still records it for the frozen run.

## 4. Independent reference

`tests/data/fpocket/build_reference.py` derives every observable above from the
raw fpocket tree with its own parsing logic. It imports nothing from
`normalize_results.py`, and it never executes fpocket or any file content, so a
bug in the production parser cannot make the reference agree with it. The receipt
`tests/data/fpocket/upstream_reference.json` records the upstream revision, the
input hash, every raw-file hash and a tree digest, the extraction script and
version, and the expected observables.

Identity fails closed: the acceptance module recomputes the input hash, every raw
file hash, and the tree digest, and re-derives the reference from the pinned tree,
refusing if anything differs.

## 5. Runner semantics audit

The Runner's chain is `task.yaml` → `run.sh` → `detect.py` (fpocket) →
`normalize_results.py` → `pockets.csv` / `summary.json` → the declared
`entity-table` / `scalar-summary` / `evidence-bundle` views. It has no
`expected_files.yaml`; that contract is optional and its only effect is that the
raw fpocket files are published as generic view-member artifacts rather than
named logical files, which is correct for this family.

Defects found and fixed, each supported by upstream evidence:

- The task considered-string claimed "0.5 is the upstream decision threshold" for
  the druggability score. Upstream defines no such published threshold (`README`
  states only that the calibration was reoptimized), so the claim was removed from
  `task.yaml` and the `summary.json` semantics string.
- The SIF `%test` comment implies the banner is the version; clarified as above.

Intentional decisions kept: ranking is by descending fpocket score (fpocket's own
sort), pocket identity is the contiguous `pocket<N>` label printed alongside the
rank, and the centre is the alpha-sphere barycenter, matching fpocket.

## 6. How to re-verify

```bash
# Fast protocol + scientific equivalence (no fpocket binary needed).
uv run pytest tests/runners/fpocket -q

# Regenerate the frozen reference from the pinned raw tree (maintainer only).
uv run python tests/data/fpocket/build_reference.py \
    --run-dir tests/data/fpocket/1SUO_out \
    --input tests/data/pdb/1SUO.pdb \
    --output tests/data/fpocket/upstream_reference.json
```

A real SIF build (`apptainer build fpocket/fpocket.def`) and a target-host live
acceptance through the public API reproduce the run and are recorded in §7.

## 7. Live acceptance

The reference case was exercised once through the real execution path on the
production target `lab309-westlake` — public API submission → Server → Slurm →
Apptainer → fpocket → published artifacts → ResultManifest — not a local harness.

The acceptance is tied to the fpocket Runner payload, not to a moving head SHA:

- **Live execution head** — the deployed revision the runner actually executed
  under: `e9f9b6d6fe01224b604ec702c52f765002175878`. This SHA is fixed and
  meaningful.
- **Payload identity** — the fpocket Runner payload (`normalize_results.py`,
  `detect.py`, `run.sh`, `tasks/fpocket/task.yaml`, `test.yaml`, `upstream.json`,
  `fpocket.def`) is byte-identical across the live execution head and every PR
  head that differs from it only in acceptance documentation, the frozen
  reference, or browser tests, so the runner that executed is this PR's runner.
  Example heads at which that identity holds: `cdd10f32f9b9bc3317b0e16720854a2cf7b92f93`
  and `a77ec9589637264dd90104b770df791f8f2b8bc4`.
- `4c2c602230b3b7955bcea14ffb7c0460249dd7f8` was an intermediate head and is
  not a supported reference point.

| Field | Value |
| --- | --- |
| Live execution head | `e9f9b6d6fe01224b604ec702c52f765002175878` (`/opt/revocompute`), main `403f042` + the fpocket PR ref |
| Runner identity | the fpocket Runner payload is byte-identical across the live execution head and every PR head differing only in acceptance docs / frozen reference / browser tests; the executed runner is therefore this PR's runner (example heads: `cdd10f3`, `a77ec95`) |
| Active SIF | `/mnt/hdd/revocompute/images/fpocket_v1.sif`, sha256 `5410865f29870609c6e2225ff720876c47f4b367c5f81b374d9d7d6e8824849a` (rebuilt on the host from the same build inputs; the earlier locally built `497ac623…` was superseded and was not promoted) |
| Readiness | fpocket `READY`; smoke live-test receipt `PASS` |
| Submission | `POST /compute/api/post`, user `tester`, role `structure` = `1SUO.pdb`, detector defaults |
| Task id | `b546f034ffc7fafac871f21176a03c91` |
| Slurm job | `12912`, exit `0`, elapsed `3.29 s`, 1 CPU, `max_rss` `39908 KiB` |
| Lifecycle | `pending` → `finished`; manifest walltime `3.52 s` |
| ResultManifest | `schema_version` **3**, `output_check` **passed** (6/6 checks, no problems) |
| Input | `1SUO.pdb`, sha256 `372ded91157b7f3e80efe21f5dce9377452208b36c440c833205d2a5d4a9fe76` |
| Parameters | `min_alpha_sphere_radius=3.4, max_alpha_sphere_radius=6.2, min_alpha_spheres_per_pocket=15, clustering_distance=2.4, volume_monte_carlo_iterations=300` |
| Views | `entity-table`/primary "Ranked pockets", `scalar-summary`/evidence "Detection summary", `evidence-bundle`/evidence "Raw fpocket output" |
| Artifacts | 97 published; `pockets.csv` sha256 `bb783a012e88243c99a4a788ee0d06742f879397eed69f91c4ffb670efebd0ac` (role `primary`, table), `summary.json` sha256 `ef0465c6e88f8ab9f7ee75ed3f9a3b5af88bdf37614e887770e1ff3846981c31`, `work/1SUO_out/1SUO_info.txt` sha256 `bd7be8e7d1e83abc3a0340cae20c651f0d0c4aa01d28204464b096ba2acec8ef` |

**Scientific acceptance (live artifacts vs the frozen reference).** The published
`pockets.csv` reproduces `tests/data/fpocket/upstream_reference.json` with **0
deterministic mismatches** across all 40 pockets: pocket count and ids, ranking,
every non-Monte-Carlo descriptor, the alpha-sphere vertex counts, the contacted
residue sets, and the pocket centres (within the 2e-4 Å rounding bound). The
leading pocket is `pocket1`, score `0.629`, druggability `0.747`, and its
contacted-atom file lists the heme cofactor `HEM` — matching the reference's
hetero/cofactor-contact expectation. The only per-run difference is
`volume_angstrom3` (`259.927` live vs `265.894` frozen on pocket1), the
wall-clock-seeded Monte-Carlo estimate classified `not-golden`; the live value is
positive and the descriptor is otherwise exact.

**Browser acceptance.** `tests/test_playwright_fpocket_live_result_acceptance.py`
serves this exact manifest and its artifacts to the built Result workspace and
verifies the primary `entity-table` renders all 40 published pockets with pocket
identity and rank kept distinct, the bounded table endpoint serves the real
`pockets.csv`, and the evidence tabs are present under their declared titles —
with no console or CSP errors and no runner-name special case.
