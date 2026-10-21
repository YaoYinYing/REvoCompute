/* OpenDDE scientific result composition. */
/* SPDX-License-Identifier: GPL-3.0-only */

const MATRIX_TYPES = [
  { key: "token_pair_pae", label: "Predicted aligned error", short: "PAE", unit: "Å", direction: "Lower is better" },
  { key: "token_pair_pde", label: "Predicted distance error", short: "PDE", unit: "Å", direction: "Lower is better" },
  { key: "contact_probs", label: "Contact probability", short: "Contact probability", unit: "probability", direction: "Higher is better" },
];
const STYLE = `
.opendde-result{display:grid;gap:16px;min-width:0;color:var(--app-ink);font:14px/1.5 var(--font-sans)}
.opendde-result h2,.opendde-result h3,.opendde-result p{margin:0}
.opendde-head{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 18px}
.opendde-head h2{font:500 26px var(--font-display);letter-spacing:-.5px;width:100%}
.opendde-note{color:var(--app-muted);font-size:14px;line-height:1.7;max-width:78ch}
.opendde-section{display:grid;gap:.55rem;min-width:0}
.opendde-section[hidden]{display:none}
.opendde-candidates,.opendde-actions{display:flex;flex-wrap:wrap;gap:.45rem}
.opendde-candidates button[aria-current="true"]{outline:2px solid var(--accent);outline-offset:2px}
.opendde-hero{display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:18px;min-width:0;align-items:stretch}
.opendde-stage{position:relative;min-width:0;height:600px;min-height:600px;border:1px solid var(--app-line);border-radius:8px;overflow:hidden;background:var(--app-stage)}
.opendde-stage .storyboard-structure-panel{height:100%}
.opendde-stage-label{position:absolute;z-index:4;top:10px;left:10px;max-width:calc(100% - 20px);padding:3px 8px;border:1px solid var(--app-line);border-radius:4px;background:var(--app-surface);color:var(--app-muted);font:12px var(--font-mono);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;pointer-events:none}
.opendde-stage-unavailable{position:absolute;z-index:4;inset:0;display:grid;place-items:center;padding:24px;text-align:center;color:var(--app-muted);font-size:13px;line-height:1.6}
.opendde-side{min-width:0;display:grid;gap:14px;align-content:start}
.opendde-caveat{padding:10px 12px;border:1px solid var(--app-line);border-left:3px solid var(--app-plum);border-radius:4px;background:var(--app-soft);font-size:13px;line-height:1.6;color:var(--app-muted)}
@container(max-width: 860px){.opendde-hero{grid-template-columns:minmax(0,1fr)}.opendde-stage{height:420px;min-height:420px}}
`;

function list(value) { return Array.isArray(value) ? value : value ? [value] : []; }
function name(artifact) { return artifact.name || String(artifact.path || "").split("/").pop(); }
function label(artifact, index) { const sample = name(artifact).match(/_sample_(\d+)\.cif$/); return sample ? "Candidate " + (index + 1) + " - sample " + sample[1] : "Candidate " + (index + 1); }
function element(tag, className, text) { const node = document.createElement(tag); node.className = className; if (text != null) node.textContent = text; return node; }
function section(title, note) { const node = element("section", "opendde-section"); node.appendChild(element("h3", "", title)); if (note) node.appendChild(element("p", "scientific-note", note)); return node; }
function message(text) { return element("p", "preview-message", text); }
async function fetchSummary(artifact, signal) { const response = window.REvoDesignAuth ? await window.REvoDesignAuth.authFetch(artifact.url, { signal }) : await fetch(artifact.url, { credentials: "same-origin", signal }); if (!response.ok) throw new Error("The OpenDDE confidence summary could not be loaded."); return response.json(); }
function matrixRows(projection) { if (!projection || projection.shape.length !== 2) return null; const [rows, columns] = projection.shape; if (rows < 1 || columns !== rows) return null; return Array.from({ length: rows }, (_, row) => projection.values.slice(row * columns, (row + 1) * columns)); }

export default {
  async mount(host, context) {
    const Scientific = window.REvoComputeScientific;
    if (!Scientific || typeof Scientific.loadNumericProjection !== "function") throw new Error("Scientific result components are unavailable.");
    const services = context.services || {};
    const structures = list(context.files.get("structures")); const summaries = list(context.files.get("summaries")); const full = list(context.files.get("full_confidences"));
    const summariesAligned = summaries.length === structures.length; const fullAligned = full.length === structures.length;
    let generation = 0; let stageGeneration = 0; let confidencePlot = null; let pairMatrix = null;
    const root = element("div", "opendde-result"); const style = document.createElement("style"); style.textContent = STYLE;
    const head = element("header", "opendde-head"); head.append(element("h2", "", "OpenDDE prediction"), element("p", "opendde-note", "All-atom structure samples with the selected sample's confidence and pairwise error beside the structure."));
    // The selected sample's published scalars lead the page, before the stage.
    const metricHost = element("div", "opendde-strip");

    // The structure is the result: one persistent stage on the first screen
    // with the selected sample's confidence evidence beside it.
    const hero = element("div", "opendde-hero");
    const stage = element("section", "opendde-stage"); stage.dataset.structureSlot = "true"; stage.setAttribute("aria-label", "Selected structure");
    const stageLabel = element("p", "opendde-stage-label", "No sample selected");
    const stageUnavailable = element("p", "opendde-stage-unavailable", ""); stageUnavailable.hidden = true;
    stage.append(stageLabel, stageUnavailable);
    const side = element("aside", "opendde-side"); side.setAttribute("aria-label", "Sample confidence evidence");

    const candidates = section("Structure samples", "Selecting a sample updates its structure controls and every available confidence view."); const candidateHost = element("div", "opendde-candidates"); const actions = element("div", "opendde-actions"); candidates.append(candidateHost, actions);
    const local = section("Atom confidence", "OpenDDE atom pLDDT is shown on its published 0-1 scale."); const localHost = element("div", "metric-chart"); local.appendChild(localHost); local.hidden = true;
    const pairs = section("Pairwise confidence", null); pairs.hidden = true;
    const pairToolbar = element("div", "scientific-toolbar"); const pairLabel = element("label", "", "Matrix "); const pairSelect = document.createElement("select"); pairSelect.setAttribute("aria-label", "Pairwise confidence matrix"); pairLabel.appendChild(pairSelect); pairToolbar.appendChild(pairLabel); pairs.appendChild(pairToolbar);
    const pairWarning = element("p", "preview-message", ""); pairWarning.hidden = true; pairs.appendChild(pairWarning);
    const pairNote = element("p", "scientific-note", ""); pairs.appendChild(pairNote);
    const plot = element("div", "pair-matrix-plot"); const figure = element("div", "pair-matrix-figure"); const canvas = document.createElement("canvas"); canvas.className = "pair-matrix-canvas"; canvas.tabIndex = 0; canvas.setAttribute("role", "grid"); figure.appendChild(canvas); plot.appendChild(figure); pairs.appendChild(plot);
    const readout = element("p", "matrix-readout", ""); readout.setAttribute("role", "status"); pairs.appendChild(readout);
    side.append(candidates, pairs, local); hero.append(stage, side);
    const caveat = element("p", "opendde-caveat", "Published values are shown without client-side rescaling. pLDDT and pTM are model confidence estimates, not experimental validation.");
    root.append(style, head, metricHost, hero, caveat); host.replaceChildren(root);

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
    // A mount from a superseded sample is skipped rather than replacing the
    // structure the reader has just chosen.
    async function showStructure(structure, request) {
      const current = ++stageGeneration;
      stageLabel.textContent = name(structure) || "Selected sample";
      stageUnavailable.hidden = true;
      if (typeof services.openFile !== "function") { stageUnavailable.textContent = "The structure viewer is unavailable; the confidence evidence remains available."; stageUnavailable.hidden = false; return; }
      try { await services.openFile(structure); }
      catch (error) {
        if (error.name === "AbortError" || current !== stageGeneration || !request.current()) return;
        stageUnavailable.textContent = "The structure could not be shown: " + (error.message || "the viewer refused it") + ". The confidence evidence remains available.";
        stageUnavailable.hidden = false;
      }
    }
    async function select(structure, index, request) {
      const current = ++generation; const summary = summariesAligned ? summaries[index] : null; const fullArtifact = fullAligned ? full[index] : null;
      clearCandidate("Loading candidate confidence...");
      void showStructure(structure, request);
      if (!summary) { clearCandidate("No confidence summary matches this sample."); return; }
      try {
        const payload = await fetchSummary(summary, request.signal); const atomResult = await optionalProjection(fullArtifact, "atom_plddt", request.signal); const matrixValues = [];
        for (const type of MATRIX_TYPES) matrixValues.push(await optionalProjection(fullArtifact, type.key, request.signal));
        if (current !== generation || !request.current()) return;
        actions.replaceChildren(); const open = element("button", "btn btn-soft", "Open selected structure"); open.type = "button"; open.addEventListener("click", () => context.services.openFile(structure)); actions.appendChild(open); if (fullArtifact) { const download = element("button", "btn btn-soft", "Download full confidence"); download.type = "button"; download.addEventListener("click", () => context.services.downloadFile(fullArtifact)); actions.appendChild(download); }
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
    return { destroy() { generation += 1; stageGeneration += 1; selector.destroy(); if (confidencePlot) confidencePlot.destroy(); if (pairMatrix) pairMatrix.destroy(); } };
  },
};
