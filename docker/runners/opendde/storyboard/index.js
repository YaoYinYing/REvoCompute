/* OpenDDE scientific result composition. */
/* SPDX-License-Identifier: GPL-3.0-only */

const MATRIX_TYPES = [
  { key: "token_pair_pae", label: "Predicted aligned error", short: "PAE", unit: "Å", direction: "Lower is better" },
  { key: "token_pair_pde", label: "Predicted distance error", short: "PDE", unit: "Å", direction: "Lower is better" },
  { key: "contact_probs", label: "Contact probability", short: "Contact probability", unit: "probability", direction: "Higher is better" },
];
const STYLE = `
.opendde-result { display: grid; gap: 1rem; padding: 1rem; }
.opendde-result h2, .opendde-result h3, .opendde-result p { margin: 0; }
.opendde-section { display: grid; gap: 0.55rem; }
.opendde-section[hidden] { display: none; }
.opendde-candidates, .opendde-actions { display: flex; flex-wrap: wrap; gap: 0.45rem; }
.opendde-candidates button[aria-current="true"] { outline: 2px solid var(--accent); outline-offset: 2px; }
`;

function list(value) { return Array.isArray(value) ? value : value ? [value] : []; }
function name(artifact) { return artifact.name || String(artifact.path || "").split("/").pop(); }
function label(artifact, index) { const sample = name(artifact).match(/_sample_(\d+)\.cif$/); return "Candidate " + (index + 1) + " - sample " + (sample ? sample[1] : "?"); }
function section(title, note) { const node = document.createElement("section"); node.className = "opendde-section"; const heading = document.createElement("h3"); heading.textContent = title; node.appendChild(heading); if (note) { const text = document.createElement("p"); text.className = "scientific-note"; text.textContent = note; node.appendChild(text); } return node; }
function message(text) { const node = document.createElement("p"); node.className = "preview-message"; node.textContent = text; return node; }
async function fetchSummary(artifact, signal) { const response = window.REvoDesignAuth ? await window.REvoDesignAuth.authFetch(artifact.url, { signal }) : await fetch(artifact.url, { credentials: "same-origin", signal }); if (!response.ok) throw new Error("The OpenDDE confidence summary could not be loaded."); return response.json(); }
function matrixRows(projection) { if (!projection || projection.shape.length !== 2) return null; const [rows, columns] = projection.shape; if (rows < 1 || columns !== rows) return null; return Array.from({ length: rows }, (_, row) => projection.values.slice(row * columns, (row + 1) * columns)); }

export default {
  async mount(host, context) {
    const Scientific = window.REvoComputeScientific;
    if (!Scientific || typeof Scientific.loadNumericProjection !== "function") throw new Error("Scientific result components are unavailable.");
    const structures = list(context.files.get("structures")); const summaries = list(context.files.get("summaries")); const full = list(context.files.get("full_confidences"));
    const summariesAligned = summaries.length === structures.length; const fullAligned = full.length === structures.length;
    let generation = 0; let confidencePlot = null; let pairMatrix = null;
    const root = document.createElement("div"); root.className = "opendde-result"; const style = document.createElement("style"); style.textContent = STYLE;
    const heading = document.createElement("h2"); heading.textContent = "OpenDDE prediction"; const intro = document.createElement("p"); intro.textContent = "All-atom structure samples with candidate-matched confidence reported by OpenDDE."; root.append(style, heading, intro);
    const candidates = section("Structure samples", "Selecting a sample updates its structure controls and every available confidence view."); const candidateHost = document.createElement("div"); candidateHost.className = "opendde-candidates"; candidates.appendChild(candidateHost); const actions = document.createElement("div"); actions.className = "opendde-actions"; candidates.appendChild(actions); root.appendChild(candidates);
    const metrics = section("Model confidence", "Published values are shown without client-side rescaling."); const metricHost = document.createElement("div"); metrics.appendChild(metricHost); root.appendChild(metrics);
    const local = section("Atom confidence", "OpenDDE atom pLDDT is shown on its published 0-1 scale."); const localHost = document.createElement("div"); localHost.className = "metric-chart"; local.appendChild(localHost); local.hidden = true; root.appendChild(local);
    const pairs = section("Pairwise confidence", null); pairs.hidden = true; const pairToolbar = document.createElement("div"); pairToolbar.className = "scientific-toolbar"; const pairLabel = document.createElement("label"); pairLabel.textContent = "Matrix "; const pairSelect = document.createElement("select"); pairSelect.setAttribute("aria-label", "Pairwise confidence matrix"); pairLabel.appendChild(pairSelect); pairToolbar.appendChild(pairLabel); pairs.appendChild(pairToolbar);
    const pairWarning = document.createElement("p"); pairWarning.className = "preview-message"; pairWarning.hidden = true; pairs.appendChild(pairWarning);
    const pairNote = document.createElement("p"); pairNote.className = "scientific-note"; pairs.appendChild(pairNote); const plot = document.createElement("div"); plot.className = "pair-matrix-plot"; const figure = document.createElement("div"); figure.className = "pair-matrix-figure"; const canvas = document.createElement("canvas"); canvas.className = "pair-matrix-canvas"; canvas.tabIndex = 0; canvas.setAttribute("role", "grid"); figure.appendChild(canvas); plot.appendChild(figure); pairs.appendChild(plot); const readout = document.createElement("p"); readout.className = "matrix-readout"; readout.setAttribute("role", "status"); pairs.appendChild(readout); root.appendChild(pairs); host.replaceChildren(root);

    async function optionalProjection(artifact, key, signal) {
      if (!artifact || !artifact.ndarray_url) return { projection: null, error: null };
      try { return { projection: await Scientific.loadNumericProjection(artifact, { key, signal }), error: null }; }
      catch (error) {
        if (error.name === "AbortError") throw error;
        return { projection: null, error };
      }
    }
    function showMatrix(entry) {
      if (pairMatrix) pairMatrix.destroy();
      const values = matrixRows(entry.projection); const xLabels = Array.from({ length: entry.projection.shape[1] }, (_, index) => String(index + 1)); const yLabels = Array.from({ length: entry.projection.shape[0] }, (_, index) => String(index + 1));
      pairMatrix = new Scientific.PairMatrix({ figure, canvas, readout, observe: plot, minimum: 0, decimals: entry.type.unit === "probability" ? 2 : 1, xTitle: "Aligned token", yTitle: "Scored token", legendTitle: entry.type.short, unit: entry.type.unit, formatReadout: ({ xLabel, yLabel, value }) => "Aligned token " + xLabel + " · Scored token " + yLabel + " · " + (Number.isFinite(value) ? value.toFixed(entry.type.unit === "probability" ? 2 : 1) + " " + entry.type.unit : "N/A") });
      pairMatrix.setData({ values, xLabels, yLabels }); pairNote.textContent = entry.type.label + " for " + entry.projection.shape[0] + " × " + entry.projection.shape[1] + " tokens. " + entry.type.direction + ".";
    }
    function clearCandidate(messageText) {
      actions.replaceChildren(); metricHost.replaceChildren(message(messageText));
      if (confidencePlot) { confidencePlot.destroy(); confidencePlot = null; }
      localHost.replaceChildren(); local.hidden = true;
      pairSelect.replaceChildren(); pairToolbar.hidden = true; pairWarning.hidden = true; pairWarning.textContent = "";
      pairNote.textContent = ""; plot.hidden = true; readout.hidden = true; readout.textContent = ""; pairs.hidden = true;
      if (pairMatrix) { pairMatrix.destroy(); pairMatrix = null; }
    }
    async function select(structure, index, request) {
      const current = ++generation; const summary = summariesAligned ? summaries[index] : null; const fullArtifact = fullAligned ? full[index] : null;
      clearCandidate("Loading candidate confidence...");
      if (!summary) { clearCandidate("No confidence summary matches this sample."); return; }
      try {
        const payload = await fetchSummary(summary, request.signal); const atomResult = await optionalProjection(fullArtifact, "atom_plddt", request.signal); const matrixValues = [];
        for (const type of MATRIX_TYPES) matrixValues.push(await optionalProjection(fullArtifact, type.key, request.signal));
        if (current !== generation || !request.current()) return;
        actions.replaceChildren(); const open = document.createElement("button"); open.type = "button"; open.className = "btn btn-soft"; open.textContent = "Open selected structure"; open.addEventListener("click", () => context.services.openFile(structure)); actions.appendChild(open); if (fullArtifact) { const download = document.createElement("button"); download.type = "button"; download.className = "btn btn-soft"; download.textContent = "Download full confidence"; download.addEventListener("click", () => context.services.downloadFile(fullArtifact)); actions.appendChild(download); }
        new Scientific.ScalarMetricGrid(metricHost, [{ label: "pLDDT", value: payload.plddt, unit: "score", meaning: "Higher is better" }, { label: "pTM", value: payload.ptm, unit: "score", meaning: "Higher is better" }, { label: "ipTM", value: payload.iptm, unit: "score", meaning: "Higher is better" }, { label: "gPDE", value: payload.gpde, unit: "score", meaning: "Lower is better" }, { label: "Ranking score", value: payload.ranking_score, unit: "score", meaning: "Higher is better" }, { label: "Clash", value: payload.has_clash == null ? null : (payload.has_clash ? "Yes" : "No") }]);
        if (confidencePlot) { confidencePlot.destroy(); confidencePlot = null; }
        local.hidden = false; localHost.replaceChildren();
        const atomConfidence = atomResult.projection;
        if (atomConfidence && atomConfidence.shape.length === 1 && atomConfidence.values.length) {
          try { confidencePlot = new Scientific.LocalConfidenceSeries(localHost, { series: [{ label: "Atom pLDDT", values: atomConfidence.values }], xLabel: "Atom index", yLabel: "Atom pLDDT", yMin: 0, yMax: 1, unit: "score", direction: "Higher is better" }); }
          catch (_error) { localHost.replaceChildren(message("Atom confidence could not be displayed.")); }
        } else if (atomResult.error) localHost.replaceChildren(message("Atom confidence could not be displayed."));
        else local.hidden = true;
        const entries = MATRIX_TYPES.map((type, position) => ({ type, projection: matrixValues[position].projection, error: matrixValues[position].error }));
        const available = entries.filter((entry) => matrixRows(entry.projection)); const hasFailure = entries.some((entry) => entry.error || (entry.projection && !matrixRows(entry.projection)));
        pairs.hidden = !available.length && !hasFailure; pairWarning.hidden = !hasFailure; pairWarning.textContent = hasFailure ? "Some pairwise confidence data could not be displayed." : "";
        pairSelect.replaceChildren(); available.forEach((entry, position) => { const option = document.createElement("option"); option.value = String(position); option.textContent = entry.type.short; pairSelect.appendChild(option); }); if (available.length) { pairToolbar.hidden = false; plot.hidden = false; readout.hidden = false; pairSelect.onchange = () => showMatrix(available[Number(pairSelect.value)]); try { showMatrix(available[0]); } catch (_error) { pairWarning.hidden = false; pairWarning.textContent = "Some pairwise confidence data could not be displayed."; plot.hidden = true; readout.hidden = true; } } else { pairToolbar.hidden = true; plot.hidden = true; readout.hidden = true; if (pairMatrix) { pairMatrix.destroy(); pairMatrix = null; } }
        return true;
      } catch (error) { if (error.name === "AbortError" || !request.current()) return; clearCandidate(error.message || "OpenDDE confidence could not be loaded."); }
    }
    const selector = new Scientific.CandidateSelector(candidateHost, { items: structures, store: context.selection, label, onSelect: select }); if (structures.length) await selector.select(0); else candidateHost.replaceChildren(message("No structure sample was published."));
    return { destroy() { generation += 1; selector.destroy(); if (confidencePlot) confidencePlot.destroy(); if (pairMatrix) pairMatrix.destroy(); } };
  },
};
