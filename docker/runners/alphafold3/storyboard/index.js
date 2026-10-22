/* AlphaFold 3 scientific result composition. */
/* SPDX-License-Identifier: GPL-3.0-only */

const RAMP_LIGHT = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"];
const RAMP_DARK = ["#184f95", "#256abf", "#3987e5", "#6da7ec", "#9ec5f4", "#b7d3f6", "#cde2fb"];
const PLOT = { width: 800, height: 600, left: 78, top: 30, size: 500, legendX: 604, legendWidth: 24 };
const STYLE = `
.af3-result{display:grid;gap:1.1rem;min-width:0;color:var(--app-ink);font:14px/1.5 var(--font-sans)}
.af3-result h2,.af3-result h3,.af3-result p{margin:0}
.af3-head{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 18px}
.af3-head h2{font:500 26px var(--font-display);letter-spacing:-.5px;width:100%}
.af3-note{color:var(--app-muted);font-size:14px;line-height:1.7;max-width:78ch}
.af3-section{display:grid;gap:.5rem;min-width:0}
.af3-actions{display:flex;flex-wrap:wrap;gap:.5rem}
.af3-hero{display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:18px;min-width:0;align-items:stretch}
.af3-stage{position:relative;min-width:0;height:600px;min-height:600px;border:1px solid var(--app-line);border-radius:8px;overflow:hidden;background:var(--app-stage)}
.af3-stage-label{position:absolute;z-index:4;top:10px;left:10px;max-width:calc(100% - 20px);padding:3px 8px;border:1px solid var(--app-line);border-radius:4px;background:var(--app-surface);color:var(--app-muted);font:12px var(--font-mono);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;pointer-events:none}
.af3-stage-unavailable{position:absolute;z-index:4;inset:0;display:grid;place-items:center;padding:24px;text-align:center;color:var(--app-muted);font-size:13px;line-height:1.6}
.af3-stage .storyboard-structure-panel{height:100%}
.af3-side{min-width:0;display:grid;gap:14px;align-content:start}
.af3-side .af3-figure{margin:0 auto}
.af3-caveat{padding:10px 12px;border:1px solid var(--app-line);border-left:3px solid var(--app-plum);border-radius:4px;background:var(--app-soft);font-size:13px;line-height:1.6;color:var(--app-muted)}
@container(max-width: 860px){.af3-hero{grid-template-columns:minmax(0,1fr)}.af3-stage{height:420px;min-height:420px}}
`;

// The Task's declared `confidence_summary` scalar-summary view is the only
// source of the global-confidence vocabulary shown here: fields, labels, units,
// and direction come from the declaration, not from a copy in this module.
function declaredScalars(views) { const view = list(views).find((item) => item.id === 'confidence_summary'); const fields = view && view.mapping && view.mapping.fields; return Array.isArray(fields) ? fields : []; }
function directionWording(direction) { return direction === 'higher' ? 'Higher is better' : direction === 'lower' ? 'Lower is better' : ''; }
function list(value) { return Array.isArray(value) ? value : value ? [value] : []; }
function name(artifact) { return artifact && (artifact.name || String(artifact.path || "").split("/").pop()); }
function key(artifact, suffix) { const value = name(artifact); return value && value.endsWith(suffix) ? value.slice(0, -suffix.length) : null; }
function section(title, note) { const node = document.createElement("section"); node.className = "af3-section"; const heading = document.createElement("h3"); heading.textContent = title; node.appendChild(heading); if (note) { const text = document.createElement("p"); text.className = "scientific-note"; text.textContent = note; node.appendChild(text); } return node; }
function message(text) { const node = document.createElement("p"); node.className = "preview-message"; node.textContent = text; return node; }
function themeName() { const value = document.documentElement.getAttribute("data-theme"); return value === "dark" || value === "light" ? value : window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"; }
function matrixRows(projection) { if (!projection || projection.shape.length !== 2) return null; const [rows, columns] = projection.shape; if (rows < 1 || columns !== rows) return null; return Array.from({ length: rows }, (_, row) => projection.values.slice(row * columns, (row + 1) * columns)); }

export default {
  async mount(host, context) {
    const Scientific = window.REvoComputeScientific;
    if (!Scientific || typeof Scientific.loadProjection !== "function") throw new Error("Shared scientific visualizations are unavailable.");
    const structures = list(context.files.get("structures"));
    const scalars = declaredScalars(context.views);
    const summaryByKey = new Map(list(context.files.get("summaries")).map((item) => [key(item, "_summary_confidences.json"), item]));
    const confidenceByKey = new Map(list(context.files.get("confidences")).filter((item) => !name(item).endsWith("_summary_confidences.json")).map((item) => [key(item, "_confidences.json"), item]));
    const services = context.services || {};
    let generation = 0; let stageGeneration = 0; let matrix = null;

    const root = document.createElement("div"); root.className = "af3-result"; const style = document.createElement("style"); style.textContent = STYLE;
    const head = document.createElement("header"); head.className = "af3-head"; head.append(
      element("h2", "", "AlphaFold 3 prediction"),
      element("p", "af3-note", "Candidate-matched structures with the selected model's confidence evidence beside it."),
    );
    // The selected candidate's published scalars lead the page as a compact
    // strip, so the stage and its evidence stay on the first screen.
    const metricHost = document.createElement('div'); metricHost.className = 'af3-strip';

    // The structure is the result: one persistent stage on the first screen,
    // with the selected candidate's confidence evidence beside it.
    const hero = document.createElement("div"); hero.className = "af3-hero";
    const stage = document.createElement("section"); stage.className = "af3-stage"; stage.dataset.structureSlot = "true";
    const stageLabel = element("p", "af3-stage-label", "No candidate selected");
    const stageUnavailable = element("p", "af3-stage-unavailable", "");
    stageUnavailable.hidden = true; stage.append(stageLabel, stageUnavailable);
    const side = document.createElement("aside"); side.className = "af3-side"; side.setAttribute("aria-label", "Candidate confidence evidence");

    const candidates = section("Predicted structures", "Selecting a candidate updates the structure and every confidence view as one generation.");
    const candidateHost = document.createElement("div"); candidates.appendChild(candidateHost); const actions = document.createElement("div"); actions.className = "af3-actions"; candidates.appendChild(actions);
    const pae = section("Expected position error", null); const note = document.createElement("p"); note.className = "scientific-note"; note.id = "af3-pae-note"; note.textContent = "Select a candidate to load bounded PAE evidence."; pae.appendChild(note);
    const toolbar = document.createElement("div"); toolbar.className = "scientific-toolbar"; const borders = document.createElement("button"); borders.type = "button"; borders.className = "btn btn-soft"; borders.textContent = "Show chain borders"; borders.disabled = true; borders.setAttribute("aria-pressed", "false"); toolbar.appendChild(borders); pae.appendChild(toolbar);
    const plot = document.createElement("div"); plot.className = "af3-plot pair-matrix-plot"; const figure = document.createElement("div"); figure.className = "af3-figure pair-matrix-figure"; const canvas = document.createElement("canvas"); canvas.className = "af3-canvas pair-matrix-canvas"; canvas.width = PLOT.width; canvas.height = PLOT.height; canvas.tabIndex = 0; canvas.setAttribute("role", "grid"); canvas.setAttribute("aria-describedby", note.id); figure.appendChild(canvas); plot.appendChild(figure); pae.appendChild(plot); const readout = document.createElement("p"); readout.className = "matrix-readout"; readout.setAttribute("role", "status"); pae.appendChild(readout);
    side.append(candidates, pae); hero.append(stage, side);
    const caveat = element("p", "af3-caveat", "Published values are shown without client-side rescaling. pTM, ipTM, and pLDDT are model confidence estimates, not experimental validation.");
    root.append(style, head, metricHost, hero, caveat); host.replaceChildren(root);

    let residueIds = [], residueLabels = [], chainIds = [], showBorders = false;
    function element(tag, className, text) { const node = document.createElement(tag); node.className = className; if (text != null) node.textContent = text; return node; }

    // The stage follows the selection: a late mount from a superseded candidate
    // is skipped rather than replacing the freshly chosen structure.
    async function showStructure(structure, request) {
      const current = ++stageGeneration;
      stageLabel.textContent = name(structure) || "Selected structure";
      stageUnavailable.hidden = true;
      if (typeof services.openFile !== "function") { stageUnavailable.textContent = "The structure viewer is unavailable; the confidence evidence remains available."; stageUnavailable.hidden = false; return; }
      try { await services.openFile(structure); }
      catch (error) {
        if (error.name === "AbortError" || current !== stageGeneration || !request.current()) return;
        stageUnavailable.textContent = "The structure could not be shown: " + (error.message || "the viewer refused it") + ". The confidence evidence remains available.";
        stageUnavailable.hidden = false;
      }
    }
    function clearCandidate(text) { actions.replaceChildren(); metricHost.replaceChildren(); residueIds = []; residueLabels = []; chainIds = []; borders.disabled = true; readout.textContent = ""; plot.hidden = true; note.textContent = text; if (matrix) { matrix.destroy(); matrix = null; } }
    borders.addEventListener("click", () => { showBorders = !showBorders; borders.setAttribute("aria-pressed", String(showBorders)); if (matrix) matrix.setBorders(showBorders); });
    function scalarValue(projection) { return projection && projection.shape.length === 0 && projection.values.length === 1 ? projection.values[0] : null; }
    async function select(structure, _index, request) {
      const current = ++generation; clearCandidate("Loading candidate confidence...");
      await showStructure(structure, request);
      const identity = key(structure, "_model.cif"), summary = summaryByKey.get(identity), confidence = confidenceByKey.get(identity);
      if (!identity || !confidence) { clearCandidate("No exact confidence record matches this structure candidate."); return; }
      try {
        const [scalarResults, required] = await Promise.all([
          summary && scalars.length ? Promise.allSettled(scalars.map((field) => Scientific.loadNumericProjection(summary, { key: field.path, signal: request.signal }))) : Promise.resolve([]),
          Promise.all([
          Scientific.loadNumericProjection(confidence, { key: "pae", signal: request.signal }),
          Scientific.loadNumericProjection(confidence, { key: "token_res_ids", signal: request.signal }),
          Scientific.loadProjection(confidence, { key: "token_chain_ids", kind: "categorical", signal: request.signal }),
          ]),
        ]);
        const [paeProjection, residueProjection, chainProjection] = required;
        if (current !== generation || !request.current()) return;
        const values = matrixRows(paeProjection); if (!values) throw new Error("The confidence record does not contain a PAE matrix.");
        residueIds = residueProjection.shape.length === 1 ? residueProjection.values : []; chainIds = chainProjection.shape.length === 1 ? chainProjection.values : [];
        if (residueIds.length !== values.length || chainIds.length !== values.length) throw new Error("Candidate labels do not match the PAE dimensions.");
        residueLabels = residueIds.map((value) => typeof value === "number" && Number.isFinite(value) ? String(value) : "N/A");
        const scalarMetrics = scalars.flatMap((field, index) => {
          const result = scalarResults[index];
          const value = result && result.status === "fulfilled" ? scalarValue(result.value) : null;
          // A declared nullable field that this candidate does not publish renders
          // as N/A, the same way the declared scalar-summary view renders it.
          if (value == null && !field.nullable) return [];
          return [{ label: field.label, value, unit: field.unit, meaning: directionWording(field.direction), nullable: Boolean(field.nullable) }];
        });
        if (scalarMetrics.length) new Scientific.ScalarMetricGrid(metricHost, scalarMetrics);
        else metricHost.replaceChildren(message(summary && scalars.length ? "This candidate did not publish global confidence scalars." : "The Task declared no global confidence scalars."));
        const open = document.createElement("button"); open.type = "button"; open.className = "btn btn-soft"; open.textContent = "Open selected structure"; open.addEventListener("click", () => context.services.openFile(structure)); actions.replaceChildren(open);
        plot.hidden = false;
        matrix = new Scientific.PairMatrix({ figure, canvas, readout, observe: plot, geometry: PLOT, minimum: 0, decimals: 1, ticks: 5, xTitle: "Aligned residue", yTitle: "Scored residue", legendTitle: "PAE (Å)", unit: "Å", ramp: () => themeName() === "dark" ? RAMP_DARK : RAMP_LIGHT, formatReadout: ({ x, y, value }) => `Aligned residue ${residueLabels[x]} (chain ${chainIds[x]}) · Scored residue ${residueLabels[y]} (chain ${chainIds[y]}) · ${Number.isFinite(value) ? value.toFixed(1) : "N/A"} Å`, onSelect: ({ x, y }) => { const rawResidue = residueIds[x]; const residue = typeof rawResidue === "number" && Number.isFinite(rawResidue) ? rawResidue : null; const chain = String(chainIds[x] || ""); context.selection.set({ token: residue, entityA: chain || null, entityB: String(chainIds[y] || "") || null }, matrix); if (chain && residue != null) context.services.focusStructure?.({ chain, residue, numbering: "label_seq_id" }); } });
        matrix.setData({ values, xLabels: residueLabels, yLabels: residueLabels, xGroups: chainIds, yGroups: chainIds }); matrix.setBorders(showBorders); borders.disabled = false;
        note.textContent = `PAE (Å): ${values.length} × ${values[0].length} scored and aligned residues across ${new Set(chainIds).size} chains. Lower is better.`;
        return true;
      } catch (error) { if (error.name !== "AbortError" && request.current()) clearCandidate(error.message || "Candidate confidence could not be loaded."); }
    }
    const unsubscribe = context.selection?.subscribe?.((state, source) => {
      if (!matrix || source === matrix || state.token == null) return;
      const index = residueIds.findIndex((residue, offset) => residue === state.token && (!state.entityA || chainIds[offset] === state.entityA));
      if (index >= 0) matrix.setSelection(index);
    }) || (() => {});
    const selector = new Scientific.CandidateSelector(candidateHost, { items: structures, store: context.selection, label: (item) => name(item).replace(/_model\.cif$/, ""), onSelect: select });
    if (structures.length) await selector.select(0); else clearCandidate("No structure candidate was published.");
    return { destroy() { generation += 1; stageGeneration += 1; unsubscribe(); selector.destroy(); if (matrix) matrix.destroy(); } };
  },
};
