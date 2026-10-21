/* AlphaFold2 ranked structure confidence and optional PAE composition. */
/* SPDX-License-Identifier: GPL-3.0-only */

const STYLE = `
.af2-result{display:grid;gap:16px;min-width:0;color:var(--app-ink);font:14px/1.5 var(--font-sans)}
.af2-result h2,.af2-result h3,.af2-result p{margin:0}
.af2-head{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 18px}
.af2-head h2{font:500 26px var(--font-display);letter-spacing:-.5px;width:100%}
.af2-note{color:var(--app-muted);font-size:14px;line-height:1.7;max-width:78ch}
.af2-section{display:grid;gap:.55rem;min-width:0}
.af2-candidates,.af2-actions{display:flex;flex-wrap:wrap;gap:.45rem}
.af2-candidates button[aria-current="true"]{outline:2px solid var(--accent);outline-offset:2px}
.af2-hero{display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:18px;min-width:0;align-items:stretch}
.af2-stage{position:relative;min-width:0;height:600px;min-height:600px;border:1px solid var(--app-line);border-radius:8px;overflow:hidden;background:var(--app-stage)}
.af2-stage .storyboard-structure-panel{height:100%}
.af2-stage-label{position:absolute;z-index:4;top:10px;left:10px;max-width:calc(100% - 20px);padding:3px 8px;border:1px solid var(--app-line);border-radius:4px;background:var(--app-surface);color:var(--app-muted);font:12px var(--font-mono);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;pointer-events:none}
.af2-stage-unavailable{position:absolute;z-index:4;inset:0;display:grid;place-items:center;padding:24px;text-align:center;color:var(--app-muted);font-size:13px;line-height:1.6}
.af2-side{min-width:0;display:grid;gap:14px;align-content:start}
.af2-figure{position:relative;overflow:hidden;margin:0 auto}
.af2-figure canvas{display:block;max-width:100%}
.af2-figure .pair-matrix-label{position:absolute;color:var(--muted);font-size:11px}
.af2-figure .af3-label-x{transform:translateX(-50%)}
.af2-figure .af3-label-y{transform:translateY(-50%)}
.af2-figure .af3-title{color:var(--ink);font-size:12px}
.af2-figure .af3-title-y{transform:translate(-50%,-50%) rotate(-90deg);white-space:nowrap}
.af2-caveat{padding:10px 12px;border:1px solid var(--app-line);border-left:3px solid var(--app-plum);border-radius:4px;background:var(--app-soft);font-size:13px;line-height:1.6;color:var(--app-muted)}
@container(max-width: 860px){.af2-hero{grid-template-columns:minmax(0,1fr)}.af2-stage{height:420px;min-height:420px}}
`;

function list(value) { return Array.isArray(value) ? value : value ? [value] : []; }
function section(title, note) { const node = document.createElement("section"); node.className = "af2-section"; const heading = document.createElement("h3"); heading.textContent = title; node.appendChild(heading); if (note) { const text = document.createElement("p"); text.className = "scientific-note"; text.textContent = note; node.appendChild(text); } return node; }
function message(value) { const node = document.createElement("p"); node.className = "preview-message"; node.textContent = value; return node; }
function element(tag, className, text) { const node = document.createElement(tag); node.className = className; if (text != null) node.textContent = text; return node; }
async function json(url, signal) { const response = window.REvoDesignAuth ? await window.REvoDesignAuth.authFetch(url, { signal }) : await fetch(url, { credentials: "same-origin", signal }); if (!response.ok) throw new Error("AlphaFold2 evidence could not be loaded."); return response.json(); }
function rankOf(artifact, fallback) { const match = String(artifact.name || "").match(/ranked_(\d+)\.pdb$/); return match ? Number(match[1]) : fallback; }
function bySuffix(files, prefix, identity) { return files.find((file) => String(file.name || "").endsWith(prefix + identity + ".json")) || null; }
function square(value) { if (!value || value.shape.length !== 2 || value.shape[0] !== value.shape[1]) return null; return Array.from({ length: value.shape[0] }, (_, row) => value.values.slice(row * value.shape[1], (row + 1) * value.shape[1])); }
// The Task's declared `predicted_aligned_error` matrix and per-residue series
// views own their scale, axis labels, unit and direction; the module reads them
// instead of pinning a scientific range of its own.
function seriesMapping(views, id) { const view = list(views).find((item) => item.id === id); return view && view.mapping || {}; }

export default { async mount(host, context) {
  const S = window.REvoComputeScientific; if (!S) throw new Error("Scientific result components are unavailable.");
  const services = context.services || {};
  const structures = list(context.files.get("structures")); const confidences = list(context.files.get("confidences")); const paes = list(context.files.get("pae")); const rankingFile = list(context.files.get("ranking"))[0];
  let confidencePlot = null; let matrix = null; let stageGeneration = 0;
  const root = document.createElement("div"); root.className = "af2-result"; const style = document.createElement("style"); style.textContent = STYLE;
  const head = element("header", "af2-head"); head.append(element("h2", "", "AlphaFold2 prediction"), element("p", "af2-note", "Ranked AlphaFold2 models with the selected model's local confidence and predicted aligned error beside the structure."));
  // AlphaFold2 publishes no global scalar summary, so this page has no metric
  // strip: the ranked selector and the stage label name the published candidate.

  // The structure is the result: one persistent stage on the first screen with
  // the selected model's confidence evidence beside it.
  const hero = element("div", "af2-hero");
  const stage = element("section", "af2-stage"); stage.dataset.structureSlot = "true";
  const stageLabel = element("p", "af2-stage-label", "No model selected");
  const stageUnavailable = element("p", "af2-stage-unavailable", ""); stageUnavailable.hidden = true;
  stage.append(stageLabel, stageUnavailable);
  const side = element("aside", "af2-side"); side.setAttribute("aria-label", "Model confidence evidence");

  const candidates = section("Ranked models", "Candidate order follows AlphaFold's published ranking."); const candidateHost = element("div", "af2-candidates"); const actions = element("div", "af2-actions"); candidates.append(candidateHost, actions);
  const confidence = section("Local confidence"); const confidenceHost = element("div"); confidence.appendChild(confidenceHost);
  const pae = section("Predicted aligned error"); const figure = element("div", "af2-figure"); const canvas = document.createElement("canvas"); canvas.tabIndex = 0; canvas.setAttribute("role", "grid"); const readout = element("p", "matrix-readout"); readout.setAttribute("role", "status"); figure.appendChild(canvas); pae.append(figure, readout);
  side.append(candidates, confidence, pae); hero.append(stage, side);
  const caveat = element("p", "af2-caveat", "Per-residue pLDDT is on AlphaFold's persisted 0 to 100 scale; model confidence, not experimental validation. PAE is optional, in angstroms, and lower is better.");
  root.append(style, head, hero, caveat); host.replaceChildren(root);

  const paeMapping = seriesMapping(context.views, "predicted_aligned_error");
  const residueMapping = seriesMapping(context.views, "residue_confidence");
  matrix = new S.PairMatrix({ figure, canvas, readout, minimum: paeMapping.scale_min, maximum: paeMapping.scale_max, unit: paeMapping.unit || "angstrom", xTitle: paeMapping.x_label || "Aligned residue", yTitle: paeMapping.y_label || "Scored residue", legendTitle: "PAE", decimals: 1 });
  const ranking = await json(rankingFile.url); const order = Array.isArray(ranking.order) ? ranking.order : [];
  function clearCandidate(text) {
    actions.replaceChildren(); confidenceHost.replaceChildren(message(text)); figure.hidden = true; readout.textContent = "";
    if (confidencePlot) { confidencePlot.destroy(); confidencePlot = null; }
  }
  // The stage follows the selection; a failed mount says so and leaves every
  // download and the matrix working.
  async function showStructure(structure, request) {
    const current = ++stageGeneration;
    stageLabel.textContent = structure.name || "Selected model";
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
    const rank = rankOf(structure, index); const identity = order[rank]; const confidenceFile = identity == null ? null : bySuffix(confidences, "confidence_", identity); const paeFile = identity == null ? null : bySuffix(paes, "pae_", identity);
    if (!confidenceFile) { clearCandidate("Ranked confidence evidence is unavailable."); return; }
    try {
      const [confidenceValue, paeResult] = await Promise.all([
        json(confidenceFile.url, request.signal),
        paeFile && paeFile.ndarray_url ? S.loadNumericProjection(paeFile, { key: "0.predicted_aligned_error", signal: request.signal }).catch((error) => { if (error.name === "AbortError") throw error; return null; }) : null,
      ]); if (!request.current()) return;
      const values = square(paeResult); const open = document.createElement("button"); open.type = "button"; open.className = "btn btn-soft"; open.textContent = "Open selected structure"; open.addEventListener("click", () => context.services.openFile(structure)); actions.replaceChildren(open);
      confidencePlot = new S.LocalConfidenceSeries(confidenceHost, { series: [{ label: residueMapping.y_label || "pLDDT", values: confidenceValue.confidenceScore }], xValues: confidenceValue.residueNumber, xLabel: residueMapping.x_label || "Residue position", yLabel: residueMapping.y_label || "pLDDT", unit: residueMapping.unit, direction: residueMapping.direction === "higher" ? "higher is better" : residueMapping.direction === "lower" ? "lower is better" : "", yMin: residueMapping.y_min, yMax: residueMapping.y_max });
      if (!paeFile) { readout.textContent = "PAE was not published for this model."; return true; }
      if (!values) { readout.textContent = "PAE is unavailable or exceeds the bounded interactive limit."; return true; }
      figure.hidden = false; const labels = values.map((_, item) => String(item + 1)); matrix.setData({ values, xLabels: labels, yLabels: labels });
      return true;
    } catch (error) { if (error.name !== "AbortError" && request.current()) clearCandidate(error.message || "AlphaFold2 evidence could not be loaded."); }
  }
  const selector = new S.CandidateSelector(candidateHost, { items: structures, store: context.selection, label: (item, index) => "Rank " + rankOf(item, index), onSelect: select }); if (structures.length) await selector.select(0); else candidateHost.replaceChildren(message("No ranked structure was published."));
  return { destroy() { stageGeneration += 1; selector.destroy(); if (confidencePlot) confidencePlot.destroy(); if (matrix) matrix.destroy(); } };
} };
