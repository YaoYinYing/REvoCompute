/* ColabFold AlphaFold2 scientific result composition. */
/* SPDX-License-Identifier: GPL-3.0-only */

const STYLE = `
.colabfold-result { display: grid; gap: 16px; min-width: 0; color: var(--app-ink); font: 14px/1.5 var(--font-sans); }
.colabfold-result h2, .colabfold-result h3 { margin: 0; }
.colabfold-result p { margin: 0; }
.colabfold-head { display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px 18px; }
.colabfold-head h2 { width: 100%; font: 500 26px var(--font-display); letter-spacing: -.5px; }
.colabfold-note { max-width: 78ch; color: var(--app-muted); font-size: 14px; line-height: 1.7; }
.colabfold-section { display: grid; gap: 0.55rem; min-width: 0; }
.colabfold-candidates, .colabfold-actions { display: flex; flex-wrap: wrap; gap: 0.45rem; }
.colabfold-candidates button[aria-current="true"] { outline: 2px solid var(--accent); outline-offset: 2px; }
.colabfold-hero { display: grid; grid-template-columns: minmax(0, 1fr) 340px; gap: 18px; min-width: 0; align-items: stretch; }
.colabfold-stage { position: relative; min-width: 0; height: 600px; min-height: 600px; border: 1px solid var(--app-line); border-radius: 8px; overflow: hidden; background: var(--app-stage); }
.colabfold-stage .storyboard-structure-panel { height: 100%; }
.colabfold-stage-label { position: absolute; z-index: 4; top: 10px; left: 10px; max-width: calc(100% - 20px); padding: 3px 8px; border: 1px solid var(--app-line); border-radius: 4px; background: var(--app-surface); color: var(--app-muted); font: 12px var(--font-mono); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; pointer-events: none; }
.colabfold-stage-unavailable { position: absolute; z-index: 4; inset: 0; display: grid; place-items: center; padding: 24px; text-align: center; color: var(--app-muted); font-size: 13px; line-height: 1.6; }
.colabfold-side { display: grid; gap: 14px; min-width: 0; align-content: start; }
.colabfold-columns { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 26rem), 1fr)); gap: 1rem; }
.colabfold-figure { position: relative; overflow: hidden; margin: 0 auto; }
.colabfold-figure canvas { display: block; max-width: 100%; }
.colabfold-figure .pair-matrix-label { position: absolute; color: var(--muted); font-size: 11px; }
.colabfold-figure .af3-label-x { transform: translateX(-50%); }
.colabfold-figure .af3-label-y { transform: translateY(-50%); }
.colabfold-figure .af3-title { color: var(--ink); font-size: 12px; }
.colabfold-figure .af3-title-y { transform: translate(-50%, -50%) rotate(-90deg); white-space: nowrap; }
.colabfold-caveat { padding: 10px 12px; border: 1px solid var(--app-line); border-left: 3px solid var(--app-plum); border-radius: 4px; background: var(--app-soft); color: var(--app-muted); font-size: 13px; line-height: 1.6; }
@container(max-width: 860px) { .colabfold-hero { grid-template-columns: minmax(0, 1fr); } .colabfold-stage { height: 420px; min-height: 420px; } }
`;

function list(value) { return Array.isArray(value) ? value : value ? [value] : []; }
function name(artifact) { return artifact.name || String(artifact.path || "").split("/").pop(); }
function rank(artifact) { const match = name(artifact).match(/_rank_(\d+)_/); return match ? Number(match[1]) : null; }
function element(tag, className, text) { const node = document.createElement(tag); node.className = className; if (text != null) node.textContent = text; return node; }
function section(title, note) {
  const node = element("section", "colabfold-section");
  node.appendChild(element("h3", "", title));
  if (note) node.appendChild(element("p", "scientific-note", note));
  return node;
}
function message(text) { return element("p", "preview-message", text); }
async function fetchText(artifact, signal) {
  const response = window.REvoDesignAuth
    ? await window.REvoDesignAuth.authFetch(artifact.url, { signal })
    : await fetch(artifact.url, { credentials: "same-origin", signal });
  if (!response.ok) throw new Error("The ColabFold artifact could not be loaded.");
  return response.text();
}
async function fetchJson(artifact, signal) { return JSON.parse(await fetchText(artifact, signal)); }
function scalar(projection) { return projection && projection.shape.length === 0 && projection.values.length === 1 ? projection.values[0] : null; }
function matrixRows(projection) { if (!projection || projection.shape.length !== 2) return null; const [rows, columns] = projection.shape; if (rows < 1 || columns !== rows) return null; return Array.from({ length: rows }, (_, row) => projection.values.slice(row * columns, (row + 1) * columns)); }
// The Task's declared views own every label, unit, direction, and scale; the
// module reads them instead of pinning a vocabulary of its own.
function viewMapping(views, id) { const view = list(views).find((item) => item.id === id); return view && view.mapping || {}; }
function declaredFields(views, id) { const fields = viewMapping(views, id).fields; return Array.isArray(fields) ? fields : []; }
function directionWording(direction) { return direction === "higher" ? "Higher is better" : direction === "lower" ? "Lower is better" : ""; }
function seriesWording(direction) { return direction === "higher" ? "higher is better" : direction === "lower" ? "lower is better" : ""; }
function preferredStructures(artifacts) {
  const byRank = new Map();
  artifacts.forEach((artifact) => {
    const key = rank(artifact); if (key == null) return;
    const current = byRank.get(key);
    if (!current || (/_relaxed_rank_/.test(name(artifact)) && !/_relaxed_rank_/.test(name(current)))) byRank.set(key, artifact);
  });
  return Array.from(byRank.entries()).sort((a, b) => a[0] - b[0]).map((entry) => entry[1]);
}
function entityRows(a3m) {
  const first = String(a3m).split(/\r?\n/, 1)[0];
  const match = first.match(/^#([0-9,]+)\t([0-9,]+)/); if (!match) return [];
  const lengths = match[1].split(",").map(Number); const copies = match[2].split(",").map(Number);
  return lengths.map((length, index) => ["Entity " + (index + 1), String(length), String(copies[index] == null ? 1 : copies[index])]);
}

export default {
  async mount(host, context) {
    const Scientific = window.REvoComputeScientific;
    if (!Scientific) throw new Error("Scientific result components are unavailable.");
    const services = context.services || {};
    const structures = preferredStructures(list(context.files.get("structures")));
    const scores = list(context.files.get("scores"));
    const alignment = list(context.files.get("alignment"))[0];
    const interfaceArtifact = list(context.files.get("interface_scores"))[0];
    const scoreByRank = new Map(scores.map((artifact) => [rank(artifact), artifact]));
    const abort = new AbortController(); let generation = 0; let stageGeneration = 0; let localSeries = null; let matrix = null;

    const root = element("div", "colabfold-result");
    const style = document.createElement("style"); style.textContent = STYLE;
    const head = element("header", "colabfold-head");
    head.append(element("h2", "", "ColabFold prediction"), element("p", "colabfold-note", "Ranked AlphaFold2 models with the selected model's confidence and predicted aligned error beside the structure."));
    // The selected model's published scalars lead the page, before the stage.
    const metricHost = element("div", "colabfold-strip");

    // The structure is the result: one persistent stage on the first screen,
    // with the selected ranked model's evidence beside it.
    const hero = element("div", "colabfold-hero");
    const stage = element("section", "colabfold-stage"); stage.dataset.structureSlot = "true"; stage.setAttribute("aria-label", "Selected structure");
    const stageLabel = element("p", "colabfold-stage-label", "No ranked model selected");
    const stageUnavailable = element("p", "colabfold-stage-unavailable", ""); stageUnavailable.hidden = true;
    stage.append(stageLabel, stageUnavailable);
    const side = element("aside", "colabfold-side"); side.setAttribute("aria-label", "Model confidence evidence");
    const candidates = section("Ranked models", "A relaxed model is preferred when ColabFold published both relaxed and unrelaxed files for the same rank.");
    const candidateHost = element("div", "colabfold-candidates"); const actions = element("div", "colabfold-actions"); candidates.append(candidateHost, actions);
    const local = section("Local confidence"); const localHost = element("div"); local.appendChild(localHost);
    const pae = section("Predicted aligned error", "Lower values indicate greater confidence in relative residue placement.");
    const figure = element("div", "colabfold-figure");
    const canvas = document.createElement("canvas"); canvas.tabIndex = 0; canvas.setAttribute("role", "grid");
    const readout = element("p", "matrix-readout"); readout.setAttribute("role", "status");
    figure.appendChild(canvas); pae.append(figure, readout);
    side.append(candidates, local, pae); hero.append(stage, side);

    const caveat = element("p", "colabfold-caveat", "Published values are shown without client-side rescaling. pTM and the interface scores are model confidence estimates, not experimental validation.");
    const evidence = element("div", "colabfold-columns");
    const coverage = section("Alignment coverage", "The published A3M supplied to ColabFold model inference."); const coverageHost = element("div"); coverage.appendChild(coverageHost);
    const entities = section("Entities", "Lengths and copy counts declared by the ColabFold A3M header."); const entityHost = element("div"); entities.appendChild(entityHost);
    evidence.append(coverage, entities);
    root.append(style, head, metricHost, hero, caveat, evidence); host.replaceChildren(root);

    let residueFocusAvailable = false;
    const views = list(context.views);
    const paeMapping = viewMapping(views, "predicted_aligned_error");
    const residueMapping = viewMapping(views, "residue_confidence");
    const globalFields = declaredFields(views, "global_confidence");
    const interfaceFields = declaredFields(views, "interface_confidence");
    matrix = new Scientific.PairMatrix({ figure, canvas, readout, minimum: paeMapping.scale_min, maximum: paeMapping.scale_max, unit: paeMapping.unit || "Å", xTitle: paeMapping.x_label || "Aligned residue", yTitle: paeMapping.y_label || "Scored residue", legendTitle: "PAE (Å)", decimals: 1, onSelect: ({ x }) => { const residue = x + 1; context.selection.set({ token: residue }, matrix); if (residueFocusAvailable) context.services.focusStructure?.({ residue, numbering: "label_seq_id" }); } });
    const [a3m, interfacePayload] = await Promise.all([
      fetchText(alignment, abort.signal),
      interfaceArtifact ? fetchJson(interfaceArtifact, abort.signal).catch(() => null) : Promise.resolve(null),
    ]);
    if (abort.signal.aborted) return { destroy() {} };
    new Scientific.AlignmentCoverage(coverageHost, a3m, { title: "ColabFold alignment coverage", maxRows: 5000 });
    const rows = entityRows(a3m);
    residueFocusAvailable = rows.length === 1 && Number(rows[0][2]) === 1;
    if (rows.length) new Scientific.EntitySummaryTable(entityHost, { columns: ["Entity", "Length", "Copies"], rows });
    else entityHost.replaceChildren(message("This A3M does not publish a ColabFold entity header."));

    function clearCandidate(text) {
      actions.replaceChildren(); metricHost.replaceChildren(message(text)); localHost.replaceChildren(); figure.hidden = true; readout.textContent = "";
      if (localSeries) { localSeries.destroy(); localSeries = null; }
    }
    // A mount from a superseded candidate is skipped rather than replacing the
    // structure the reader has just chosen.
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
    async function select(structure, _index, request) {
      const current = ++generation; const selectedRank = rank(structure); const scoreArtifact = scoreByRank.get(selectedRank);
      clearCandidate("Loading candidate confidence...");
      void showStructure(structure, request);
      if (!scoreArtifact || !scoreArtifact.ndarray_url) { clearCandidate("No bounded score record matches this ranked model."); return; }
      try {
        const results = await Promise.allSettled([
          Scientific.loadNumericProjection(scoreArtifact, { key: "plddt", signal: request.signal }),
          Scientific.loadNumericProjection(scoreArtifact, { key: "pae", signal: request.signal }),
          ...globalFields.map((field) => Scientific.loadNumericProjection(scoreArtifact, { key: field.path, signal: request.signal })),
        ]);
        if (current !== generation || !request.current()) return;
        const available = results.map((result) => result.status === "fulfilled" ? result.value : null);
        const [plddtProjection, paeProjection, ...globalValues] = available;
        const plddt = plddtProjection && plddtProjection.shape.length === 1 ? plddtProjection.values : [];
        const finite = plddt.filter(Number.isFinite);
        const publishedInterface = interfacePayload && interfacePayload.scores_file === name(scoreArtifact) ? interfacePayload : null;
        // Only what the Task declares is shown: global confidence from
        // `global_confidence`, interface confidence from `interface_confidence`.
        const scalarMetrics = [
          ...globalFields.map((field, index) => ({ label: field.label, value: scalar(globalValues[index]), unit: field.unit, meaning: directionWording(field.direction) })),
          ...interfaceFields.map((field) => ({ label: field.label, value: publishedInterface ? publishedInterface[field.path] : null, unit: field.unit, meaning: directionWording(field.direction) })),
        ].filter((metric) => metric.value != null);
        if (scalarMetrics.length) new Scientific.ScalarMetricGrid(metricHost, scalarMetrics);
        else metricHost.replaceChildren(message("This model did not publish global confidence metrics."));
        localHost.replaceChildren();
        if (finite.length) localSeries = new Scientific.LocalConfidenceSeries(localHost, { series: [{ label: residueMapping.y_label || "pLDDT", values: plddt }], xValues: plddt.map((_, index) => index + 1), xLabel: residueMapping.x_label || "Residue position", yLabel: residueMapping.y_label || "pLDDT", unit: residueMapping.unit, direction: seriesWording(residueMapping.direction), yMin: residueMapping.y_min, yMax: residueMapping.y_max, onSelect: ({ x }) => { context.selection.set({ token: x }, localSeries); if (residueFocusAvailable) context.services.focusStructure?.({ residue: x, numbering: "label_seq_id" }); } });
        else localHost.replaceChildren(message("This model did not publish local pLDDT."));
        const values = matrixRows(paeProjection);
        if (values) { figure.hidden = false; matrix.setData({ values, xLabels: values.map((_, index) => String(index + 1)), yLabels: values.map((_, index) => String(index + 1)) }); }
        else { figure.hidden = true; readout.textContent = "This model did not publish PAE."; }
        const open = document.createElement("button"); open.type = "button"; open.className = "btn btn-soft btn-small"; open.textContent = "Open selected structure"; open.addEventListener("click", () => context.services.openFile(structure)); actions.replaceChildren(open);
        return true;
      } catch (error) { if (error.name !== "AbortError" && request.current()) clearCandidate(error.message || "Candidate confidence could not be loaded."); }
    }
    const unsubscribe = context.selection?.subscribe?.((state, source) => {
      if (!residueFocusAvailable || state.token == null) return;
      if (source !== matrix) matrix.setSelection(state.token - 1);
      if (localSeries && source !== localSeries) localSeries.setSelection(state.token);
    }) || (() => {});
    const selector = new Scientific.CandidateSelector(candidateHost, { items: structures, store: context.selection, label: (item) => "Rank " + rank(item), onSelect: select });
    if (structures.length) await selector.select(0); else candidateHost.replaceChildren(message("No ranked model was published."));
    return { destroy() { generation += 1; stageGeneration += 1; abort.abort(); unsubscribe(); selector.destroy(); if (localSeries) localSeries.destroy(); if (matrix) matrix.destroy(); } };
  },
};
