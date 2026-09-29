/* ESMFold 2 scientific result composition. */
/* SPDX-License-Identifier: GPL-3.0-only */

const STYLE = `
.esmfold-result { display: grid; gap: 1rem; padding: 1rem; }
.esmfold-result h2, .esmfold-result h3, .esmfold-result p { margin: 0; }
.esmfold-section { display: grid; gap: 0.55rem; min-width: 0; }
.esmfold-candidates, .esmfold-actions { display: flex; flex-wrap: wrap; gap: 0.45rem; }
.esmfold-candidates button[aria-current="true"] { outline: 2px solid var(--accent); outline-offset: 2px; }
.esmfold-columns { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 26rem), 1fr)); gap: 1rem; }
.esmfold-figure { position: relative; overflow: hidden; }
.esmfold-figure canvas { display: block; max-width: 100%; }
.esmfold-figure .pair-matrix-label { position: absolute; color: var(--muted); font-size: 11px; }
.esmfold-figure .af3-label-x { transform: translateX(-50%); }
.esmfold-figure .af3-label-y { transform: translateY(-50%); }
.esmfold-figure .af3-title { color: var(--ink); font-size: 12px; }
.esmfold-figure .af3-title-y { transform: translate(-50%, -50%) rotate(-90deg); white-space: nowrap; }
`;

function list(value) { return Array.isArray(value) ? value : value ? [value] : []; }
function section(title, note) { const node = document.createElement("section"); node.className = "esmfold-section"; const heading = document.createElement("h3"); heading.textContent = title; node.appendChild(heading); if (note) { const text = document.createElement("p"); text.className = "scientific-note"; text.textContent = note; node.appendChild(text); } return node; }
function message(text) { const node = document.createElement("p"); node.className = "preview-message"; node.textContent = text; return node; }
async function response(artifact, signal) { const value = window.REvoDesignAuth ? await window.REvoDesignAuth.authFetch(artifact.url, { signal }) : await fetch(artifact.url, { credentials: "same-origin", signal }); if (!value.ok) throw new Error("ESMFold 2 evidence could not be loaded."); return value; }
function square(values) { return Array.isArray(values) && values.length && values.every((row) => Array.isArray(row) && row.length === values.length); }

export default {
  async mount(host, context) {
    const Scientific = window.REvoComputeScientific; if (!Scientific) throw new Error("Scientific result components are unavailable.");
    const structures = list(context.files.get("structures")); const summaries = list(context.files.get("summaries")); const locals = list(context.files.get("local_confidence")); const paeFiles = list(context.files.get("pae"));
    const aligned = [summaries, locals, paeFiles].every((items) => items.length === structures.length);
    const abort = new AbortController(); let local = null; let matrix = null;
    const root = document.createElement("div"); root.className = "esmfold-result"; const style = document.createElement("style"); style.textContent = STYLE;
    const heading = document.createElement("h2"); heading.textContent = "ESMFold 2 prediction"; const intro = document.createElement("p"); intro.textContent = "Diffusion samples with model-native confidence on its persisted 0 to 1 scale."; root.append(style, heading, intro);
    const candidateSection = section("Structure samples", "Candidate order follows the runner's deterministic sample order."); const candidateHost = document.createElement("div"); candidateHost.className = "esmfold-candidates"; const actions = document.createElement("div"); actions.className = "esmfold-actions"; candidateSection.append(candidateHost, actions); root.appendChild(candidateSection);
    const columns = document.createElement("div"); columns.className = "esmfold-columns"; const metrics = section("Global confidence", "Values belong to the selected sample."); const metricHost = document.createElement("div"); metrics.appendChild(metricHost); const confidence = section("Local confidence", "Per-token pLDDT as persisted by ESMFold 2; higher is better."); const confidenceHost = document.createElement("div"); confidence.appendChild(confidenceHost); columns.append(metrics, confidence); root.appendChild(columns);
    const pae = section("Predicted aligned error", "Pairwise token error in angstroms; lower is better."); const figure = document.createElement("div"); figure.className = "esmfold-figure"; const canvas = document.createElement("canvas"); canvas.tabIndex = 0; canvas.setAttribute("role", "grid"); const readout = document.createElement("p"); readout.className = "matrix-readout"; readout.setAttribute("role", "status"); figure.appendChild(canvas); pae.append(figure, readout); root.appendChild(pae); host.replaceChildren(root);
    matrix = new Scientific.PairMatrix({ figure, canvas, readout, minimum: 0, unit: "angstrom", xTitle: "Aligned token", yTitle: "Scored token", legendTitle: "PAE", decimals: 1 });
    function clearCandidate(text) {
      actions.replaceChildren(); metricHost.replaceChildren(message(text)); confidenceHost.replaceChildren(); figure.hidden = true; readout.textContent = "";
      if (local) { local.destroy(); local = null; }
    }
    async function select(structure, index, request) {
      clearCandidate("Loading candidate evidence...");
      if (!aligned) { clearCandidate("Candidate evidence counts do not align."); return; }
      try {
        const signal = request.signal || abort.signal; const [summaryResponse, tokenProjection, confidenceProjection, paeProjection] = await Promise.all([
          response(summaries[index], signal),
          Scientific.loadNumericProjection(locals[index], { key: "token_index", signal }),
          Scientific.loadNumericProjection(locals[index], { key: "plddt", signal }),
          Scientific.loadNumericProjection(paeFiles[index], { key: "pae", signal }),
        ]);
        const summary = await summaryResponse.json(); if (!request.current()) return;
        const values = paeProjection.shape.length === 2 ? Array.from({ length: paeProjection.shape[0] }, (_, row) => paeProjection.values.slice(row * paeProjection.shape[1], (row + 1) * paeProjection.shape[1])) : null;
        if (!square(values)) throw new Error("The selected sample did not publish a square PAE matrix.");
        const open = document.createElement("button"); open.type = "button"; open.className = "btn btn-soft"; open.textContent = "Open selected structure"; open.addEventListener("click", () => context.services.openFile(structure)); actions.replaceChildren(open);
        new Scientific.ScalarMetricGrid(metricHost, [{ label: "Mean pLDDT", value: summary.mean_plddt, unit: "score", meaning: "Higher is better" }, { label: "pTM", value: summary.ptm, unit: "score", meaning: "Higher is better" }, { label: "ipTM", value: summary.iptm, unit: "score", meaning: "Higher is better" }]);
        local = new Scientific.LocalConfidenceSeries(confidenceHost, { series: [{ label: "pLDDT", values: confidenceProjection.values }], xValues: tokenProjection.values, xLabel: "Token index", yLabel: "pLDDT", unit: "score", direction: "higher is better", yMin: 0, yMax: 1 });
        figure.hidden = false; const labels = values.map((_, token) => String(token + 1)); matrix.setData({ values, xLabels: labels, yLabels: labels });
      } catch (error) { if (error.name !== "AbortError" && request.current()) clearCandidate(error.message || "ESMFold 2 evidence could not be loaded."); }
    }
    const selector = new Scientific.CandidateSelector(candidateHost, { items: structures, label: (_, index) => "Sample " + (index + 1), onSelect: select });
    if (structures.length) await selector.select(0); else candidateHost.replaceChildren(message("No structure sample was published."));
    return { destroy() { abort.abort(); selector.destroy(); if (local) local.destroy(); if (matrix) matrix.destroy(); } };
  },
};
