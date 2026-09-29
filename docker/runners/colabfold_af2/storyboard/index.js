/* ColabFold AlphaFold2 scientific result composition. */
/* SPDX-License-Identifier: GPL-3.0-only */

const STYLE = `
.colabfold-result { display: grid; gap: 1rem; padding: 1rem; }
.colabfold-result h2, .colabfold-result h3 { margin: 0; }
.colabfold-result p { margin: 0; }
.colabfold-section { display: grid; gap: 0.55rem; min-width: 0; }
.colabfold-candidates { display: flex; flex-wrap: wrap; gap: 0.45rem; }
.colabfold-candidates button[aria-current="true"] { outline: 2px solid var(--accent); outline-offset: 2px; }
.colabfold-columns { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 26rem), 1fr)); gap: 1rem; }
.colabfold-figure { position: relative; overflow: hidden; }
.colabfold-figure canvas { display: block; max-width: 100%; }
.colabfold-figure .pair-matrix-label { position: absolute; color: var(--muted); font-size: 11px; }
.colabfold-figure .af3-label-x { transform: translateX(-50%); }
.colabfold-figure .af3-label-y { transform: translateY(-50%); }
.colabfold-figure .af3-title { color: var(--ink); font-size: 12px; }
.colabfold-figure .af3-title-y { transform: translate(-50%, -50%) rotate(-90deg); white-space: nowrap; }
`;

function list(value) { return Array.isArray(value) ? value : value ? [value] : []; }
function name(artifact) { return artifact.name || String(artifact.path || "").split("/").pop(); }
function rank(artifact) { const match = name(artifact).match(/_rank_(\d+)_/); return match ? Number(match[1]) : null; }
function section(title, note) {
  const node = document.createElement("section"); node.className = "colabfold-section";
  const heading = document.createElement("h3"); heading.textContent = title; node.appendChild(heading);
  if (note) { const text = document.createElement("p"); text.className = "scientific-note"; text.textContent = note; node.appendChild(text); }
  return node;
}
function message(text) { const node = document.createElement("p"); node.className = "preview-message"; node.textContent = text; return node; }
async function fetchText(artifact, signal) {
  const response = window.REvoDesignAuth
    ? await window.REvoDesignAuth.authFetch(artifact.url, { signal })
    : await fetch(artifact.url, { credentials: "same-origin", signal });
  if (!response.ok) throw new Error("The ColabFold artifact could not be loaded.");
  return response.text();
}
async function fetchJson(artifact, signal) { return JSON.parse(await fetchText(artifact, signal)); }
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
    const structures = preferredStructures(list(context.files.get("structures")));
    const scores = list(context.files.get("scores"));
    const alignment = list(context.files.get("alignment"))[0];
    const interfaceArtifact = list(context.files.get("interface_scores"))[0];
    const scoreByRank = new Map(scores.map((artifact) => [rank(artifact), artifact]));
    const abort = new AbortController(); let generation = 0; let localSeries = null; let matrix = null;

    const root = document.createElement("div"); root.className = "colabfold-result";
    const style = document.createElement("style"); style.textContent = STYLE;
    const heading = document.createElement("h2"); heading.textContent = "ColabFold prediction";
    const intro = document.createElement("p"); intro.textContent = "Ranked AlphaFold2 models with candidate-matched confidence, predicted aligned error, and alignment evidence.";
    root.append(style, heading, intro);

    const candidates = section("Ranked models", "A relaxed model is preferred when ColabFold published both relaxed and unrelaxed files for the same rank.");
    const candidateHost = document.createElement("div"); candidateHost.className = "colabfold-candidates"; candidates.appendChild(candidateHost); root.appendChild(candidates);
    const columns = document.createElement("div"); columns.className = "colabfold-columns";
    const metrics = section("Model confidence", "Values belong to the selected ranked model."); const metricHost = document.createElement("div"); metrics.appendChild(metricHost);
    const local = section("Local confidence", "Per-residue pLDDT; higher values indicate greater model confidence."); const localHost = document.createElement("div"); local.appendChild(localHost);
    columns.append(metrics, local); root.appendChild(columns);

    const pae = section("Predicted aligned error", "Candidate-matched PAE from the selected model's score record; lower values indicate greater confidence in relative residue placement.");
    const figure = document.createElement("div"); figure.className = "colabfold-figure";
    const canvas = document.createElement("canvas"); canvas.tabIndex = 0; canvas.setAttribute("role", "grid");
    const readout = document.createElement("p"); readout.className = "matrix-readout"; readout.setAttribute("role", "status");
    figure.appendChild(canvas); pae.append(figure, readout); root.appendChild(pae);

    const evidence = document.createElement("div"); evidence.className = "colabfold-columns";
    const coverage = section("Alignment coverage", "The published A3M supplied to ColabFold model inference."); const coverageHost = document.createElement("div"); coverage.appendChild(coverageHost);
    const entities = section("Entities", "Lengths and copy counts declared by the ColabFold A3M header."); const entityHost = document.createElement("div"); entities.appendChild(entityHost);
    evidence.append(coverage, entities); root.appendChild(evidence); host.replaceChildren(root);

    matrix = new Scientific.PairMatrix({ figure, canvas, readout, minimum: 0, maximum: 31.75, unit: "Å", xTitle: "Aligned residue", yTitle: "Scored residue", legendTitle: "PAE (Å)", decimals: 1 });
    const [a3m, interfacePayload] = await Promise.all([
      fetchText(alignment, abort.signal),
      interfaceArtifact ? fetchJson(interfaceArtifact, abort.signal).catch(() => null) : Promise.resolve(null),
    ]);
    if (abort.signal.aborted) return { destroy() {} };
    new Scientific.AlignmentCoverage(coverageHost, a3m, { title: "ColabFold alignment coverage", maxRows: 5000 });
    const rows = entityRows(a3m);
    if (rows.length) new Scientific.EntitySummaryTable(entityHost, { columns: ["Entity", "Length", "Copies"], rows });
    else entityHost.replaceChildren(message("This A3M does not publish a ColabFold entity header."));

    async function select(structure) {
      const current = ++generation; const selectedRank = rank(structure); const scoreArtifact = scoreByRank.get(selectedRank);
      if (!scoreArtifact) { metricHost.replaceChildren(message("No score record matches this ranked model.")); localHost.replaceChildren(); return; }
      const payload = await fetchJson(scoreArtifact, abort.signal); if (current !== generation || abort.signal.aborted) return;
      const plddt = Array.isArray(payload.plddt) ? payload.plddt.map(Number) : [];
      const finite = plddt.filter(Number.isFinite); const mean = finite.length ? finite.reduce((sum, value) => sum + value, 0) / finite.length : null;
      const publishedInterface = interfacePayload && interfacePayload.scores_file === name(scoreArtifact) ? interfacePayload : null;
      new Scientific.ScalarMetricGrid(metricHost, [
        { label: "Mean pLDDT", value: mean == null ? null : mean.toFixed(1), unit: "score", meaning: "Higher is better" },
        { label: "pTM", value: payload.ptm, unit: "score", meaning: "Higher is better" },
        { label: "ipTM", value: payload.iptm, unit: "score", meaning: "Higher is better" },
        { label: "Ranking confidence", value: payload.ranking_confidence, unit: "score", meaning: "Higher is better" },
        { label: "ipSAE", value: publishedInterface && publishedInterface.ipsae, unit: "score", meaning: "Higher is better" },
        { label: "pDockQ2", value: publishedInterface && publishedInterface.pdockq2, unit: "score", meaning: "Higher is better" },
      ]);
      if (localSeries) localSeries.destroy();
      if (finite.length) localSeries = new Scientific.LocalConfidenceSeries(localHost, { series: [{ label: "pLDDT", values: plddt }], xValues: plddt.map((_, index) => index + 1), xLabel: "Residue position", yLabel: "pLDDT", unit: "score", direction: "higher is better", yMin: 0, yMax: 100 });
      else localHost.replaceChildren(message("This model did not publish local pLDDT."));
      const values = Array.isArray(payload.pae) ? payload.pae : null;
      if (values && values.length && Array.isArray(values[0])) { figure.hidden = false; matrix.setData({ values, xLabels: values.map((_, index) => String(index + 1)), yLabels: values.map((_, index) => String(index + 1)) }); }
      else { figure.hidden = true; readout.textContent = "This model did not publish PAE."; }
    }
    const selector = new Scientific.CandidateSelector(candidateHost, { items: structures, label: (item) => "Rank " + rank(item), onSelect: select });
    structures.forEach((artifact) => {
      const open = document.createElement("button"); open.type = "button"; open.className = "btn btn-soft btn-small"; open.textContent = "Open rank " + rank(artifact) + " structure"; open.addEventListener("click", () => context.services.openFile(artifact)); candidates.appendChild(open);
    });
    if (structures.length) await selector.select(0); else candidateHost.replaceChildren(message("No ranked model was published."));
    return { destroy() { generation += 1; abort.abort(); selector.destroy(); if (localSeries) localSeries.destroy(); if (matrix) matrix.destroy(); } };
  },
};
