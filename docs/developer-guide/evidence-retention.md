# Evidence Retention and External Archives

> PR #86 policy for production-derived scientific evidence, fixtures and
> cleanup. Keep CI hermetic and preserve scientific traceability.

## Disposition classes

| Kind | Default home | Rationale |
| --- | --- | --- |
| Small reproducible test input / contract edge cases | Git | Required CI can run without network dependencies |
| Bounded, authentic replay payload required by CI | Git | Preserves actual browser and ResultManifest regression evidence |
| Large captured payload **required** for CI publishing/finalization | Keep until a proven CI-compatible replacement exists | Size alone cannot justify a broken output check |
| **Large, repeatedly reused payload not required by CI** | Optional external evidence store, e.g. immutable GitHub Release asset | Reduces repository size without risking mandatory tests |
| Weights, restricted databases, personal data, raw secrets, disposable cache | Not in public Git or Releases | Privacy, licensing and security |

A Release is public and **not** a private evidence vault. Before uploading
any artifact, confirm source rights, permitted redistribution, scientific
inputs' privacy, asset reproducibility and data retention expectations.
This repository had no published Releases when PR #86 was planned; do not
refer to a fabricated release URL or asset.

## PR #104 evidence ledger (Gate 3)

Base `d6e681c`, PR #104 merge `b569c45`. The PR #104 merge added **181 tracked
`tests/data/` files / 9,496,590 bytes** (155 distinct blobs / 9,065,329 bytes;
the difference is byte-identical input snapshots repeated per Task).

**Method.** Paths come from `git diff --diff-filter=A d6e681c b569c45`. Each
group's digest is SHA-256 over its files' real content, assembled as sorted
`<relative_path>\0<sha256>\n` lines; a reviewer reproduces it with
`git ls-tree -r <rev>` + `git cat-file blob` over the same paths (group digests
are abbreviations of those 64-hex values). "Implicit" means the file is reached
only by a Runner `expected_files.yaml` glob resolved during
`task_runtime._finalize_results_manifest`, not by a literal path.
Lane names are the jobs in `.github/workflows/tests.yml`: `REvoComputeTests`
(server), `RunnerFastContracts` (runner_fast), `BrowserContracts` (browser).
Every added data path classifies to `server`; the consuming fleet and browser
tests add `runner_fast`/`browser`
(`python3 tools/classify_ci_scope.py --event pull_request --paths <path>`).

| Path | Files / bytes | SHA-256 (group) | Reached | Consumers | Lanes | Class |
| --- | ---: | --- | --- | --- | --- | --- |
| `tests/data/storyboards/esmdynamic/` | 21 / 5,649,619 | `de02e2a8…f3b906b5` | direct tree copy | `tests/fleet/browser/test_playwright_numeric_storyboards.py::test_storyboard_is_the_scientific_surface_over_published_bytes[esmdynamic]` | server, browser | KEEP |
| ↳ `…/dynamic/2KL8_dynamic_prob_320K.html` | 1 / 4,702,331 | `407eb984…bb08633b` (file bytes: `837e6012…375a9d6622c`) | implicit `*/*/*.html` (`plot_html`) | same test's finalize assertion | server, browser | KEEP |
| `tests/data/storyboards/` (other 13 Tasks) | 122 / 1,008,249 | `ceeaea07…0f88972b` | direct tree copy | same test, 13 parametrizations | server, browser | KEEP |
| `tests/data/{alphafold,alphafold3,colabfold_af2,esmfold2,chai1,opendde}_replay/` | 12 / 1,093,447 | `e91dfd0f…c5a43bcb9` | direct loader | `test_playwright_replay_structure_tasks.py` (all tests), `test_fleet_scientific_contract_inventory.py::test_evidence_corpus_real_items_are_verified_and_mocks_never_claim_science` | server, runner_fast, browser | KEEP |
| `tests/data/{mpnn,fampnn,freebindcraft,placer-rfdiffusion}_replay/` | 11 / 1,488,729 | `e1216fc2…e6dac8a7e5` | direct loader | `test_playwright_owner_d_designs_replay.py` | server, browser | KEEP |
| `tests/data/{bioemu,bioemu2}_replay/` | 4 / 242,728 | `23f70869…5c682f1b499` | direct loader | `test_playwright_bioemu_trajectory.py`, `test_playwright_bioemu2_storyboard.py`, `test_replay_bundle.py::test_real_bioemu2_bundle_round_trips_with_its_published_verdicts` | server, browser | KEEP |
| `tests/data/boltz_replay/README.md` | 1 / 1,215 | `8e9d0613…ec6dee89` | README only, no bundle | `test_fleet_scientific_contract_inventory.py::test_evidence_corpus_real_items_are_verified_and_mocks_never_claim_science` | server, runner_fast | KEEP |
| `tests/data/autodock_vina/live/` | 10 / 12,603 | `b910903e…6c96ef7ba` | direct read | `test_playwright_autodock_vina_storyboard.py`, `test_playwright_autodock_vina_result_acceptance.py` | server, browser | KEEP |
| **Total added by #104** | **181 / 9,496,590** | `95779035…203fe94d` | | | | |

`tests/data/{gremlin_lh,fpocket}_replay/` and the PDB/ligand/synthetic inputs
predate #104 and are unchanged by this PR; they are outside the ledger's
subtraction scope. The `boltz_replay/README.md` is a deliberate
`BLOCKED_EVIDENCE` note with no bundle (a host path in already-published bytes),
so nothing is externalized or substituted here.

Every row is CI-coupled: each browser test above runs in `BrowserContracts`
against the built frontend, and the corpus test runs `make test-fleet` in
`RunnerFastContracts`. No added #104 path is CI-independent, so no candidate
qualifies for an external archive. **Totals: KEEP 181 files / 9,496,590 bytes;
EXTERNALIZED 0; REMOVED 0; BLOCKED 0.** Deletions are zero, as at kickoff.
The corpus test asserts only that disk and the inventory agree on what exists,
so a deleted bundle would still leave it green: read a bundle's consumers from
this ledger rather than inferring "unused" from a passing lane. The storyboard
trees are not silently skippable — losing one fails the test's own finalize
assertion.

The `.gitattributes` entries keep `tests/data/storyboards/**` byte-exact
(`-text`), so a checkout cannot rewrite captured bytes into a different digest.

## Required externalization/deletion sequence

1. Inventory each candidate's bytes, exact path, SHA-256, size, test consumers,
   implicit wildcard matches, Runner output-check requirements, licensing,
   sensitivity, storage cost and provenance.
2. Classify CI dependence, repeated reuse and reproducibility. Exclude
   secrets and non-redistributable scientific inputs from public stores.
3. For approved CI-independent candidates, construct an immutable versioned
   archive + machine-readable manifest (`relative_path`, `sha256`,
   `size_bytes`, source reference, license). Upload a pinned Release asset
   only after maintainer authorization; or use an authorized private store.
4. Verify retrieval, hashes, extraction and scientific consumption *before*
   deleting tracked data. Provide useful failure messages if external data
   cannot be obtained. Never make mandatory offline CI silently dependent on
   network or a moving `latest` tag.
5. Remove only proved-redundant bytes and update consumers/docs. Run focused
   output-finalizer, replay and browser tests plus all required final-head CI.
6. Record a cleanup ledger with `KEEP | EXTERNALIZED | REMOVED | BLOCKED`
   and links to objective evidence. **Zero removals is valid** if no safe
   candidate is found. Never shrink inputs by corrupting scientific content or
   changing capture-mode claims.

The [Single-PR Campaign Acceptance Auditor](../agents/single-pr-campaign.md)
must recheck the **exact final file diff**, external artifact links, digests
and test dependencies before accepting any subtraction claim.
