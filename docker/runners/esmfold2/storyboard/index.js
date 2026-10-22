/* ESMFold 2 scientific result composition. */
/* SPDX-License-Identifier: GPL-3.0-only */

const STYLE = `
.esmfold-result{display:grid;gap:16px;min-width:0;color:var(--app-ink);font:14px/1.5 var(--font-sans)}
.esmfold-result h2,.esmfold-result h3,.esmfold-result p{margin:0}
.esmfold-head{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 18px}
.esmfold-head h2{font:500 26px var(--font-display);letter-spacing:-.5px;width:100%}
.esmfold-note{color:var(--app-muted);font-size:14px;line-height:1.7;max-width:78ch}
.esmfold-section{display:grid;gap:.55rem;min-width:0}
.esmfold-candidates,.esmfold-actions{display:flex;flex-wrap:wrap;gap:.45rem}
.esmfold-candidates button[aria-current="true"]{outline:2px solid var(--accent);outline-offset:2px}
.esmfold-hero{display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:18px;min-width:0;align-items:stretch}
.esmfold-stage{position:relative;min-width:0;height:600px;min-height:600px;border:1px solid var(--app-line);border-radius:8px;overflow:hidden;background:var(--app-stage)}
.esmfold-stage .storyboard-structure-panel{height:100%}
.esmfold-stage-label{position:absolute;z-index:4;top:10px;left:10px;max-width:calc(100% - 20px);padding:3px 8px;border:1px solid var(--app-line);border-radius:4px;background:var(--app-surface);color:var(--app-muted);font:12px var(--font-mono);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;pointer-events:none}
.esmfold-stage-unavailable{position:absolute;z-index:4;inset:0;display:grid;place-items:center;padding:24px;text-align:center;color:var(--app-muted);font-size:13px;line-height:1.6}
.esmfold-side{min-width:0;display:grid;gap:14px;align-content:start}
.esmfold-figure{position:relative;overflow:hidden;margin:0 auto}
.esmfold-figure canvas{display:block;max-width:100%}
.esmfold-figure .pair-matrix-label{position:absolute;color:var(--muted);font-size:11px}
.esmfold-figure .af3-label-x{transform:translateX(-50%)}
.esmfold-figure .af3-label-y{transform:translateY(-50%)}
.esmfold-figure .af3-title{color:var(--ink);font-size:12px}
.esmfold-figure .af3-title-y{transform:translate(-50%,-50%) rotate(-90deg);white-space:nowrap}
.esmfold-caveat{padding:10px 12px;border:1px solid var(--app-line);border-left:3px solid var(--app-plum);border-radius:4px;background:var(--app-soft);font-size:13px;line-height:1.6;color:var(--app-muted)}
@container(max-width: 860px){.esmfold-hero{grid-template-columns:minmax(0,1fr)}.esmfold-stage{height:420px;min-height:420px}}
`;

function list(value) { return Array.isArray(value) ? value : value ? [value] : []; }
function element(tag, className, text) { const node = document.createElement(tag); node.className = className; if (text != null) node.textContent = text; return node; }
function section(title, note) { const node = element("section", "esmfold-section"); node.appendChild(element("h3", "", title)); if (note) node.appendChild(element("p", "scientific-note", note)); return node; }
function message(text) { return element("p", "preview-message", text); }
async function response(artifact, signal) { const value = window.REvoDesignAuth ? await window.REvoDesignAuth.authFetch(artifact.url, { signal }) : await fetch(artifact.url, { credentials: "same-origin", signal }); if (!value.ok) throw new Error("ESMFold 2 evidence could not be loaded."); return value; }
function square(values) { return Array.isArray(values) && values.length && values.every((row) => Array.isArray(row) && row.length === values.length); }
// The Task's declared series and matrix views own their labels, unit, range and
// direction; the module reads them instead of pinning a vocabulary of its own.
function viewMapping(views, id) { const view = list(views).find((item) => item.id === id); return view && view.mapping || {}; }
function seriesWording(direction) { return direction === 'higher' ? 'higher is better' : direction === 'lower' ? 'lower is better' : ''; }

export default {
  async mount(host, context) {
    const Scientific = window.REvoComputeScientific; if (!Scientific) throw new Error("Scientific result components are unavailable.");
    const services = context.services || {};
    const structures = list(context.files.get("structures")); const summaries = list(context.files.get("summaries")); const locals = list(context.files.get("local_confidence")); const paeFiles = list(context.files.get("pae"));
    const aligned = [summaries, locals, paeFiles].every((items) => items.length === structures.length);
    const abort = new AbortController(); let local = null; let matrix = null; let stageGeneration = 0;
    const root = element("div", "esmfold-result"); const style = document.createElement("style"); style.textContent = STYLE;
    const head = element("header", "esmfold-head"); head.append(element("h2", "", "ESMFold 2 prediction"), element("p", "esmfold-note", "Diffusion samples with model-native confidence on its persisted 0 to 1 scale."));
    // The selected sample's published scalars lead the page, before the stage.
    const metricHost = element("div", "esmfold-strip");

    // The structure is the result: one persistent stage on the first screen,
    // with the selected sample's confidence evidence beside it.
    const hero = element("div", "esmfold-hero");
    const stage = element("section", "esmfold-stage"); stage.dataset.structureSlot = "true"; stage.setAttribute("aria-label", "Selected structure");
    const stageLabel = element("p", "esmfold-stage-label", "No sample selected");
    const stageUnavailable = element("p", "esmfold-stage-unavailable", ""); stageUnavailable.hidden = true;
    stage.append(stageLabel, stageUnavailable);
    const side = element("aside", "esmfold-side"); side.setAttribute("aria-label", "Model confidence evidence");
    const candidateSection = section("Structure samples", "Candidate order follows the runner's deterministic sample order."); const candidateHost = element("div", "esmfold-candidates"); const actions = element("div", "esmfold-actions"); candidateSection.append(candidateHost, actions);
    const confidence = section("Local confidence", "Per-token pLDDT as persisted by ESMFold 2; higher is better."); const confidenceHost = element("div"); confidence.appendChild(confidenceHost);
    const pae = section("Predicted aligned error", "Pairwise token error in angstroms; lower is better."); const figure = element("div", "esmfold-figure"); const canvas = document.createElement("canvas"); canvas.tabIndex = 0; canvas.setAttribute("role", "grid"); const readout = element("p", "matrix-readout"); readout.setAttribute("role", "status"); figure.appendChild(canvas); pae.append(figure, readout);
    side.append(candidateSection, confidence, pae); hero.append(stage, side);
    const caveat = element("p", "esmfold-caveat", "Values belong to the selected sample; model confidence estimates, not experimental validation.");
    root.append(style, head, metricHost, hero, caveat); host.replaceChildren(root);
    const seriesMapping = viewMapping(context.views, 'residue_confidence');
    const paeMapping = viewMapping(context.views, 'predicted_aligned_error');
    matrix = new Scientific.PairMatrix({ figure, canvas, readout, minimum: paeMapping.scale_min, unit: paeMapping.unit || 'angstrom', xTitle: paeMapping.x_label || 'Aligned token', yTitle: paeMapping.y_label || 'Scored token', legendTitle: 'PAE', decimals: 1 });

    function clearCandidate(text) {
      actions.replaceChildren(); metricHost.replaceChildren(message(text)); confidenceHost.replaceChildren(); figure.hidden = true; readout.textContent = "";
      if (local) { local.destroy(); local = null; }
    }
    // A mount from a superseded sample is skipped rather than replacing the
    // structure the reader has just chosen.
    async function showStructure(structure, request) {
      const current = ++stageGeneration;
      stageLabel.textContent = structure.name || "Selected sample";
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
      clearCandidate("Loading candidate evidence...");
      void showStructure(structure, request);
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
        local = new Scientific.LocalConfidenceSeries(confidenceHost, { series: [{ label: seriesMapping.y_label || 'pLDDT', values: confidenceProjection.values }], xValues: tokenProjection.values, xLabel: seriesMapping.x_label || 'Token index', yLabel: seriesMapping.y_label || 'pLDDT', unit: seriesMapping.unit, direction: seriesWording(seriesMapping.direction), yMin: seriesMapping.y_min, yMax: seriesMapping.y_max });
        figure.hidden = false; const labels = values.map((_, token) => String(token + 1)); matrix.setData({ values, xLabels: labels, yLabels: labels });
        return true;
      } catch (error) { if (error.name !== "AbortError" && request.current()) clearCandidate(error.message || "ESMFold 2 evidence could not be loaded."); }
    }
    const selector = new Scientific.CandidateSelector(candidateHost, { items: structures, store: context.selection, label: (_, index) => "Sample " + (index + 1), onSelect: select });
    if (structures.length) await selector.select(0); else candidateHost.replaceChildren(message("No structure sample was published."));
    return { destroy() { stageGeneration += 1; abort.abort(); selector.destroy(); if (local) local.destroy(); if (matrix) matrix.destroy(); } };
  },
};
