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

## Concrete PR #104 cleanup inventory

Compared with parent `d6e681c`, the PR #104 merge added approximately
**9.5 MB** in new tracked test/evidence paths. The largest group is
`tests/data/storyboards/` (143 files / 6,657,868 bytes). The single
ESMDynamic `2KL8_dynamic_prob_320K.html` is **4,702,331 bytes**.

This HTML is **not a safe automatic deletion** despite being download-only
in the product: `tests/fleet/browser/test_playwright_numeric_storyboards.py`
copies real per-Task output trees into the server's finalization path, and the
ESMDynamic file tree declares HTML results. A deletion may invalidate output
checking and provenance. The replay bundles under
`tests/data/*_replay/` are also used by required fleet/browser tests;
their saved `reproduced_real_result`, `synthetic` and unverified modes must
not be conflated.

**Kickoff decision:** keep these CI-coupled files in Git until tests and
a replacement strategy demonstrate a safe change. Do not move them to Releases
just to decrease Git's size. For genuinely large, reusable *CI-independent*
scientific files, releases or an authorized external evidence archive are
reasonable future candidates.

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
