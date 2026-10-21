/* SimpleFold sampled structure and optional pLDDT composition. */
/* SPDX-License-Identifier: GPL-3.0-only */

const STYLE = `
.simplefold-result{display:grid;gap:16px;min-width:0;color:var(--app-ink);font:14px/1.5 var(--font-sans)}
.simplefold-result h2,.simplefold-result h3,.simplefold-result p{margin:0}
.simplefold-head{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 18px}
.simplefold-head h2{font:500 26px var(--font-display);letter-spacing:-.5px;width:100%}
.simplefold-note{color:var(--app-muted);font-size:14px;line-height:1.7;max-width:78ch}
.simplefold-section{display:grid;gap:.55rem;min-width:0}
.simplefold-candidates,.simplefold-actions{display:flex;flex-wrap:wrap;gap:.45rem}
.simplefold-candidates button[aria-current="true"]{outline:2px solid var(--accent);outline-offset:2px}
.simplefold-hero{display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:18px;min-width:0;align-items:stretch}
.simplefold-stage{position:relative;min-width:0;height:600px;min-height:600px;border:1px solid var(--app-line);border-radius:8px;overflow:hidden;background:var(--app-stage)}
.simplefold-stage .storyboard-structure-panel{height:100%}
.simplefold-stage-label{position:absolute;z-index:4;top:10px;left:10px;max-width:calc(100% - 20px);padding:3px 8px;border:1px solid var(--app-line);border-radius:4px;background:var(--app-surface);color:var(--app-muted);font:12px var(--font-mono);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;pointer-events:none}
.simplefold-stage-unavailable{position:absolute;z-index:4;inset:0;display:grid;place-items:center;padding:24px;text-align:center;color:var(--app-muted);font-size:13px;line-height:1.6}
.simplefold-side{min-width:0;display:grid;gap:14px;align-content:start}
.simplefold-caveat{padding:10px 12px;border:1px solid var(--app-line);border-left:3px solid var(--app-plum);border-radius:4px;background:var(--app-soft);font-size:13px;line-height:1.6;color:var(--app-muted)}
@container(max-width: 860px){.simplefold-hero{grid-template-columns:minmax(0,1fr)}.simplefold-stage{height:420px;min-height:420px}}
`;
function list(value) { return Array.isArray(value) ? value : value ? [value] : []; }
function element(tag, className, text) { const node = document.createElement(tag); node.className = className; if (text != null) node.textContent = text; return node; }
function section(title, note) { const node = element("section", "simplefold-section"); node.appendChild(element("h3", "", title)); if (note) node.appendChild(element("p", "scientific-note", note)); return node; }
function message(value) { return element("p", "preview-message", value); }
function stem(name) { return String(name || "").replace(/\.(?:cif|pdb|json)$/i, ""); }
// The Task's declared per-residue series owns its labels, unit, range and
// direction; the module reads them instead of pinning a vocabulary of its own.
function seriesMapping(views) { const view = list(views).find((item) => item.id === "residue_confidence"); return view && view.mapping || {}; }
async function json(url, signal) { const response = window.REvoDesignAuth ? await window.REvoDesignAuth.authFetch(url, { signal }) : await fetch(url, { credentials: "same-origin", signal }); if (!response.ok) throw new Error("SimpleFold confidence could not be loaded."); return response.json(); }

export default { async mount(host, context) {
  const S = window.REvoComputeScientific; if (!S) throw new Error("Scientific result components are unavailable.");
  const services = context.services || {};
  const structures = list(context.files.get("structures_cif")).concat(list(context.files.get("structures_pdb"))).sort((left, right) => String(left.name).localeCompare(String(right.name))); const confidences = list(context.files.get("confidences")); let plot = null; let stageGeneration = 0;
  const root = element("div", "simplefold-result"); const style = document.createElement("style"); style.textContent = STYLE;
  const head = element("header", "simplefold-head"); head.append(element("h2", "", "SimpleFold prediction"), element("p", "simplefold-note", "Independently sampled conformations with the selected sample's optional local confidence beside the structure."));
  // SimpleFold publishes no global scalar summary, so this page has no metric
  // strip: the sampled selector and the stage label name the candidate.

  // The structure is the result: one persistent stage on the first screen,
  // with the selected sample's confidence beside it.
  const hero = element("div", "simplefold-hero");
  const stage = element("section", "simplefold-stage"); stage.dataset.structureSlot = "true"; stage.setAttribute("aria-label", "Selected structure");
  const stageLabel = element("p", "simplefold-stage-label", "No sample selected");
  const stageUnavailable = element("p", "simplefold-stage-unavailable", ""); stageUnavailable.hidden = true;
  stage.append(stageLabel, stageUnavailable);
  const side = element("aside", "simplefold-side"); side.setAttribute("aria-label", "Sample confidence evidence");
  const candidates = section("Sampled structures", "Each candidate is an independently sampled conformation."); const candidateHost = element("div", "simplefold-candidates"); const actions = element("div", "simplefold-actions"); candidates.append(candidateHost, actions);
  const confidence = section("Local confidence", "Optional per-residue pLDDT on SimpleFold's persisted 0 to 100 scale."); const confidenceHost = element("div"); confidence.appendChild(confidenceHost);
  side.append(candidates, confidence); hero.append(stage, side);
  const residueMapping = seriesMapping(context.views);
  const caveat = element("p", "simplefold-caveat", "pLDDT is a model confidence estimate, not experimental validation.");
  root.append(style, head, hero, caveat); host.replaceChildren(root);
  function clearCandidate(text) { actions.replaceChildren(); if (plot) { plot.destroy(); plot = null; } confidenceHost.replaceChildren(message(text)); }
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
    const confidenceFile = confidences.find((file) => stem(file.name) === stem(structure.name));
    try {
      const payload = confidenceFile ? await json(confidenceFile.url, request.signal) : null; if (!request.current()) return;
      const open = document.createElement("button"); open.type = "button"; open.className = "btn btn-soft"; open.textContent = "Open selected structure"; open.addEventListener("click", () => context.services.openFile(structure)); actions.replaceChildren(open);
      if (!payload) { confidenceHost.replaceChildren(message("pLDDT was not requested for this run.")); return true; }
      plot = new S.LocalConfidenceSeries(confidenceHost, { series: [{ label: residueMapping.y_label || 'pLDDT', values: payload.confidenceScore }], xLabel: residueMapping.x_label || 'Residue position', yLabel: residueMapping.y_label || 'pLDDT', unit: residueMapping.unit, direction: residueMapping.direction === 'higher' ? 'higher is better' : residueMapping.direction === 'lower' ? 'lower is better' : '', yMin: residueMapping.y_min, yMax: residueMapping.y_max });
      return true;
    } catch (error) { if (error.name !== "AbortError" && request.current()) clearCandidate(error.message || "SimpleFold confidence could not be loaded."); }
  }
  const selector = new S.CandidateSelector(candidateHost, { items: structures, store: context.selection, label: (item) => stem(item.name), onSelect: select }); if (structures.length) await selector.select(0); else candidateHost.replaceChildren(message("No sampled structure was published."));
  return { destroy() { stageGeneration += 1; selector.destroy(); if (plot) plot.destroy(); } };
} };
