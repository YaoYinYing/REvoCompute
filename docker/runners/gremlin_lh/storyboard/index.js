/* GREMLIN_LH scientific result: a question-ordered narrative over the runner's own declared views. */
/* SPDX-License-Identifier: GPL-3.0-only */

const STYLE = `
.glh-result > details > summary { cursor: pointer; padding-block: .75rem; font-size: .875rem; }
.glh-inspector { background: var(--app-stage) !important; }
.glh-result > .glh-section > h3 { font-size: 1.35rem; }
.glh-result > .glh-section > .glh-question { max-width: 85ch; }
.glh-bench { display: grid; grid-template-columns: minmax(0, 2.5fr) minmax(16rem, 1fr); border: 1px solid var(--app-line); border-radius: var(--r-control); background: var(--app-surface); overflow: hidden; }
.glh-result .btn { font: inherit; font-size: .875rem; padding: .55rem .7rem; min-height: 2.5rem; border: 1px solid var(--app-line); border-radius: var(--r-control); color: var(--app-ink); background: var(--app-surface); cursor: pointer; }
.glh-pair-preview { max-height: 24rem; overflow: auto; border-block: 1px solid var(--app-line); }
.glh-pair-preview th { position: sticky; top: 0; background: var(--app-soft); }
.glh-more > summary { cursor: pointer; font-size: .875rem; padding-block: .75rem; }
.glh-inspector .scalar-grid { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); border: 0; background: transparent; }
.glh-inspector .scalar-grid dt, .glh-inspector .scalar-grid dd { padding: .6rem 0; border-bottom: 1px solid var(--app-line); overflow-wrap: anywhere; }
.glh-inspector .scalar-grid dd { font: .875rem/1.5 var(--font-mono); text-align: right; }
.glh-landscape { min-width: 0; padding: 1rem; }
.glh-inspector { display: grid; gap: 1.5rem; align-content: start; padding: 1.5rem; background: var(--app-soft); }
.glh-inspector .glh-section h3 { font-size: 1.15rem; }
.glh-actions button[aria-pressed="true"] { color: var(--app-plum); border-color: var(--app-plum); }
@media (max-width: 1000px) { .glh-bench { grid-template-columns: minmax(0, 1fr); } }

.glh-result { --muted: var(--app-muted); display: grid; gap: 1.75rem; padding: .25rem; }
.glh-result h2, .glh-result h3, .glh-result p { margin: 0; }
.glh-result h2 { font-family: var(--font-display); font-size: 1.35rem; font-weight: 600; }
.glh-intro, .glh-question, .glh-note { color: var(--muted); font-size: .875rem; line-height: 1.5; }
.glh-section { display: grid; gap: .55rem; min-width: 0; padding-top: .9rem; border-top: 1px solid color-mix(in srgb, currentColor 18%, transparent); }
.glh-section:first-of-type { padding-top: 0; border-top: 0; }
.glh-section h3 { font: 500 1.35rem/1.3 var(--font-display); letter-spacing: -.025em; }
.glh-actions { display: flex; flex-wrap: wrap; gap: .45rem; }
.glh-provenance { display: grid; gap: .5rem; }
.glh-provenance-row { display: flex; flex-wrap: wrap; align-items: baseline; gap: .55rem; }
.glh-provenance-row .glh-label { font-size: .875rem; font-weight: 600; }
.glh-provenance-row .glh-note { flex: 1 1 14rem; }
.glh-unavailable { color: var(--muted); font-size: .875rem; font-style: italic; }
`;

function list(value) { return Array.isArray(value) ? value : value ? [value] : []; }
function first(context, id) { return list(context.files.get(id))[0] || null; }

function section(question, framing) {
  const node = document.createElement("section"); node.className = "glh-section";
  const heading = document.createElement("h3"); heading.textContent = question; node.appendChild(heading);
  if (framing) { const note = document.createElement("p"); note.className = "glh-question"; note.textContent = framing; node.appendChild(note); }
  return node;
}
function message(value, className) { const node = document.createElement("p"); node.className = className || "glh-note"; node.textContent = value; return node; }
function button(label, run) {
  const node = document.createElement("button"); node.type = "button"; node.className = "btn btn-soft"; node.textContent = label;
  node.addEventListener("click", () => { void run(); });
  return node;
}
function fileAction(label, artifact, context) {
  const node = button(label, () => context.services.openFile(artifact)); node.dataset.fileId = artifact.id || artifact.path; return node;
}
function downloadAction(label, artifact, context) {
  const node = button(label, () => context.services.downloadFile(artifact)); node.dataset.fileId = artifact.id || artifact.path; return node;
}
function viewAction(label, view, openView) {
  const node = button(label, () => openView(view.id)); node.dataset.viewId = view.id; return node;
}
async function fetchJson(artifact, signal) {
  const response = window.REvoDesignAuth
    ? await window.REvoDesignAuth.authFetch(artifact.url, { signal })
    : await fetch(artifact.url, { credentials: "same-origin", signal });
  if (!response.ok) throw new Error("GREMLIN_LH evidence could not be loaded.");
  return response.json();
}

export default {
  async mount(host, context) {
    const Scientific = window.REvoComputeScientific;
    if (!Scientific) throw new Error("Scientific result components are unavailable.");
    const controller = new AbortController();
    let destroyed = false;
    let embedded = null;
    let matrixController = null;
    let pairRenderer = null;

    // Navigate to the task's own declared views instead of re-implementing them.
    const views = Array.isArray(context.views) ? context.views : [];
    const openView = typeof context.services.openView === "function" ? context.services.openView : null;
    // The manifest declares which coupling matrix is primary, so the narrative
    // reports the declared hierarchy instead of re-deriving it from a name.
    const matrixViews = views.filter((view) => view.plugin === "matrix");
    const primaryMatrixView = matrixViews.find((view) => view.role === "primary") || matrixViews[0] || null;
    const comparisonMatrixView = matrixViews.find((view) => view !== primaryMatrixView) || null;
    const rankedPairsView = views.find((view) => view.plugin === "entity-table") || null;
    const openDeclaredView = (view) => (view && openView ? viewAction("Open " + view.title, view, openView) : null);

    const statisticsFile = first(context, "alignment_statistics");
    const metadataFile = first(context, "model_metadata");
    const weightsFile = first(context, "sequence_weights");
    const alignmentFile = first(context, "alignment");
    const queryFile = first(context, "query");
    const rawFile = first(context, "raw_matrix");
    const apcFile = first(context, "apc_matrix");
    const pairwiseFile = first(context, "pairwise_scores");

    const root = document.createElement("div"); root.className = "glh-result";
    const style = document.createElement("style"); style.textContent = STYLE;
    const intro = document.createElement("p"); intro.className = "glh-intro";
    intro.textContent = "A regularized Potts/MRF model fitted to the submitted alignment. Every coupling score below " +
      "is a statistical dependency of the fitted model: contact evidence, not proof of a physical contact.";
    root.append(style);

    const alignmentSection = section("Fit evidence", "The alignment actually modelled.");
    const alignmentMetrics = document.createElement("div"); const alignmentActions = document.createElement("div");
    alignmentActions.className = "glh-actions"; alignmentSection.append(alignmentMetrics, alignmentActions); root.append(alignmentSection);

    const informationSection = section("How much independent evolutionary information was present?", "Phylogenetically similar rows are down-weighted, so the effective sequence count limits the available signal and the overfitting risk.");
    const informationMetrics = document.createElement("div"); const informationActions = document.createElement("div");
    informationActions.className = "glh-actions"; informationSection.append(informationMetrics, informationActions); root.append(informationSection);

    const modelSection = section("What model was fit?", "A pairwise MRF over positions x amino-acid states, with durable one-site fields alongside the couplings.");
    const modelMetrics = document.createElement("div"); modelSection.append(modelMetrics); root.append(modelSection);

    const couplingSection = section("What coupling landscape was inferred?",
      primaryMatrixView
        ? "The primary matrix is the contact-oriented object: PRX Life reports that for LH weights in its tuned range the raw Frobenius matrix converges toward the average-product-corrected (APC) one, so the corrected matrix is kept as the declared comparison. That convergence is the paper's asymptotic benchmark, not a property of any single run."
        : "These are Frobenius norms of the fitted pairwise couplings. Average-product correction (APC) is the declared comparison; the uncorrected raw matrix is also available.");
    const couplingActions = document.createElement("div"); couplingActions.className = "glh-actions";
    const primaryMatrixAction = openDeclaredView(primaryMatrixView) || (rawFile ? fileAction("Open coupling matrix (raw)", rawFile, context) : null);
    const comparisonMatrixAction = openDeclaredView(comparisonMatrixView) || (apcFile ? fileAction("Open coupling matrix (APC)", apcFile, context) : null);
    if (primaryMatrixAction) couplingActions.append(primaryMatrixAction);
    if (comparisonMatrixAction) couplingActions.append(comparisonMatrixAction);
    couplingSection.append(couplingActions, message("Bounded matrices are rendered by the task's own declared view.", "glh-note"));
    const interpretation = document.createElement("details"); const interpretationTitle = document.createElement("summary"); interpretationTitle.textContent = "Scientific interpretation"; interpretation.append(interpretationTitle, intro, couplingSection); root.append(interpretation);

    const pairsSection = section("Ranked residue pairs", "Upper-triangle pairs ranked by APC-corrected strength, with raw and APC scores side by side. The top pairs are the strongest dependencies in the fit and need independent validation before being read as contacts.");
    const pairsActions = document.createElement("div"); pairsActions.className = "glh-actions";
    const pairsAction = openDeclaredView(rankedPairsView) || (pairwiseFile ? fileAction("Open ranked residue pairs", pairwiseFile, context) : null);
    pairsActions.append(pairsAction || message("Ranked residue pairs were not published.", "glh-unavailable"));
    pairsSection.append(pairsActions);
    if (rankedPairsView && context.services.mountView) {
      const pairTable = document.createElement("div"); pairTable.className = "glh-pair-preview";
      pairTable.setAttribute("role", "region"); pairTable.setAttribute("aria-label", "Ranked residue pairs preview"); pairTable.tabIndex = 0;
      pairsSection.append(pairTable);
      queueMicrotask(async () => {
        try {
          const instance = await context.services.mountView(rankedPairsView.id, pairTable, controller.signal);
          if (destroyed) instance?.destroy(); else pairRenderer = instance;
        } catch (error) { if (!destroyed && error.name !== "AbortError") pairTable.append(message(error.message, "glh-unavailable")); }
      });
    }
    root.append(pairsSection);

    const provenanceSection = section("What model and provenance artifacts are available for downstream analysis?", "Durable scientific objects for reuse, with the run metadata that identifies them.");
    const provenance = document.createElement("div"); provenance.className = "glh-provenance";
    [
      ["mrf_model", "Durable MRF model (NPZ)", "One-site fields and pairwise couplings in GREMLIN_LH's own array layout.", "download"],
      ["model_metadata", "Model metadata (JSON)", "Alphabet, gap index, array shapes, regularization, and upstream commit.", "open"],
      ["profile", "Position profile (TSV)", "Observed per-position state frequencies, consensus, entropy, and gap fraction.", "open"],
      ["sequence_scores", "Per-sequence scores (TSV)", "Phylogenetic weight, pseudo-likelihood loss, and MRF Hamiltonian for each row.", "open"],
      ["training_history", "Training history (CSV)", "Optimization loss and regularization trace.", "open"],
      ["summary", "Run summary (JSON)", "Run-level alignment, model, and optimization metadata.", "open"],
    ].forEach(([id, label, note, kind]) => {
      const row = document.createElement("div"); row.className = "glh-provenance-row";
      const title = document.createElement("span"); title.className = "glh-label"; title.textContent = label;
      const description = document.createElement("span"); description.className = "glh-note"; description.textContent = note;
      row.append(title, description);
      const artifact = first(context, id);
      if (!artifact) row.append(message(label + " unavailable", "glh-unavailable"));
      else if (kind === "download") row.append(downloadAction("Download", artifact, context));
      else row.append(fileAction("Open", artifact, context));
      provenance.append(row);
    });
    provenanceSection.append(provenance); const artifacts = document.createElement("details"); const artifactsTitle = document.createElement("summary"); artifactsTitle.textContent = "Model artifacts and provenance"; artifacts.append(artifactsTitle, provenanceSection); root.append(artifacts);

    if (primaryMatrixView && context.services.mountView) {
      const bench = document.createElement("div"); bench.className = "glh-bench";
      const landscape = document.createElement("section"); landscape.className = "glh-landscape";
      const tabs = document.createElement("div"); tabs.className = "glh-actions";
      tabs.setAttribute("role", "group"); tabs.setAttribute("aria-label", "Coupling matrix");
      const canvas = document.createElement("div"); canvas.className = "glh-matrix";
      let generation = 0;
      const show = async view => {
        const current = ++generation;
        matrixController?.abort(); matrixController = new AbortController();
        embedded?.destroy(); embedded = null;
        canvas.replaceChildren(message("Loading " + view.title + "…"));
        tabs.querySelectorAll("button").forEach(tab => tab.setAttribute("aria-pressed", String(tab.dataset.viewId === view.id)));
        try {
          const instance = await context.services.mountView(view.id, canvas, matrixController.signal);
          if (destroyed || current !== generation) { instance?.destroy(); return; }
          embedded = instance;
        } catch (error) { if (!destroyed && current === generation && error.name !== "AbortError") canvas.replaceChildren(message(error.message, "glh-unavailable")); }
      };
      for (const view of matrixViews) {
        const tab = button(view.title, () => show(view)); tab.dataset.viewId = view.id; tabs.append(tab);
      }
      landscape.append(tabs, canvas);
      const inspector = document.createElement("aside"); inspector.className = "glh-inspector";
      const more = document.createElement("details"); more.className = "glh-more";
      const summary = document.createElement("summary"); summary.textContent = "Weighting and fitted model";
      more.append(summary, informationSection, modelSection); inspector.append(message("Statistical dependencies of the fitted model; not proof of physical contacts."), alignmentSection, more);
      bench.append(landscape, inspector); style.after(bench); pairsSection.after(interpretation);
      queueMicrotask(() => { if (!destroyed) void show(primaryMatrixView); });
    }
    host.replaceChildren(root);

    function fillMetrics(target, metrics) {
      if (destroyed || !metrics.length) return false;
      new Scientific.ScalarMetricGrid(target, metrics);
      return true;
    }
    async function loadStatistics() {
      if (statisticsFile) {
        try {
          const statistics = await fetchJson(statisticsFile, controller.signal);
          if (destroyed) return;
          const rows = [
            { label: "Modelled sequences", value: statistics.sequence_count, unit: "rows" },
            { label: "Alignment width", value: statistics.alignment_length, unit: "positions" },
            { label: "Columns excluded from weighting", value: statistics.columns_excluded_by_gap_cutoff, unit: "positions" },
            { label: "Query length", value: statistics.query_length, unit: "residues" },
            { label: "Mean gap fraction", value: statistics.mean_gap_fraction },
            { label: "Effective sequence count (Neff)", value: statistics.effective_sequence_count, unit: "sequences" },
            { label: "Identity cutoff for weighting", value: statistics.identity_cutoff },
            { label: "Gap cutoff for weighting", value: statistics.gap_cutoff },
          ];
          fillMetrics(alignmentMetrics, [rows[0], rows[1], rows[5], rows[3]]);
          fillMetrics(informationMetrics, rows.slice(5));
        } catch (error) {
          if (destroyed || error.name === "AbortError") return;
          alignmentMetrics.append(message(error.message || "Alignment statistics could not be loaded.", "glh-unavailable"));
          informationMetrics.append(message("Effective sequence count could not be loaded.", "glh-unavailable"));
        }
      } else {
        alignmentMetrics.append(message("Alignment statistics were not published.", "glh-unavailable"));
        informationMetrics.append(message("Effective sequence count was not published.", "glh-unavailable"));
      }
      if (alignmentFile) alignmentActions.append(fileAction("Open filtered alignment", alignmentFile, context));
      if (queryFile) alignmentActions.append(fileAction("Open query sequence", queryFile, context));
      if (weightsFile) informationActions.append(fileAction("Open per-sequence weights", weightsFile, context));
    }
    async function loadMetadata() {
      if (!metadataFile) { modelMetrics.append(message("Model metadata was not published.", "glh-unavailable")); return; }
      try {
        const metadata = await fetchJson(metadataFile, controller.signal);
        if (destroyed) return;
        const shape = metadata.arrays && metadata.arrays.couplings ? metadata.arrays.couplings.shape : null;
        fillMetrics(modelMetrics, [
          { label: "Regularization", value: metadata.regularization },
          { label: "Model positions", value: metadata.positions, unit: "positions" },
          { label: "States per position", value: metadata.states, unit: "states" },
          { label: "Coupling tensor", value: shape ? shape.join(" x ") : null },
          { label: "One-site fields", value: metadata.parameters && metadata.parameters.use_bias === false ? "not fitted" : "fitted" },
        ]);
      } catch (error) {
        if (destroyed || error.name === "AbortError") return;
        modelMetrics.append(message(error.message || "Model metadata could not be loaded.", "glh-unavailable"));
      }
    }
    await Promise.all([loadStatistics(), loadMetadata()]);

    return { destroy() { destroyed = true; controller.abort(); matrixController?.abort(); embedded?.destroy(); pairRenderer?.destroy(); } };
  },
};
