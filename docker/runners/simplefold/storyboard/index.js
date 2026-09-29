/* SimpleFold sampled structure and optional pLDDT composition. */
/* SPDX-License-Identifier: GPL-3.0-only */

const STYLE = `.simplefold-result{display:grid;gap:1rem;padding:1rem}.simplefold-result h2,.simplefold-result h3,.simplefold-result p{margin:0}.simplefold-section{display:grid;gap:.55rem;min-width:0}.simplefold-candidates,.simplefold-actions{display:flex;flex-wrap:wrap;gap:.45rem}.simplefold-candidates button[aria-current="true"]{outline:2px solid var(--accent);outline-offset:2px}`;
function list(value) { return Array.isArray(value) ? value : value ? [value] : []; }
function section(title, note) { const node = document.createElement("section"); node.className = "simplefold-section"; const heading = document.createElement("h3"); heading.textContent = title; node.appendChild(heading); if (note) { const text = document.createElement("p"); text.className = "scientific-note"; text.textContent = note; node.appendChild(text); } return node; }
function message(value) { const node = document.createElement("p"); node.className = "preview-message"; node.textContent = value; return node; }
function stem(name) { return String(name || "").replace(/\.(?:cif|pdb|json)$/i, ""); }
async function json(url, signal) { const response = window.REvoDesignAuth ? await window.REvoDesignAuth.authFetch(url, { signal }) : await fetch(url, { credentials: "same-origin", signal }); if (!response.ok) throw new Error("SimpleFold confidence could not be loaded."); return response.json(); }

export default { async mount(host, context) {
  const S = window.REvoComputeScientific; if (!S) throw new Error("Scientific result components are unavailable.");
  const structures = list(context.files.get("structures_cif")).concat(list(context.files.get("structures_pdb"))).sort((left, right) => String(left.name).localeCompare(String(right.name))); const confidences = list(context.files.get("confidences")); let plot = null;
  const root = document.createElement("div"); root.className = "simplefold-result"; const style = document.createElement("style"); style.textContent = STYLE; const heading = document.createElement("h2"); heading.textContent = "SimpleFold prediction"; root.append(style, heading);
  const candidates = section("Sampled structures", "Each candidate is an independently sampled conformation."); const candidateHost = document.createElement("div"); candidateHost.className = "simplefold-candidates"; const actions = document.createElement("div"); actions.className = "simplefold-actions"; candidates.append(candidateHost, actions); root.appendChild(candidates);
  const confidence = section("Local confidence", "Optional per-residue pLDDT on SimpleFold's persisted 0 to 100 scale."); const confidenceHost = document.createElement("div"); confidence.appendChild(confidenceHost); root.appendChild(confidence); host.replaceChildren(root);
  function clearCandidate(text) { actions.replaceChildren(); if (plot) { plot.destroy(); plot = null; } confidenceHost.replaceChildren(message(text)); }
  async function select(structure, index, request) {
    clearCandidate("Loading candidate evidence...");
    const confidenceFile = confidences.find((file) => stem(file.name) === stem(structure.name));
    try {
      const payload = confidenceFile ? await json(confidenceFile.url, request.signal) : null; if (!request.current()) return;
      const open = document.createElement("button"); open.type = "button"; open.className = "btn btn-soft"; open.textContent = "Open selected structure"; open.addEventListener("click", () => context.services.openFile(structure)); actions.replaceChildren(open);
      if (!payload) { confidenceHost.replaceChildren(message("pLDDT was not requested for this run.")); return; }
      plot = new S.LocalConfidenceSeries(confidenceHost, { series: [{ label: "pLDDT", values: payload.confidenceScore }], xLabel: "Residue position", yLabel: "pLDDT", unit: "score", direction: "higher is better", yMin: 0, yMax: 100 });
    } catch (error) { if (error.name !== "AbortError" && request.current()) clearCandidate(error.message || "SimpleFold confidence could not be loaded."); }
  }
  const selector = new S.CandidateSelector(candidateHost, { items: structures, label: (item) => stem(item.name), onSelect: select }); if (structures.length) await selector.select(0); else candidateHost.replaceChildren(message("No sampled structure was published."));
  return { destroy() { selector.destroy(); if (plot) plot.destroy(); } };
} };
