/* AlphaFold2 ranked structure confidence and optional PAE composition. */
/* SPDX-License-Identifier: GPL-3.0-only */

const STYLE = `.af2-result{display:grid;gap:1rem;padding:1rem}.af2-result h2,.af2-result h3,.af2-result p{margin:0}.af2-section{display:grid;gap:.55rem;min-width:0}.af2-candidates,.af2-actions{display:flex;flex-wrap:wrap;gap:.45rem}.af2-candidates button[aria-current="true"]{outline:2px solid var(--accent);outline-offset:2px}.af2-figure{position:relative;overflow:hidden}.af2-figure canvas{display:block;max-width:100%}.af2-figure .pair-matrix-label{position:absolute;color:var(--muted);font-size:11px}.af2-figure .af3-label-x{transform:translateX(-50%)}.af2-figure .af3-label-y{transform:translateY(-50%)}.af2-figure .af3-title{color:var(--ink);font-size:12px}.af2-figure .af3-title-y{transform:translate(-50%,-50%) rotate(-90deg);white-space:nowrap}`;
const JSON_MATRIX_LIMIT = 2 * 1024 * 1024;
function list(value) { return Array.isArray(value) ? value : value ? [value] : []; }
function section(title, note) { const node = document.createElement("section"); node.className = "af2-section"; const heading = document.createElement("h3"); heading.textContent = title; node.appendChild(heading); if (note) { const text = document.createElement("p"); text.className = "scientific-note"; text.textContent = note; node.appendChild(text); } return node; }
function message(value) { const node = document.createElement("p"); node.className = "preview-message"; node.textContent = value; return node; }
async function json(url, signal) { const response = window.REvoDesignAuth ? await window.REvoDesignAuth.authFetch(url, { signal }) : await fetch(url, { credentials: "same-origin", signal }); if (!response.ok) throw new Error("AlphaFold2 evidence could not be loaded."); return response.json(); }
function rankOf(artifact, fallback) { const match = String(artifact.name || "").match(/ranked_(\d+)\.pdb$/); return match ? Number(match[1]) : fallback; }
function bySuffix(files, prefix, identity) { return files.find((file) => String(file.name || "").endsWith(prefix + identity + ".json")) || null; }
function square(value) { if (!Array.isArray(value) || !value.length || value.some((row) => !Array.isArray(row) || row.length !== value.length)) return null; return value; }

export default { async mount(host, context) {
  const S = window.REvoComputeScientific; if (!S) throw new Error("Scientific result components are unavailable.");
  const structures = list(context.files.get("structures")); const confidences = list(context.files.get("confidences")); const paes = list(context.files.get("pae")); const rankingFile = list(context.files.get("ranking"))[0];
  let confidencePlot = null; let matrix = null;
  const root = document.createElement("div"); root.className = "af2-result"; const style = document.createElement("style"); style.textContent = STYLE; const heading = document.createElement("h2"); heading.textContent = "AlphaFold2 prediction"; root.append(style, heading);
  const candidates = section("Ranked models", "Candidate order follows AlphaFold's published ranking."); const candidateHost = document.createElement("div"); candidateHost.className = "af2-candidates"; const actions = document.createElement("div"); actions.className = "af2-actions"; candidates.append(candidateHost, actions); root.appendChild(candidates);
  const confidence = section("Local confidence", "Per-residue pLDDT on AlphaFold's persisted 0 to 100 scale."); const confidenceHost = document.createElement("div"); confidence.appendChild(confidenceHost); root.appendChild(confidence);
  const pae = section("Predicted aligned error", "Optional PAE in angstroms; lower is better."); const figure = document.createElement("div"); figure.className = "af2-figure"; const canvas = document.createElement("canvas"); canvas.tabIndex = 0; canvas.setAttribute("role", "grid"); const readout = document.createElement("p"); readout.className = "matrix-readout"; readout.setAttribute("role", "status"); figure.appendChild(canvas); pae.append(figure, readout); root.appendChild(pae); host.replaceChildren(root);
  matrix = new S.PairMatrix({ figure, canvas, readout, minimum: 0, maximum: 31.75, unit: "angstrom", xTitle: "Aligned residue", yTitle: "Scored residue", legendTitle: "PAE", decimals: 1 });
  const ranking = await json(rankingFile.url); const order = Array.isArray(ranking.order) ? ranking.order : [];
  async function select(structure, index, request) {
    actions.replaceChildren(); const open = document.createElement("button"); open.type = "button"; open.className = "btn btn-soft"; open.textContent = "Open selected structure"; open.addEventListener("click", () => context.services.openFile(structure)); actions.appendChild(open);
    const rank = rankOf(structure, index); const identity = order[rank]; const confidenceFile = identity == null ? null : bySuffix(confidences, "confidence_", identity); const paeFile = identity == null ? null : bySuffix(paes, "pae_", identity);
    if (!confidenceFile) { confidenceHost.replaceChildren(message("Ranked confidence evidence is unavailable.")); figure.hidden = true; readout.textContent = "PAE is unavailable for this model."; return; }
    const confidenceValue = await json(confidenceFile.url, request.signal); if (!request.current()) return; if (confidencePlot) confidencePlot.destroy(); confidencePlot = new S.LocalConfidenceSeries(confidenceHost, { series: [{ label: "pLDDT", values: confidenceValue.confidenceScore }], xValues: confidenceValue.residueNumber, xLabel: "Residue position", yLabel: "pLDDT", unit: "score", direction: "higher is better", yMin: 0, yMax: 100 });
    if (!paeFile) { figure.hidden = true; readout.textContent = "PAE was not published for this model."; return; }
    if (Number(paeFile.size) > JSON_MATRIX_LIMIT) { figure.hidden = true; readout.textContent = "This PAE file exceeds the interactive JSON limit."; return; }
    const payload = await json(paeFile.url, request.signal); if (!request.current()) return; const values = square(Array.isArray(payload) && payload[0] ? payload[0].predicted_aligned_error : null); if (!values) { figure.hidden = true; readout.textContent = "PAE data is invalid."; return; } figure.hidden = false; const labels = values.map((_, item) => String(item + 1)); matrix.setData({ values, xLabels: labels, yLabels: labels });
  }
  const selector = new S.CandidateSelector(candidateHost, { items: structures, label: (item, index) => "Rank " + rankOf(item, index), onSelect: select }); if (structures.length) await selector.select(0); else candidateHost.replaceChildren(message("No ranked structure was published."));
  return { destroy() { selector.destroy(); if (confidencePlot) confidencePlot.destroy(); matrix.destroy(); } };
} };
