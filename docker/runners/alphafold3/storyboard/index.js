/* AlphaFold 3 scientific result composition. */
/* SPDX-License-Identifier: GPL-3.0-only */

const RAMP_LIGHT = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"];
const RAMP_DARK = ["#184f95", "#256abf", "#3987e5", "#6da7ec", "#9ec5f4", "#b7d3f6", "#cde2fb"];
const PLOT = { width: 800, height: 600, left: 78, top: 30, size: 500, legendX: 604, legendWidth: 24 };
const SCALARS = [["ptm", "pTM", "score"], ["iptm", "ipTM", "score"], ["ranking_score", "Ranking score", "score"], ["fraction_disordered", "Fraction disordered", "fraction"]];
const STYLE = `.af3-result{display:grid;gap:1.1rem;padding:1rem}.af3-result h2,.af3-result h3,.af3-result p{margin:0}.af3-section{display:grid;gap:.5rem}.af3-actions{display:flex;flex-wrap:wrap;gap:.5rem}`;

function list(value) { return Array.isArray(value) ? value : value ? [value] : []; }
function name(artifact) { return artifact && (artifact.name || String(artifact.path || "").split("/").pop()); }
function key(artifact, suffix) { const value = name(artifact); return value && value.endsWith(suffix) ? value.slice(0, -suffix.length) : null; }
function section(title, note) { const node = document.createElement("section"); node.className = "af3-section"; const heading = document.createElement("h3"); heading.textContent = title; node.appendChild(heading); if (note) { const text = document.createElement("p"); text.className = "scientific-note"; text.textContent = note; node.appendChild(text); } return node; }
function message(text) { const node = document.createElement("p"); node.className = "preview-message"; node.textContent = text; return node; }
function themeName() { const value = document.documentElement.getAttribute("data-theme"); return value === "dark" || value === "light" ? value : window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"; }
function matrixRows(projection) { if (!projection || projection.shape.length !== 2) return null; const [rows, columns] = projection.shape; if (rows < 1 || columns < 1) return null; return Array.from({ length: rows }, (_, row) => projection.values.slice(row * columns, (row + 1) * columns)); }

export default {
  async mount(host, context) {
    const Scientific = window.REvoComputeScientific;
    if (!Scientific || typeof Scientific.loadProjection !== "function") throw new Error("Shared scientific visualizations are unavailable.");
    const structures = list(context.files.get("structures"));
    const summaryByKey = new Map(list(context.files.get("summaries")).map((item) => [key(item, "_summary_confidences.json"), item]));
    const confidenceByKey = new Map(list(context.files.get("confidences")).filter((item) => !name(item).endsWith("_summary_confidences.json")).map((item) => [key(item, "_confidences.json"), item]));
    let generation = 0; let matrix = null;

    const root = document.createElement("div"); root.className = "af3-result"; const style = document.createElement("style"); style.textContent = STYLE;
    const heading = document.createElement("h2"); heading.textContent = "AlphaFold 3 prediction"; const intro = document.createElement("p"); intro.textContent = "Candidate-matched structures and bounded confidence evidence."; root.append(style, heading, intro);
    const candidates = section("Predicted structures", "Selecting a candidate updates every confidence view as one generation."); const candidateHost = document.createElement("div"); candidates.appendChild(candidateHost); const actions = document.createElement("div"); actions.className = "af3-actions"; candidates.appendChild(actions); root.appendChild(candidates);
    const metrics = section("Global confidence", "Published values are shown without client-side rescaling."); const metricHost = document.createElement("div"); metrics.appendChild(metricHost); root.appendChild(metrics);
    const pae = section("Expected position error", null); const note = document.createElement("p"); note.className = "scientific-note"; note.id = "af3-pae-note"; note.textContent = "Select a candidate to load bounded PAE evidence."; pae.appendChild(note);
    const toolbar = document.createElement("div"); toolbar.className = "scientific-toolbar"; const borders = document.createElement("button"); borders.type = "button"; borders.className = "btn btn-soft"; borders.textContent = "Show chain borders"; borders.disabled = true; borders.setAttribute("aria-pressed", "false"); toolbar.appendChild(borders); pae.appendChild(toolbar);
    const plot = document.createElement("div"); plot.className = "af3-plot pair-matrix-plot"; const figure = document.createElement("div"); figure.className = "af3-figure pair-matrix-figure"; const canvas = document.createElement("canvas"); canvas.className = "af3-canvas pair-matrix-canvas"; canvas.width = PLOT.width; canvas.height = PLOT.height; canvas.tabIndex = 0; canvas.setAttribute("role", "grid"); canvas.setAttribute("aria-describedby", note.id); figure.appendChild(canvas); plot.appendChild(figure); pae.appendChild(plot); const readout = document.createElement("p"); readout.className = "matrix-readout"; readout.setAttribute("role", "status"); pae.appendChild(readout); root.appendChild(pae); host.replaceChildren(root);

    let residueIds = [], chainIds = [], showBorders = false;
    function clearCandidate(text) { actions.replaceChildren(); metricHost.replaceChildren(); residueIds = []; chainIds = []; borders.disabled = true; readout.textContent = ""; plot.hidden = true; note.textContent = text; if (matrix) { matrix.destroy(); matrix = null; } }
    borders.addEventListener("click", () => { showBorders = !showBorders; borders.setAttribute("aria-pressed", String(showBorders)); if (matrix) matrix.setBorders(showBorders); });
    function scalarValue(projection) { return projection && projection.shape.length === 0 && projection.values.length === 1 ? projection.values[0] : null; }
    async function select(structure, _index, request) {
      const current = ++generation; clearCandidate("Loading candidate confidence...");
      const identity = key(structure, "_model.cif"), summary = summaryByKey.get(identity), confidence = confidenceByKey.get(identity);
      if (!identity || !confidence) { clearCandidate("No exact confidence record matches this structure candidate."); return; }
      try {
        const [scalarResults, required] = await Promise.all([
          summary ? Promise.allSettled(SCALARS.map(([field]) => Scientific.loadNumericProjection(summary, { key: field, signal: request.signal }))) : Promise.resolve([]),
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
        const scalarMetrics = SCALARS.flatMap(([field, label, unit], index) => {
          const result = scalarResults[index];
          if (!result || result.status !== "fulfilled") return [];
          const value = scalarValue(result.value);
          return value == null ? [] : [{ label, value, unit, meaning: field === "fraction_disordered" ? "Lower is better" : "Higher is better" }];
        });
        if (scalarMetrics.length) new Scientific.ScalarMetricGrid(metricHost, scalarMetrics);
        else metricHost.replaceChildren(message("This candidate did not publish global confidence scalars."));
        const open = document.createElement("button"); open.type = "button"; open.className = "btn btn-soft"; open.textContent = "Open selected structure"; open.addEventListener("click", () => context.services.openFile(structure)); actions.replaceChildren(open);
        plot.hidden = false;
        matrix = new Scientific.PairMatrix({ figure, canvas, readout, observe: plot, geometry: PLOT, minimum: 0, decimals: 1, ticks: 5, xTitle: "Aligned residue", yTitle: "Scored residue", legendTitle: "PAE (Å)", unit: "Å", ramp: () => themeName() === "dark" ? RAMP_DARK : RAMP_LIGHT, formatReadout: ({ x, y, value }) => `Aligned residue ${residueIds[x]} (chain ${chainIds[x]}) · Scored residue ${residueIds[y]} (chain ${chainIds[y]}) · ${Number.isFinite(value) ? value.toFixed(1) : "N/A"} Å` });
        matrix.setData({ values, xLabels: residueIds, yLabels: residueIds, xGroups: chainIds, yGroups: chainIds }); matrix.setBorders(showBorders); borders.disabled = false;
        note.textContent = `PAE (Å): ${values.length} × ${values[0].length} scored and aligned residues across ${new Set(chainIds).size} chains. Lower is better.`;
      } catch (error) { if (error.name !== "AbortError" && request.current()) clearCandidate(error.message || "Candidate confidence could not be loaded."); }
    }
    const selector = new Scientific.CandidateSelector(candidateHost, { items: structures, label: (item) => name(item).replace(/_model\.cif$/, ""), onSelect: select });
    if (structures.length) await selector.select(0); else clearCandidate("No structure candidate was published.");
    return { destroy() { generation += 1; selector.destroy(); if (matrix) matrix.destroy(); } };
  },
};
