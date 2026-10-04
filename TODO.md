# TODO.md — GREMLIN_LH Scientific Reference Runner

## Objective

PR32–PR34 completed Presentation Plane ownership.
PR35 completed the visual/product refinement.

The frontend/backend architecture phase is closed.

Start from fresh current `main`:

    87aeb191fb1a2dafcf4d8019afd6f5fdf59be941

The next objective is scientific, not architectural:

> Make GREMLIN_LH the first REvoCompute Runner whose scientific implementation,
> durable outputs, ResultManifest semantics, generic result rendering, Storyboard,
> and live user experience can all be traced back to primary literature and a
> pinned upstream executable reference.

This is a **literature-grounded scientific reconstruction and delivery audit**.

Do not assume the current GREMLIN_LH implementation is wrong.

Do not assume its README claims are correct either.

Verify them.

The desired chain is:

    primary literature
            ↓
    pinned upstream notebook
            ↓
    REvoCompute implementation
            ↓
    durable scientific artifacts
            ↓
    ResultManifest / ResultView semantics
            ↓
    Storyboard / generic scientific renderers
            ↓
    real browser acceptance

---

# 0. Bootstrap

Before changing code:

1. Fetch latest remote `main`.
2. Confirm starting SHA is the PR35 squash merge or its direct descendant.
3. Create a dedicated scientific-readiness branch.
4. Confirm clean worktree.
5. Read:
   - `CLAUDE.md`
   - `AGENTS.md`
   - Runner Family Contract documentation
   - ResultManifest / ResultView documentation
   - current GREMLIN_LH README
   - `MODEL_AND_LICENSE.md`
   - `fit_model.py`
   - `run.sh`
   - `expected_files.yaml`
   - `task.yaml`
   - current Storyboard
   - all `tests/runners/gremlin_lh/*`
   - the current frozen upstream reference receipt.
6. Do not begin implementation before the literature/notebook audit below is complete.

---

# 1. Mandatory Scientific Sources

Read the actual primary sources, not summaries.

## 1.1 GREMLIN_LH paper

Wang H. et al.

**Disentanglement of Evolutionary Constraints in Statistical Models of Proteins**

PRX Life 2, 023005 (2024)

DOI:

    10.1103/PRXLife.2.023005

Read:

- full article;
- Methods;
- all relevant equations;
- figures relevant to L2/LH/LB;
- Supplemental Material.

Pay particular attention to:

- MRF/Potts formulation;
- one-body and two-body terms;
- pseudo-likelihood loss;
- definition of Frobenius coupling matrix `M`;
- APC;
- dominant eigenmode interpretation;
- LH spectral regularization;
- L2 and Block-L1/LB comparisons;
- Hamiltonian interpretation;
- raw vs APC contact scores;
- entropy / conservation / phylogenetic disentanglement;
- limitations of interpreting pairwise couplings.

Do not infer scientific semantics from the README if the paper says something more precise.

---

## 1.2 Original GREMLIN paper

Kamisetty H., Ovchinnikov S., Baker D.

**Assessing the utility of coevolution-based residue–residue contact predictions in a sequence- and structure-rich era**

PNAS 110, 15674–15679 (2013)

DOI:

    10.1073/pnas.1314045110

Also read the published correction:

    10.1073/pnas.1319550110

Understand:

- what GREMLIN means scientifically;
- why pseudolikelihood is used;
- direct versus indirect correlations;
- how pairwise parameters are converted into residue-pair scores;
- APC's role in the original formulation;
- sequence-depth limitations;
- what the paper does and does not claim about contacts.

Use the corrected figure/legend where the correction applies.

---

## 1.3 Pinned executable upstream

Repository:

    sokrypton/GREMLIN_LH

Pinned commit:

    6b8a6beb426fd31bb10c3fdd398abd3355b782f9

Authoritative notebook:

    GREMLIN_LH_outline_7.ipynb

Pinned notebook blob currently recorded by REvoCompute:

    79cc0fdaba25ff1a6d6cb12ab2a2ebc8358c2c17

Do not use current upstream `main` as a substitute for the pinned version.

Read the notebook cell-by-cell, especially the executable inference path currently
described as cells 7–14.

Paper semantics and notebook behavior are different kinds of evidence:

    paper
    → scientific intent

    notebook
    → executable reference behavior

When they differ, document the difference explicitly.

---

# 2. Scientific Traceability Document

Create:

    docker/runners/gremlin_lh/SCIENTIFIC_TRACEABILITY.md

This should become the audit trail for this Runner.

For every scientifically meaningful operation, record:

| Scientific concept | Literature | Notebook implementation | REvoCompute implementation | Artifact | Result presentation | Acceptance test |
| --- | --- | --- | --- | --- | --- | --- |

At minimum trace:

- alignment parsing;
- alphabet/state ordering;
- gap semantics;
- sequence identity weighting;
- effective sequence count / Neff;
- one-hot representation;
- one-body fields;
- pairwise couplings;
- pseudo-likelihood objective;
- initialization;
- optimizer;
- L2 regularization;
- LH regularization;
- LB regularization;
- coupling gauge / centering / symmetry treatment;
- raw Frobenius score matrix;
- APC;
- dominant eigenmode interpretation;
- Hamiltonian;
- per-sequence pseudo-likelihood;
- profile frequencies;
- ranked residue pairs.

Use equation/section/figure identifiers rather than copying large pieces of the papers.

---

# 3. Audit Current Implementation Before Editing

Audit these functions against both the notebook and literature:

    parse_alignment()
    encode_alignment()
    sequence_weights()
    weighted_covariance()
    inverse_covariance_initialization()
    normalize_couplings()
    lh_penalty()
    regularization()
    notebook_adam()
    fit_model()
    coupling_scores()
    sequence_statistics()
    write_profile_artifacts()
    write_coupling_artifacts()
    write_sequence_scores()

Classify every difference as one of:

    EXACT_TRANSCRIPTION
    EXPLICIT_CORRECTION
    RUNTIME_ADAPTATION
    PRODUCTION_DEFAULT
    NUMERICAL_GUARD
    SCIENTIFIC_DEVIATION
    UNKNOWN

Do not change an implementation merely because another formulation looks cleaner.

---

# 4. Re-evaluate the Existing "Two Corrections"

The current Runner documents two corrections to the notebook:

1. explicit gap-state indexing;
2. field-L2 ordinary division instead of notebook floor division.

Do not simply inherit the current claim that these are bugs.

For each:

- inspect the exact notebook expression;
- inspect surrounding notebook logic;
- inspect paper equations and Methods;
- determine the apparent scientific intent;
- quantify the numerical effect;
- state whether the evidence supports calling it:
  - implementation bug;
  - ambiguous behavior;
  - intentional upstream behavior;
  - REvoCompute correction.

If the literature cannot disambiguate the behavior, say so.

Preserve the upstream behavior in a reproducible reference where useful, and keep
the REvoCompute deviation explicit.

No silent "fixes".

---

# 5. Audit All Other Existing Deviations

Explicitly review the current differences already mentioned in the Runner:

- zero versus inverse-covariance initialization;
- batch-size clamping;
- field pseudocount floor;
- deterministic seed;
- configurable weighting thresholds;
- approximate versus exact dominant eigenvalue;
- optimizer transcription;
- parameter scaling by `L`, `K`, and `Neff`.

For each one answer:

1. What does the paper do?
2. What does the notebook do?
3. What does REvoCompute do?
4. Why?
5. Does it change scientific interpretation?
6. Should it be a user-facing parameter, fixed runtime behavior, or golden-case-only setting?

Do not automatically make the most expensive/upstream-like behavior the production default.

Do not automatically favor the fastest behavior either.

Use evidence.

---

# 6. Separate Three Different Scientific Quantities

The final code, docs and Storyboard must not conflate:

## Model parameters

    B / V
    W

## Sequence/model scores

    Hamiltonian
    pseudo-likelihood / reconstruction loss

## Pairwise/contact-oriented projections

    raw Frobenius norm matrix
    APC-corrected matrix
    ranked residue-pair scores

These are different scientific objects.

Names, descriptions and UI must preserve that distinction.

---

# 7. Profile Semantics

Audit `profiles/profile.tsv`.

If it contains empirical state frequencies from the modeled alignment, continue to
call it:

    profile
    residue frequencies
    position profile

Do not call it a PSSM unless it actually contains position-specific scoring
values with a defined background/log-odds interpretation.

Document this distinction explicitly.

---

# 8. Coupling Interpretation

Do not describe a high GREMLIN coupling as proof of:

    direct physical contact
    causality
    functional coupling

without qualification.

The result should communicate that pairwise scores represent statistical
dependence extracted from the fitted model.

Contact-oriented interpretation is a downstream use of those scores.

Preserve raw scores, APC scores, sequence separation, alignment indices and
query indices.

---

# 9. Reconsider Raw vs APC Result Hierarchy

Do not assume that the current:

    APC-corrected coupling strengths = primary result

is automatically the correct GREMLIN_LH presentation.

The Wang paper's scientific argument explicitly concerns the relationship between
LH-regularized raw parameters and APC-corrected parameters.

After the literature audit, determine whether the most informative presentation is:

    APC primary
    raw primary
    raw + APC comparison
    or another evidence-based composition

Document the choice.

Do not redesign based on aesthetics.

---

# 10. Golden Scientific Case

Retain the existing fast synthetic fixture for protocol testing:

    tests/data/msa/gremlin_lh_tiny.a3m

but it is not scientific acceptance.

Audit the existing reference case:

    tests/data/msa/2KL8.i90c75_aln.a3m

Before continuing to call it the golden scientific case, establish:

- where it came from;
- why it is appropriate;
- its input SHA;
- rows / width;
- preprocessing;
- exact parameter set;
- upstream notebook provenance.

If the existing 2KL8 case is suitable, retain it rather than inventing a new one.

Do not reproduce the paper's hundreds-of-proteins benchmarks merely for this PR.

---

# 11. Golden Receipt

Strengthen the frozen scientific receipt only where needed.

It should capture enough independent observables to detect a scientifically
meaningful drift without freezing every floating-point number.

At minimum consider:

- sequence weights;
- Neff;
- selected one-body fields;
- selected W blocks;
- coupling tensor norm;
- maximum coupling magnitude;
- raw coupling matrix;
- APC matrix;
- strongest pair identities;
- selected Hamiltonian / pseudo-likelihood values if appropriate.

Every numerical tolerance needs a reason.

Do not use broad tolerances merely to make CI pass.

Do not require bitwise equality where JAX floating-point ordering makes that
scientifically meaningless.

---

# 12. Reference Generation Must Be Reproducible

The golden reference cannot be an unexplained JSON blob.

Document:

    upstream commit
    notebook blob
    input hash
    dependency versions
    parameters
    seed
    intentional corrections
    generation procedure

If practical, provide a small reference-generation script or documented command
that regenerates the receipt from the pinned upstream implementation.

The generator does not need to run in normal CI.

---

# 13. Durable MRF Artifact

Audit:

    model/gremlin_mrf.npz

Ensure it is sufficient to reconstruct the scientific model state.

At minimum verify:

    fields
    couplings
    alphabet
    sequence weights
    gap index
    dimensions / shapes
    parameter metadata
    upstream identity

Do not use pickle.

Do not duplicate huge arrays into JSON.

`metadata.json` should make the NPZ interpretable without requiring a reader to
inspect `fit_model.py`.

---

# 14. Artifact Semantics

Audit every output:

    summary.json
    query.fasta
    alignment/filtered_alignment.a3m
    alignment/statistics.json
    alignment/sequence_weights.tsv
    model/gremlin_mrf.npz
    model/metadata.json
    model/training_history.csv
    model/sequence_scores.tsv
    profiles/profile.tsv
    couplings/pairwise_scores.tsv
    couplings/raw_scores.csv
    couplings/apc_scores.csv
    plots/coupling_apc.png

For each determine whether it is:

    primary scientific result
    scientific evidence
    provenance
    diagnostic
    transport/download artifact

Result semantics must derive from canonical declarations, not filename heuristics.

---

# 15. `task_finished`

The recent real browser acceptance exposed a zero-byte `task_finished` marker.

PR35 correctly restored the rule that the frontend must render every artifact the
manifest declares.

Therefore:

> Do not hide `task_finished` in the frontend.

Determine why it is being published as a user-facing artifact.

If it is purely an execution marker, fix the producer/result publication boundary
so it is not declared as a scientific artifact.

Do not special-case its filename in generic frontend code.

---

# 16. Generic Matrix View Must Actually Render a Matrix

The current Task declares:

    plugin: matrix

for:

    couplings/apc_scores.csv

but the live GREMLIN_LH acceptance showed it being rendered as an ordinary CSV
table/text-oriented artifact.

This violates the declared ResultView semantics.

Fix this generically.

The solution must:

- honor `ResultView.plugin == matrix`;
- use the existing generic `PairMatrix` scientific primitive where appropriate;
- use authorized/bounded data loading;
- obey declared mapping:
  - row labels;
  - axis labels;
  - units;
  - direction;
  - scale;
  - center;
- support negative APC values correctly;
- support light/dark themes;
- support resize;
- support keyboard selection;
- avoid loading unbounded matrices into the browser;
- fail gracefully to download/table access when the declared matrix cannot be rendered.

Absolutely no:

    if (runner === "gremlin_lh")

branch in generic frontend code.

The underlying CSV is transport.

The declared `matrix` view is presentation semantics.

---

# 17. Test the Generic Matrix Renderer Independently

Add frontend/browser tests with synthetic matrices.

Cover at least:

- square numeric matrix;
- row-label column;
- negative / zero / positive values;
- diverging scale centered at zero;
- bounded-size enforcement;
- keyboard navigation;
- responsive resize;
- dark mode;
- malformed matrix;
- unavailable projection/table endpoint.

Do not make GREMLIN_LH the only test of the generic primitive.

---

# 18. Storyboard Must Become a Scientific Narrative

The current GREMLIN_LH Storyboard is primarily a categorized download launcher.

Rework it after the scientific audit.

It should answer scientific questions in an intentional order.

A likely structure is:

    1. What alignment was modeled?
    2. How much independent evolutionary information was present?
    3. What model was fit?
    4. What coupling landscape was inferred?
    5. Which residue pairs carry the strongest statistical coupling?
    6. What model/provenance artifacts are available for downstream analysis?

Do not copy this exact ordering if the literature audit supports a better one.

---

# 19. Storyboard Must Not Duplicate Generic Renderers

Runner Storyboard owns scientific composition.

Generic frontend owns reusable rendering.

Do not implement a second CSV parser, matrix renderer, table renderer or image
viewer inside:

    docker/runners/gremlin_lh/storyboard/index.js

The Storyboard should compose existing scientific result capabilities and expose
scientifically meaningful navigation/actions.

---

# 20. Remove Dead Result Views

The real acceptance showed an `evidence-bundle` tab whose effective user
experience was:

    No inline preview is available.

A declared ResultView should normally answer a scientific question.

If an object is simply a durable downloadable model bundle, prefer placing it in
the appropriately classified Files & diagnostics area unless there is a real
inline scientific presentation.

Do not keep dead tabs merely because the contract technically permits them.

---

# 21. Fix Artifact Role Classification at the Source

The live result placed scientifically meaningful GREMLIN_LH outputs such as some
plots/model evidence under:

    Other files

Do not fix this with filename heuristics in the frontend.

Adjust Runner-owned result declarations so the manifest projects correct roles.

Audit in particular:

    coupling_apc.png
    sequence weights
    training history
    profile
    model metadata
    MRF archive
    sequence scores

Not every scientifically generated file needs to be `evidence`.

For example, optimization history may be primarily diagnostic/provenance rather
than a first-class scientific conclusion.

Make that judgment explicitly.

---

# 22. Scientific Result Copy

Rewrite Runner-owned result descriptions only where literature review shows
current wording is imprecise.

Avoid claims such as:

    contact
    energy
    stability
    coevolution

unless the exact quantity displayed supports the term.

Especially distinguish:

    model Hamiltonian
    thermodynamic free energy

They are not interchangeable.

If the paper reports empirical correlation of Hamiltonian with stability in
specific systems, do not turn that into a universal statement about any
GREMLIN_LH run.

---

# 23. Citation Provenance

A completed GREMLIN_LH result should preserve citations to:

- Wang et al. 2024 — GREMLIN_LH / LH method;
- Kamisetty et al. 2013 — GREMLIN model lineage.

Document the PNAS correction in the scientific traceability record.

Do not burden the normal result surface with bibliographic clutter.

Citations belong in provenance/run metadata and documentation.

---

# 24. Fast Test vs Scientific Test

Keep two layers clearly separate.

## Fast protocol contract

Purpose:

    Does the Runner execute and honor the platform contract?

Use:

    gremlin_lh_tiny.a3m
    very few iterations

This can remain quick.

## Scientific acceptance

Purpose:

    Does the implementation reproduce the pinned scientific reference within
    justified numerical tolerances?

Use:

    validated real homolog alignment
    upstream-compatible parameter profile

Never claim the synthetic smoke test proves scientific equivalence.

---

# 25. Real Runtime Acceptance

After implementation/tests pass locally:

1. Build or validate the actual GREMLIN_LH SIF using normal Runner identity rules.
2. Run the golden case through:
   
       REvoCompute
       → Slurm
       → Apptainer
       → Result publication

3. Prefer browser submission.
4. API submission is acceptable only if browser automation genuinely blocks it.
5. Open the finished result in the browser.

Record:

    task ID
    exact git SHA
    SIF identity
    input SHA
    parameters
    walltime
    final status

---

# 26. Real Browser Result Acceptance

Inspect the actual finished page.

Verify:

- matrix is an actual matrix;
- Storyboard loads;
- primary result answers a scientific question;
- raw/APC terminology is correct;
- ranked pairs are interpretable;
- alignment view is useful;
- summary metrics are meaningful;
- durable MRF is available;
- artifact roles make sense;
- no important science is buried under `Other files`;
- no implementation markers dominate the page;
- no console errors;
- no failed result requests;
- no CSP violations;
- light mode;
- dark mode;
- narrow viewport.

Capture screenshots for review.

---

# 27. Scientific Acceptance Report

Produce a concise report for the real golden case.

It should state:

    What was modeled?
    What scientific quantities were produced?
    What matches upstream?
    What intentionally differs?
    What the user can infer?
    What the user must not infer?

This is more valuable than a simple PASS badge.

---

# 28. README Rewrite

After the audit, update the GREMLIN_LH README.

The final README must distinguish:

    paper semantics
    upstream notebook behavior
    REvoCompute production behavior
    deliberate deviations
    scientific acceptance
    result interpretation

Do not claim "reference-grade" merely because tests exist.

The implementation should earn that label from the completed evidence chain.

---

# 29. Do Not Generalize Prematurely

This work is intended to establish a reference pattern.

Do not in the same PR:

- retrofit every Runner;
- create a new Runner framework;
- create a generic scientific-validation service;
- redesign ResultManifest;
- redesign frontend/backend ownership;
- add a new workflow engine;
- rewrite the whole renderer registry;
- reproduce all experiments from the papers.

Prove the pattern with GREMLIN_LH first.

---

# 30. Minimal Generalization Allowed

A generic change is justified only when GREMLIN_LH exposes a real missing
platform capability that is already part of the declared contract.

The matrix renderer qualifies because `ResultView.plugin = matrix` already exists
and the frontend already contains a `PairMatrix` primitive.

Any other proposed generic abstraction needs independent justification.

---

# 31. Acceptance Criteria

This objective is complete when:

- the primary papers and supplement have been read;
- the PNAS correction has been considered;
- the pinned notebook has been audited;
- `SCIENTIFIC_TRACEABILITY.md` exists;
- all current implementation deviations are classified;
- scientifically unsupported deviations are corrected or explicitly retained;
- the golden reference is reproducible and provenanced;
- model fields/couplings and key derived scores are tested;
- raw/APC semantics are correct;
- profile semantics are correct;
- pairwise coupling interpretation is appropriately qualified;
- durable MRF state is complete and interpretable;
- artifact roles are intentional;
- `task_finished` is not hidden by frontend heuristics;
- declared matrix views render as real matrices;
- the Storyboard communicates a coherent scientific result;
- dead/no-preview scientific tabs are eliminated or justified;
- real Slurm/Apptainer execution succeeds;
- real browser Result acceptance succeeds;
- all exact-head CI gates pass.

---

# 32. Stop Rule

Once GREMLIN_LH is scientifically traceable from:

    papers
    → notebook
    → implementation
    → artifact
    → manifest
    → Storyboard
    → real browser

stop.

Do not use this PR to "clean up" the rest of REvoCompute.

The next step after this PR will be to decide which parts of the proven
GREMLIN_LH acceptance pattern are worth applying to the rest of the Runner fleet.
