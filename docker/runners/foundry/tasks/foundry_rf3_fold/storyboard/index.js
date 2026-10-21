/* Foundry RoseTTAFold3 seed/sample confidence composition. */
/* SPDX-License-Identifier: GPL-3.0-only */

const STYLE = `.rf3-result{display:grid;gap:16px;min-width:0;color:var(--app-ink);font:14px/1.5 var(--font-sans)}.rf3-result h2,.rf3-result h3,.rf3-result p{margin:0}.rf3-head{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 18px}.rf3-head h2{font:500 26px var(--font-display);letter-spacing:-.5px;width:100%}.rf3-note{color:var(--app-muted);font-size:14px;line-height:1.7;max-width:78ch}.rf3-section{display:grid;gap:.55rem;min-width:0}.rf3-candidates,.rf3-actions,.rf3-downloads{display:flex;flex-wrap:wrap;gap:.45rem}.rf3-candidates button[aria-current="true"]{outline:2px solid var(--accent);outline-offset:2px}.rf3-hero{display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:18px;min-width:0;align-items:stretch}.rf3-stage{position:relative;min-width:0;height:600px;min-height:600px;border:1px solid var(--app-line);border-radius:8px;overflow:hidden;background:var(--app-stage)}.rf3-stage .storyboard-structure-panel{height:100%}.rf3-stage-label{position:absolute;z-index:4;top:10px;left:10px;max-width:calc(100% - 20px);padding:3px 8px;border:1px solid var(--app-line);border-radius:4px;background:var(--app-surface);color:var(--app-muted);font:12px var(--font-mono);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;pointer-events:none}.rf3-stage-unavailable{position:absolute;z-index:4;inset:0;display:grid;place-items:center;padding:24px;text-align:center;color:var(--app-muted);font-size:13px;line-height:1.6}.rf3-side{min-width:0;display:grid;gap:14px;align-content:start}.rf3-figure{position:relative;overflow:hidden;margin:0 auto}.rf3-figure canvas{display:block;max-width:100%}.rf3-figure .pair-matrix-label{position:absolute;color:var(--muted);font-size:11px}.rf3-figure .af3-label-x{transform:translateX(-50%)}.rf3-figure .af3-label-y{transform:translateY(-50%)}.rf3-figure .af3-title{color:var(--ink);font-size:12px}.rf3-figure .af3-title-y{transform:translate(-50%,-50%) rotate(-90deg);white-space:nowrap}.rf3-caveat{padding:10px 12px;border:1px solid var(--app-line);border-left:3px solid var(--app-plum);border-radius:4px;background:var(--app-soft);font-size:13px;line-height:1.6;color:var(--app-muted)}@container(max-width: 860px){.rf3-hero{grid-template-columns:minmax(0,1fr)}.rf3-stage{height:420px;min-height:420px}}`;
function list(value) { return Array.isArray(value) ? value : value ? [value] : []; }
function element(tag, className, text) { const node = document.createElement(tag); node.className = className; if (text != null) node.textContent = text; return node; }
function section(title, note) { const node = element("section", "rf3-section"); node.appendChild(element("h3", "", title)); if (note) node.appendChild(element("p", "scientific-note", note)); return node; }
function message(value) { return element("p", "preview-message", value); }
async function response(url, signal) { const value = window.REvoDesignAuth ? await window.REvoDesignAuth.authFetch(url, { signal }) : await fetch(url, { credentials: "same-origin", signal }); if (!value.ok) throw new Error("RF3 evidence could not be loaded."); return value; }
async function json(url, signal) { return (await response(url, signal)).json(); }
function identity(name, suffix) { const match = String(name || "").match(new RegExp("^(.*)_seed-(\\d+)_sample-(\\d+)_" + suffix + "$")); return match ? { target: match[1], seed: Number(match[2]), sample: Number(match[3]), key: match[1] + ":" + match[2] + ":" + match[3] } : null; }
function matching(files, candidate, suffix) { const wanted = String(candidate.name || "").replace(/_model\.cif$/, suffix); return files.find((file) => file.name === wanted) || null; }
async function projection(artifact, key, signal) { if (!artifact || !artifact.ndarray_url) return null; try { return await window.REvoComputeScientific.loadNumericProjection(artifact, { key, signal }); } catch (error) { if (signal && signal.aborted) throw error; return null; } }
function square(value) { if (!value || value.shape.length !== 2 || value.shape[0] !== value.shape[1] || value.values.length !== value.shape[0] * value.shape[1]) return null; const rows = []; for (let offset = 0; offset < value.values.length; offset += value.shape[1]) rows.push(value.values.slice(offset, offset + value.shape[1])); return rows; }
function viewMapping(views, id) { const view = list(views).find((item) => item.id === id); return view && view.mapping || {}; }
function seriesWording(direction) { return direction === 'higher' ? 'higher is better' : direction === 'lower' ? 'lower is better' : ''; }
function rankingRows(text, target) { const lines = String(text).trim().split(/\r?\n/); if (lines.shift() !== "seed,sample,ranking_score") return []; return lines.map((line) => { const cells = line.split(","); const seed = Number(cells[0]); const sample = Number(cells[1]); const score = Number(cells[2]); return Number.isInteger(seed) && Number.isInteger(sample) && Number.isFinite(score) ? { key: target + ":" + seed + ":" + sample, score } : null; }).filter(Boolean); }

export default { async mount(host, context) {
  const S = window.REvoComputeScientific; if (!S) throw new Error("Scientific result components are unavailable.");
  const services = context.services || {};
  const structures = list(context.files.get("structures")); const summaries = list(context.files.get("summaries")); const confidences = list(context.files.get("confidences")); const rankings = list(context.files.get("rankings")); const runRecord = list(context.files.get("run_record"))[0]; const modelAssets = list(context.files.get("model_assets"))[0]; let local = null; let matrix = null; let stageGeneration = 0;
  const scores = new Map(); for (const artifact of rankings) { const match = String(artifact.name || "").match(/^(.*)_ranking_scores\.csv$/); if (!match) continue; const rows = rankingRows(await (await response(artifact.url)).text(), match[1]); rows.forEach((row) => scores.set(row.key, row.score)); }
  structures.sort((left, right) => { const a = identity(left.name, "model\\.cif"); const b = identity(right.name, "model\\.cif"); return (scores.get(b && b.key) ?? -Infinity) - (scores.get(a && a.key) ?? -Infinity) || String(left.name).localeCompare(String(right.name)); });
  const root = element("div", "rf3-result"); const style = document.createElement("style"); style.textContent = STYLE;
  const head = element("header", "rf3-head"); head.append(element("h2", "", "RoseTTAFold3 prediction"), element("p", "rf3-note", "Ranked seed/sample predictions with the selected sample's confidence and aligned error beside the structure."));
  // The selected sample's published summary values lead the page, before the stage.
  const metricHost = element("div", "rf3-strip");

  // The structure is the result: one persistent stage on the first screen with
  // the selected sample's confidence evidence beside it.
  const hero = element("div", "rf3-hero");
  const stage = element("section", "rf3-stage"); stage.dataset.structureSlot = "true"; stage.setAttribute("aria-label", "Selected structure");
  const stageLabel = element("p", "rf3-stage-label", "No sample selected");
  const stageUnavailable = element("p", "rf3-stage-unavailable", ""); stageUnavailable.hidden = true;
  stage.append(stageLabel, stageUnavailable);
  const side = element("aside", "rf3-side"); side.setAttribute("aria-label", "Sample confidence evidence");
  const candidates = section("Ranked samples", "Descending published ranking score; target, seed, and sample remain explicit."); const candidateHost = element("div", "rf3-candidates"); const actions = element("div", "rf3-actions"); candidates.append(candidateHost, actions);
  const confidence = section("Atom confidence", "Per-atom pLDDT on RF3's persisted 0 to 1 scale."); const confidenceHost = element("div"); confidence.appendChild(confidenceHost);
  const pae = section("Predicted aligned error", "Token-pair PAE in angstroms; lower is better."); const figure = element("div", "rf3-figure"); const canvas = document.createElement("canvas"); canvas.tabIndex = 0; canvas.setAttribute("role", "grid"); const readout = element("p", "matrix-readout", ""); readout.setAttribute("role", "status"); figure.appendChild(canvas); pae.append(figure, readout);
  side.append(candidates, confidence, pae); hero.append(stage, side);
  const caveat = element("p", "rf3-caveat", "Published values are shown without client-side rescaling; model confidence estimates, not experimental validation.");
  const downloads = element("div", "rf3-downloads"); [["Download run record", runRecord], ["Download model identity", modelAssets]].forEach(([label, artifact]) => { const button = element("button", "btn btn-soft", label); button.type = "button"; button.addEventListener("click", () => context.services.downloadFile(artifact)); downloads.appendChild(button); });
  root.append(style, head, metricHost, hero, caveat, downloads); host.replaceChildren(root);
  const seriesMapping = viewMapping(context.views, "atom_confidence");
  const paeMapping = viewMapping(context.views, "predicted_aligned_error");
  matrix = new S.PairMatrix({ figure, canvas, readout, minimum: paeMapping.scale_min, unit: paeMapping.unit || "angstrom", xTitle: paeMapping.x_label || "Aligned token", yTitle: paeMapping.y_label || "Scored token", legendTitle: "PAE", decimals: 1 });

  function clearCandidate(text) { actions.replaceChildren(); metricHost.replaceChildren(message(text)); confidenceHost.replaceChildren(); figure.hidden = true; readout.textContent = ""; if (local) { local.destroy(); local = null; } }
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
    try {
      const summaryFile = matching(summaries, structure, "_summary_confidences.json"); const confidenceFile = matching(confidences, structure, "_confidences.json"); const [summary, plddt, paeValue] = await Promise.all([summaryFile ? json(summaryFile.url, request.signal) : null, projection(confidenceFile, "atom_plddts", request.signal), projection(confidenceFile, "pae", request.signal)]); if (!request.current()) return;
      const open = element("button", "btn btn-soft", "Open selected structure"); open.type = "button"; open.addEventListener("click", () => context.services.openFile(structure)); actions.replaceChildren(open);
      if (summary) new S.ScalarMetricGrid(metricHost, [{ label: "Overall pLDDT", value: summary.overall_plddt, unit: "score", meaning: "Higher is better" }, { label: "Overall PAE", value: summary.overall_pae, unit: "angstrom", meaning: "Lower is better" }, { label: "Overall PDE", value: summary.overall_pde, unit: "angstrom", meaning: "Lower is better" }, { label: "pTM", value: summary.ptm, unit: "score", meaning: "Higher is better" }, { label: "ipTM", value: summary.iptm, unit: "score", meaning: "Higher is better" }, { label: "Ranking score", value: summary.ranking_score, unit: "score", meaning: "Higher is better" }, { label: "Clash", value: summary.has_clash ? "Yes" : "No" }]); else metricHost.replaceChildren(message("Summary confidence was not published for this sample."));
      if (plddt && plddt.shape.length === 1) local = new S.LocalConfidenceSeries(confidenceHost, { series: [{ label: seriesMapping.y_label || 'Atom pLDDT', values: plddt.values }], xLabel: seriesMapping.x_label || 'Atom index', yLabel: seriesMapping.y_label || 'pLDDT', unit: seriesMapping.unit, direction: seriesWording(seriesMapping.direction), yMin: seriesMapping.y_min, yMax: seriesMapping.y_max }); else confidenceHost.replaceChildren(message("Atom pLDDT is unavailable or exceeds the bounded interactive limit."));
      const values = square(paeValue); if (!values) { readout.textContent = "PAE is unavailable or exceeds the bounded interactive limit."; return true; } figure.hidden = false; const labels = values.map((_, item) => String(item + 1)); matrix.setData({ values, xLabels: labels, yLabels: labels }); return true;
    } catch (error) { if (error.name !== "AbortError" && request.current()) clearCandidate(error.message || "RF3 evidence could not be loaded."); }
  }
  const selector = new S.CandidateSelector(candidateHost, { items: structures, store: context.selection, label: (item) => { const itemIdentity = identity(item.name, "model\\.cif"); const score = itemIdentity ? scores.get(itemIdentity.key) : null; return itemIdentity ? itemIdentity.target + " · seed " + itemIdentity.seed + " · sample " + itemIdentity.sample + (score == null ? "" : " · " + score) : String(item.name || "Sample"); }, onSelect: select }); if (structures.length) await selector.select(0); else candidateHost.replaceChildren(message("RF3 published early-stopping metrics without a structure."));
  return { destroy() { stageGeneration += 1; selector.destroy(); if (local) local.destroy(); matrix.destroy(); } };
} };
