/* fpocket result storyboard: rank the detected pockets and read one pocket structurally. */
/* SPDX-License-Identifier: GPL-3.0-only */

const STYLE = `
.fpl-result { display:grid; gap:0; min-width:0; color:var(--app-ink); font:14px/1.5 var(--font-sans); }
.fpl-result .btn { font:14px var(--font-sans); min-height:35px; padding:7px 11px; border:1px solid var(--app-line-strong); border-radius:4px; background:var(--app-raised); color:inherit; cursor:pointer; }
.fpl-result h2,.fpl-result h3,.fpl-result h4,.fpl-result p { margin:0; }
.fpl-stage { height:590px; display:grid; grid-template-columns:minmax(0,1fr) 292px; gap:24px; padding-right:24px; border:1px solid var(--app-line); border-radius:8px; background:var(--app-stage); overflow:hidden; }
.fpl-molecular-region { display:flex; flex-direction:column; min-width:0; min-height:0; background:var(--app-surface); }
.fpl-scene { position:relative; flex:1; min-height:0; }
.fpl-scene-label,.fpl-scene-bottom { position:absolute; left:24px; right:24px; display:flex; justify-content:space-between; gap:16px; z-index:3; pointer-events:none; font-size:14px; color:var(--app-muted); }
.fpl-scene-label { top:22px; } .fpl-scene-bottom { bottom:17px; font-size:10px; }
.fpl-scene-bottom [role=status] { color:var(--app-plum); }
.fpl-scene-label .mono { font:10px var(--font-mono); margin-left:12px; }
.fpl-structure-slot { position:absolute; inset:44px 12px 48px; }
.fpl-scene .msp-plugin,.fpl-scene .msp-layout-standard,.fpl-scene .msp-viewport { background:transparent; }
.fpl-inspector { min-width:0; min-height:0; display:flex; flex-direction:column; padding-top:23px; }
.fpl-inspector-head { flex:none; border-bottom:1px solid var(--app-line-strong); padding-bottom:16px; }
.fpl-eyebrow { font:10px var(--font-mono); letter-spacing:1.3px; text-transform:uppercase; color:var(--app-muted); }
.fpl-inspector-head h3 { font:500 25px var(--font-display); letter-spacing:-.5px; margin:8px 0 5px; }
.fpl-inspector-head .fpl-note { font-size:14px; }
.fpl-detail { padding:20px 4px 15px 0; overflow:auto; scrollbar-gutter:stable; min-height:0; }
.fpl-metrics { display:grid; grid-template-columns:1fr 1fr; gap:19px 18px; margin:0; }
.fpl-pair dt { color:var(--app-muted); font-size:14px; margin-bottom:5px; }
.fpl-pair dd { margin:0; font:400 20px/1.5 var(--font-mono); }
.fpl-actions { display:flex; flex-wrap:wrap; align-items:center; gap:12px; margin:20px 0 15px; }
.fpl-highlight { display:flex; align-items:center; gap:7px; font-size:14px; }
.fpl-highlight input { accent-color:var(--app-plum); width:15px; height:15px; }
.fpl-detail details { border-top:1px solid var(--app-line-strong); }
.fpl-detail summary { cursor:pointer; display:flex; align-items:center; justify-content:space-between; min-height:43px; padding:11px 0; font-size:14px; }
.fpl-detail summary::after { content:'+'; color:var(--app-muted); } .fpl-detail details[open] summary::after { content:'−'; }
.fpl-detail details .fpl-metrics { display:block; margin-bottom:16px; }
.fpl-detail details .fpl-pair { display:flex; align-items:baseline; justify-content:space-between; gap:12px; border-bottom:1px solid var(--app-line); padding:5px 0; }
.fpl-detail details dd { font-size:14px; }
.fpl-detail details .btn { margin:4px 0 8px; }
.fpl-residues { display:flex; flex-wrap:wrap; gap:5px; padding-bottom:16px; }
.fpl-chip { font:14px var(--font-mono); padding:4px 6px; border:1px solid var(--app-line); border-radius:3px; }
.fpl-note,.fpl-unavailable { color:var(--app-muted); font-size:14px; line-height:1.7; }
.fpl-detail > .fpl-note { margin-top:14px; }
.fpl-layout { padding-top:24px; min-width:0; }
.fpl-section { min-width:0; }
.fpl-evidence-head { display:flex; align-items:center; gap:24px; padding-bottom:16px; }
.fpl-evidence-head h3 { font:500 22px var(--font-display); letter-spacing:-.4px; margin-top:7px; }
.fpl-selector-tools { display:flex; flex-wrap:wrap; align-items:center; gap:18px; margin-left:auto; }
.fpl-selector-tools input { width:180px; max-width:100%; padding:8px 0; border:0; border-bottom:1px solid var(--app-line-strong); background:transparent; font:14px var(--font-sans); color:inherit; }
.fpl-table-wrap { max-height:210px; overflow:auto; border-top:1px solid var(--app-line-strong); }
.fpl-pockets { width:100%; min-width:730px; border-collapse:collapse; font-size:14px; }
.fpl-pockets th,.fpl-pockets td { padding:11px 15px; text-align:left; border-bottom:1px solid var(--app-line); white-space:nowrap; }
.fpl-pockets th { position:sticky; top:0; background:var(--app-bg); color:var(--app-muted); font-size:14px; font-weight:400; }
.fpl-pockets td { height:42px; font:14px var(--font-mono); }
.fpl-pockets th:first-child,.fpl-pockets td:first-child { position:sticky; left:0; background:var(--app-bg); }
.fpl-pockets th:first-child { z-index:3; }
.fpl-pocket-row { cursor:pointer; }
.fpl-rank { display:inline-block; width:34px; color:var(--app-muted); font-size:10px; }
.fpl-pocket-row:focus-visible { outline:2px solid var(--app-plum); outline-offset:-2px; }
.fpl-pocket-row[aria-current=true],.fpl-pocket-row[aria-current=true] td:first-child { background:var(--app-soft); }
.fpl-pocket-row[aria-current=true] td:first-child { box-shadow:inset 3px 0 var(--app-plum); }
.fpl-artifacts { margin-top:12px; } .fpl-artifacts > summary { padding:12px 0; font-size:14px; cursor:pointer; }
.fpl-scene .msp-layout-standard { border:0; }
.fpl-scene .msp-viewport-controls { opacity:.85; } .fpl-scene:hover .msp-viewport-controls,.fpl-scene:focus-within .msp-viewport-controls { opacity:1; }
.fpl-geometry-hint { font-size:10px; color:var(--app-muted); }
.fpl-result .structure-viewport { border:0; border-radius:0; box-shadow:none; }
.fpl-stage:fullscreen { width:100vw; height:100vh; }
@container(max-width:1150px) { .fpl-stage { grid-template-columns:minmax(0,1fr) 267px; gap:18px; padding-right:18px; height:610px; } .fpl-scene-label,.fpl-scene-bottom { left:18px; right:18px; } .fpl-evidence-head { flex-wrap:wrap; } }
@container(max-width:820px) { .fpl-stage { display:flex; flex-direction:column; height:auto; padding:0; gap:0; } .fpl-scene { height:365px; flex:none; } .fpl-inspector { border-top:1px solid var(--app-line); padding:20px 22px; } .fpl-inspector-head { display:flex; flex-wrap:wrap; align-items:center; gap:8px 15px; } .fpl-inspector-head .fpl-eyebrow { width:100%; } .fpl-detail { overflow:visible; } .fpl-selector-tools { margin-left:0; } .fpl-stage:fullscreen { overflow:auto; } }
@container(max-width:480px) { .fpl-scene { height:320px; } .fpl-scene-label .mono { display:none; } .fpl-scene-bottom { flex-direction:column; gap:4px; } .fpl-evidence-head { gap:14px; } .fpl-selector-tools { gap:10px; } }
`;

// The columns the ranked selector exposes: rank and score first, then the
// fpocket-reported descriptors a reader compares a pocket by.
const COLUMNS = [
  { key: "rank", label: "Rank" },
  { key: "pocket", label: "Pocket" },
  { key: "score", label: "Score" },
  { key: "druggability_score", label: "Druggability" },
  { key: "alpha_spheres", label: "Alpha spheres" },
  { key: "volume_angstrom3", label: "Volume (A^3)" },
  { key: "residue_count", label: "Contacts" },
  { key: "total_sasa_angstrom2", label: "SASA (A^2)" },
  { key: "center_x", label: "Centre x" },
  { key: "center_y", label: "Centre y" },
  { key: "center_z", label: "Centre z" },
];

// The descriptor readout for the selected pocket. Each label says only that the
// value is what fpocket reported; no threshold is applied, because fpocket
// defines none for these fields.
const DETAIL = [
  { key: "score", label: "fpocket score" },
  { key: "druggability_score", label: "Druggability score" },
  { key: "volume_angstrom3", label: "Volume / Å³" },
  { key: "residue_count", label: "Contact residues" },
  { key: "alpha_spheres", label: "Alpha spheres" },
  { key: "total_sasa_angstrom2", label: "Total SASA / Å²" },
  { key: "mean_alpha_sphere_radius_angstrom", label: "Mean alpha-sphere radius (A)" },
  { key: "center_x", label: "Centre x (A)" },
  { key: "center_y", label: "Centre y (A)" },
  { key: "center_z", label: "Centre z (A)" },
];

function list(value) { return Array.isArray(value) ? value : value ? [value] : []; }
function first(context, id) { return list(context.files.get(id))[0] || null; }
function pocketNumber(path) {
  const match = /pocket(\d+)/.exec(String(path || ""));
  return match ? Number(match[1]) : null;
}
function text(value) { return value == null || value === "" ? "—" : String(value); }

// Parse the normalized pockets.csv (one header row plus one row per pocket).
function parseCsv(source) {
  const rows = []; let row = []; let field = ""; let quoted = false;
  for (let index = 0; index < source.length; index += 1) {
    const character = source[index];
    if (quoted) {
      if (character === '"') { if (source[index + 1] === '"') { field += '"'; index += 1; } else quoted = false; }
      else field += character;
    } else if (character === '"') quoted = true;
    else if (character === ",") { row.push(field); field = ""; }
    else if (character === "\n") { row.push(field); rows.push(row); row = []; field = ""; }
    else if (character !== "\r") field += character;
  }
  if (field || row.length) { row.push(field); rows.push(row); }
  if (!rows.length) return [];
  const header = rows[0].map((name) => name.trim());
  return rows.slice(1)
    .filter((values) => values.some((value) => value !== ""))
    .map((values) => Object.fromEntries(header.map((name, column) => [name, values[column]])));
}

// Residue ids are published as "<chain>_<resSeq>" tokens (e.g. "A_101").
function residueTokens(value) {
  const raw = Array.isArray(value) ? value : String(value || "").split(/\s+/);
  return raw.map((token) => String(token).trim()).filter(Boolean);
}
// A residue id is "<chain>_<resSeq>[<iCode>]" in PDB AUTHOR numbering (what
// normalize_results.py reads from PDB columns 23-27). Split on the LAST
// underscore so a multi-character chain or residue never mis-splits, and carry
// the insertion code: "A_42A" is residue 42 with iCode A, not residue 42.
function residueSelection(token) {
  const text = String(token || "");
  const split = text.lastIndexOf("_");
  if (split < 0) return null;
  const chain = text.slice(0, split);
  const match = /^(-?[0-9]+)(.*)$/.exec(text.slice(split + 1));
  if (!match) return null;
  // The author residue identity is stated in full: a bare residue is the empty
  // insertion code, not an unspecified one, so "A_42" (bare 42) and "A_42A"
  // (42 with iCode A) stay distinct rather than the bare residue widening to
  // every insertion variant at that position.
  return { chain: chain || undefined, residue: Number(match[1]), insertionCode: match[2] };
}
function toStructureSelection(entry) {
  return { chain: entry.chain, residue: entry.residue, numbering: "auth_seq_id", insertionCode: entry.insertionCode };
}
async function fetchText(artifact, signal) {
  const response = window.REvoDesignAuth
    ? await window.REvoDesignAuth.authFetch(artifact.url, { signal })
    : await fetch(artifact.url, { credentials: "same-origin", signal });
  if (!response.ok) throw new Error("The fpocket pocket table could not be loaded.");
  return response.text();
}

export default {
  async mount(host, context) {
    const controller = new AbortController();
    let destroyed = false;
    const services = context.services || {};
    const focusStructure = typeof services.focusStructure === "function" ? services.focusStructure : null;
    const selectStructure = typeof services.selectStructure === "function" ? services.selectStructure : null;

    const root = document.createElement("div"); root.className = "fpl-result";
    const style = document.createElement("style"); style.textContent = STYLE;
    root.append(style);

    const layout = document.createElement("div"); layout.className = "fpl-layout";
    const selector = document.createElement("section"); selector.className = "fpl-section";
    const selectorTitle = document.createElement("h3"); selectorTitle.textContent = "Ranked pockets";
    const tableWrap = document.createElement("div"); tableWrap.className = "fpl-table-wrap";
    const selectorTools = document.createElement("div"); selectorTools.className = "fpl-selector-tools";
    const search = document.createElement("input"); search.type = "search"; search.placeholder = "Pocket or residue…"; search.setAttribute("aria-label", "Find pocket or contacted residue");
    const compare = document.createElement("button"); compare.type = "button"; compare.className = "btn btn-soft"; compare.textContent = "Compare descriptors"; compare.setAttribute("aria-expanded", "false");
    let expanded = false;
    compare.addEventListener("click", () => { expanded = !expanded; compare.setAttribute("aria-expanded", String(expanded)); renderTable(); });
    search.addEventListener("input", () => renderTable());
    const evidenceHead = document.createElement('header'); evidenceHead.className = 'fpl-evidence-head'; const evidenceIdentity = document.createElement('div'); const evidenceKicker = document.createElement('p'); evidenceKicker.className = 'fpl-eyebrow'; evidenceKicker.textContent = 'Ranked pockets'; selectorTitle.textContent = 'Detected pockets'; evidenceIdentity.append(evidenceKicker, selectorTitle); selectorTools.append(search, compare); evidenceHead.append(evidenceIdentity, selectorTools); selector.append(evidenceHead, tableWrap);
    const detail = document.createElement("aside"); detail.className = "fpl-inspector"; detail.setAttribute("aria-label", "Pocket inspector");
    const detailTitle = document.createElement("h3"); detailTitle.textContent = "Selected pocket";
    const detailBody = document.createElement("div"); detailBody.className = "fpl-detail";
    const inspectorHead = document.createElement('header'); inspectorHead.className = 'fpl-inspector-head'; const inspectorKicker = document.createElement('p'); inspectorKicker.className = 'fpl-eyebrow'; inspectorKicker.textContent = 'Pocket inspector'; const inspectorStatus = document.createElement('p'); inspectorStatus.className = 'fpl-note'; inspectorHead.append(inspectorKicker, detailTitle, inspectorStatus); detail.append(inspectorHead, detailBody);
    const stage = document.createElement("div"); stage.className = "fpl-stage";
    const structureSlot = document.createElement("section"); structureSlot.dataset.structureSlot = "true";
    stage.dataset.molecularWorkspace = 'true';
    const molecularRegion = document.createElement('div'); molecularRegion.className = 'fpl-molecular-region';
    const scene = document.createElement('div'); scene.className = 'fpl-scene';
    structureSlot.className = 'fpl-structure-slot';
    const sceneLabel = document.createElement('div'); sceneLabel.className = 'fpl-scene-label'; const sourceLabel = document.createElement('span'); sourceLabel.textContent = 'Protein structure'; const sceneLegend = document.createElement('span'); sceneLegend.dataset.structureLegend = 'true'; sceneLegend.textContent = 'Sequence N → C'; sceneLabel.append(sourceLabel, sceneLegend);
    const sceneBottom = document.createElement('div'); sceneBottom.className = 'fpl-scene-bottom'; const spatialStatus = document.createElement('span'); spatialStatus.setAttribute('role','status'); const viewStatus = document.createElement('span'); viewStatus.textContent = 'Whole structure'; sceneBottom.append(spatialStatus, viewStatus);
    const toolsSlot = document.createElement('div'); toolsSlot.dataset.structureTools = 'true';
    scene.append(sceneLabel, structureSlot, sceneBottom); molecularRegion.append(scene, toolsSlot); stage.append(molecularRegion, detail); layout.append(selector); root.append(stage, layout);
    stage.addEventListener('structure-reset', () => { pocketFocused = false; viewStatus.textContent = 'Whole structure'; });

    const views = Array.isArray(context.views) ? context.views : [];
    const openView = typeof services.openView === "function" ? services.openView : null;
    const generic = document.createElement("section"); generic.className = "fpl-section";
    const genericTitle = document.createElement("h4"); genericTitle.textContent = "Full result and evidence";
    const genericActions = document.createElement("div"); genericActions.className = "fpl-actions";
    for (const view of views) {
      const button = document.createElement("button"); button.type = "button"; button.className = "btn btn-soft";
      button.textContent = "Open " + view.title; button.dataset.viewId = view.id;
      button.addEventListener("click", () => { if (openView) void openView(view.id); });
      genericActions.append(button);
    }
    const pocketsFile = first(context, "pockets");
    if (pocketsFile) {
      const download = document.createElement("button"); download.type = "button"; download.className = "btn btn-soft";
      download.textContent = "Download table ↓"; download.dataset.fileId = pocketsFile.id;
      download.addEventListener("click", () => services.downloadFile?.(pocketsFile));
      selectorTools.append(download);
    }
    generic.append(genericTitle, genericActions); const artifacts = document.createElement("details"); artifacts.className = "fpl-artifacts"; const artifactsTitle = document.createElement("summary"); artifactsTitle.textContent = "Associated views and artifacts"; artifacts.append(artifactsTitle, generic); root.append(artifacts);
    host.replaceChildren(root);

    // Pocket geometry files are optional: a result whose per-pocket files were
    // not published must still list and describe its pockets.
    const structureArtifact = first(context, "protein_structure");
    if (structureArtifact) { const source = document.createElement('span'); source.className = 'mono'; source.textContent = '/ ' + (structureArtifact.name || structureArtifact.path || '').split('/').pop(); sourceLabel.append(source); }
    let structureOpened = false;
    let selectionGeneration = 0;
    const geometry = new Map();
    for (const artifact of list(context.files.get("pocket_contacts"))) {
      const number = pocketNumber(artifact.name || artifact.path);
      if (number != null) geometry.set(number, Object.assign(geometry.get(number) || {}, { contacts: artifact }));
    }
    for (const artifact of list(context.files.get("pocket_alpha_spheres"))) {
      const number = pocketNumber(artifact.name || artifact.path);
      if (number != null) geometry.set(number, Object.assign(geometry.get(number) || {}, { spheres: artifact }));
    }

    let pockets = [];
    let selectedIndex = 0;
    let pocketFocused = false;
    let highlightContacts = true;
    let geometryShown = false; let geometryToggle = null;
    let tableLoaded = false;
    if (!pocketsFile) {
      tableWrap.append(message("The ranked pocket table was not published.", "fpl-unavailable"));
    } else {
      try {
        if (Number(pocketsFile.size) > 8 * 1024 * 1024) throw new Error("The pocket table exceeds the preview limit.");
        pockets = parseCsv(await fetchText(pocketsFile, controller.signal));
        tableLoaded = true;
      } catch (error) {
        if (error.name === "AbortError") return { destroy() { destroyed = true; controller.abort(); } };
        tableWrap.append(message(error.message || "The ranked pocket table could not be loaded.", "fpl-unavailable"));
      }
    }
    if (destroyed) return { destroy() { destroyed = true; controller.abort(); } };
    if (pockets.length) renderTable();
    else if (tableLoaded) tableWrap.append(message("fpocket reported no pockets for this structure.", "fpl-unavailable"));
    if (pockets.length) void selectPocket(0); else { renderEmptyDetail(); if (structureArtifact) void services.openFile?.(structureArtifact); }

    function message(value, className) {
      const node = document.createElement("p"); node.className = className || "fpl-note"; node.textContent = value; return node;
    }
    function renderTable() {
      const table = document.createElement("table"); table.className = "fpl-pockets";
      const head = document.createElement("thead"); const headRow = document.createElement("tr");
      const columns = expanded ? COLUMNS : [{key:"candidate",label:"Candidate"}, ...COLUMNS.filter(column => ["score", "druggability_score", "volume_angstrom3", "residue_count"].includes(column.key))];
      columns.forEach((column) => { const cell = document.createElement("th"); cell.scope = "col"; cell.textContent = column.label; headRow.append(cell); });
      head.append(headRow); table.append(head);
      const body = document.createElement("tbody");
      pockets.forEach((pocket, index) => {
        const query = search.value.trim().toLowerCase();
        if (query && ![pocket.pocket, pocket.residue_ids].join(" ").toLowerCase().includes(query)) return;
        const row = document.createElement("tr"); row.className = "fpl-pocket-row";
        row.dataset.pocket = String(pocketNumber(pocket.pocket) ?? index + 1); row.tabIndex = 0;
        row.setAttribute("role", "button"); row.setAttribute("aria-current", String(index === selectedIndex));
        columns.forEach((column) => { const cell = document.createElement("td"); if (column.key === 'candidate') { const rank = document.createElement('span'); rank.className = 'fpl-rank'; rank.textContent = text(pocket.rank).padStart(2,'0'); cell.append(rank, 'Pocket ' + (pocketNumber(pocket.pocket) ?? index + 1)); } else cell.textContent = text(pocket[column.key]); row.append(cell); });
        row.addEventListener("click", () => selectPocket(index));
        row.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); selectPocket(index); } });
        body.append(row);
      });
      table.append(body); tableWrap.replaceChildren(table);
      if (!body.childElementCount) tableWrap.append(message("No pockets match this search."));
    }
    function renderEmptyDetail() {
      detailBody.replaceChildren(message("Select a pocket to see its fpocket-reported descriptors and contacted residues.", "fpl-note"));
    }

    // The pocket's own descriptor readout, then the structural interpretation:
    // focus the viewer on the pocket's geometric centre, highlight the residues
    // its alpha spheres contact, and open the contacted-atom / vertex files.
    function renderDetail(pocket, index) {
      detailTitle.textContent = "Pocket " + (pocketNumber(pocket.pocket) ?? index + 1);
      inspectorStatus.textContent = 'Rank ' + text(pocket.rank || index + 1) + ' · selected pocket';
      spatialStatus.textContent = 'Pocket ' + (pocketNumber(pocket.pocket) ?? index + 1) + ' · ' + (highlightContacts ? text(pocket.residue_count) + ' contacts highlighted' : 'contact highlight off');
      const nodes = [];
      const pairList = document.createElement("dl"); pairList.className = "fpl-metrics";
      const extra = document.createElement("details"); const extraTitle = document.createElement("summary"); extraTitle.textContent = "Scientific descriptors";
      const extraPairs = document.createElement("dl"); extraPairs.className = "fpl-metrics"; extra.append(extraTitle, extraPairs);
      DETAIL.forEach((entry) => {
        if (pocket[entry.key] == null || pocket[entry.key] === "") return;
        const pair = document.createElement("div"); pair.className = "fpl-pair";
        const term = document.createElement("dt"); term.textContent = entry.label;
        const value = document.createElement("dd"); value.textContent = text(pocket[entry.key]);
        pair.append(term, value); (DETAIL.indexOf(entry) < 4 ? pairList : extraPairs).append(pair);
      });
      if (pairList.childElementCount) nodes.push(pairList);

      const number = pocketNumber(pocket.pocket) ?? index + 1;
      const files = geometry.get(number) || {};
      const residueIds = residueTokens(pocket.residue_ids);
      const residueHeader = document.createElement("h4"); residueHeader.textContent = "Contacted residues (" + text(pocket.residue_count) + ")";
      const contacts = document.createElement("details"); const contactsTitle = document.createElement("summary"); contactsTitle.textContent = residueHeader.textContent; contacts.append(contactsTitle);
      if (residueIds.length) {
        const chips = document.createElement("div"); chips.className = "fpl-residues";
        residueIds.forEach((token) => { const chip = document.createElement("span"); chip.className = "fpl-chip"; chip.textContent = token; chips.append(chip); });
        contacts.append(chips);
      } else {
        contacts.append(message("No contacted residues were reported for this pocket.", "fpl-note"));
      }

      const resources = document.createElement("details"); const resourcesTitle = document.createElement("summary"); resourcesTitle.textContent = "Pocket artifacts"; resources.append(resourcesTitle);
      const actions = document.createElement("div"); actions.className = "fpl-actions";
      const target = focusSelection(pocket);
      if (target && focusStructure) {
        actions.append(actionButton("Focus this pocket", () => focusOnPocket(pocket, target)));
      }
      if (residueIds.length && selectStructure) {
        const label = document.createElement("label"); label.className = "fpl-highlight"; const toggle = document.createElement("input"); toggle.type = "checkbox"; toggle.checked = highlightContacts; toggle.addEventListener("change", () => { highlightContacts = toggle.checked; if (highlightContacts) selectResidues(residueIds); else selectStructure({ residues: [] }); spatialStatus.textContent = 'Pocket ' + text(pocket.rank) + (highlightContacts ? ' · ' + text(pocket.residue_count) + ' contacts highlighted' : ' · contact highlight off'); }); label.append(toggle, " Highlight contacts"); actions.append(label);
      }
      if (files.contacts) resources.append(actionButton("Download contacted atoms", () => services.downloadFile?.(files.contacts)));
      if (files.spheres) resources.append(actionButton("Inspect alpha-sphere coordinates", () => services.openGeometry?.(files.spheres, "Alpha-sphere centres from the published PQR artifact. Markers have a fixed display size; they do not show sphere radii or a cavity surface. The protein remains above for context.")));


      if (actions.childElementCount) nodes.push(actions);
      nodes.push(contacts, extra, resources, message("Candidate site, not a confirmed binding site. No decision threshold is applied to these scores."));
      if (!files.contacts && !files.spheres) {
        nodes.push(message("Pocket geometry files were not published. Reported descriptors and contacts remain available.", "fpl-note"));
      }
      detailBody.replaceChildren(...nodes);
    }
    function actionButton(label, run) {
      const node = document.createElement("button"); node.type = "button"; node.className = "btn btn-soft"; node.textContent = label;
      // A rejected async action (focus/select/open) must not break the result.
      node.addEventListener("click", () => { try { Promise.resolve(run()).catch(() => {}); } catch (_error) { /* ignored */ } });
      return node;
    }
    // The pocket's geometric centre, as a bounded spatial focus target for the
    // shared structure adapter (never Mol* internals from here).
    function focusSelection(pocket) {
      if (["center_x", "center_y", "center_z"].some(axis => pocket[axis] == null || String(pocket[axis]).trim() === "")) return null;
      const [x, y, z] = ["center_x", "center_y", "center_z"].map((axis) => Number(pocket[axis]));
      if (![x, y, z].every((value) => Number.isFinite(value))) return null;
      const radius = Number(pocket.mean_alpha_sphere_radius_angstrom);
      return { focusPoint: { x, y, z, radius: Number.isFinite(radius) && radius > 0 ? radius * 2 : undefined } };
    }
    async function selectPocket(index) {
      selectedIndex = index;
      const generation = ++selectionGeneration;
      services.closeGeometry?.();
      const pocket = pockets[index]; if (!pocket) return;
      const row = tableWrap.querySelector('[data-pocket="' + String(pocketNumber(pocket.pocket) ?? index + 1) + '"]');
      tableWrap.querySelectorAll(".fpl-pocket-row").forEach((node) => node.setAttribute("aria-current", node === row ? "true" : "false"));
      renderDetail(pocket, index);
      // Publish the choice to the shared selection store so the structure panel
      // and any other cooperating view follow the same pocket without a reload.
      const residueIds = residueTokens(pocket.residue_ids);
      const selection = residueIds.length ? residueSelection(residueIds[0]) : null;
      const state = { candidate: pocket.pocket ?? index + 1, entityA: selection ? selection.chain || null : null, entityB: null, token: selection ? selection.residue : null };
      context.selection?.set?.(state, tableWrap);
      // Mount the protein structure once, so the pocket can be read in context.
      if (structureArtifact && !structureOpened) {
        structureOpened = true;
        try { await services.openFile?.(structureArtifact); } catch (_error) { structureOpened = false; }
      }
      if (destroyed || generation !== selectionGeneration) return;
      if (services.setStructureGeometry) {
        if (!geometryToggle) {
          const label = document.createElement('label'); label.className = 'fpl-highlight'; geometryToggle = document.createElement('input'); geometryToggle.type = 'checkbox'; label.append(geometryToggle, ' Alpha spheres');
          const hint = document.createElement('span'); hint.className = 'fpl-geometry-hint'; hint.textContent = 'Recorded centres and radii';
          toolsSlot.querySelector('.structure-tool-secondary')?.prepend(label, hint);
          geometryToggle.onchange = async () => { geometryShown = geometryToggle.checked; const current = pockets[selectedIndex]; const file = geometry.get(pocketNumber(current.pocket) ?? selectedIndex + 1)?.spheres; try { await services.setStructureGeometry(geometryShown ? file : null); spatialStatus.textContent = 'Pocket ' + text(current.rank) + (geometryShown ? ' · recorded alpha spheres shown' : ' · whole structure context'); } catch (error) { geometryShown = false; geometryToggle.checked = false; spatialStatus.textContent = error.message; } };
        }
        const file = geometry.get(pocketNumber(pocket.pocket) ?? index + 1)?.spheres;
        geometryToggle.disabled = !file; geometryToggle.checked = geometryShown && !!file;
        try { await services.setStructureGeometry(geometryShown && file ? file : null); } catch (error) { if (generation === selectionGeneration) { geometryShown = false; geometryToggle.checked = false; spatialStatus.textContent = error.message; } }
      }
      if (destroyed || generation !== selectionGeneration) return;
      if (highlightContacts) selectResidues(residueIds);
      const target = focusSelection(pocket); services.annotateStructure?.(target ? { point: target.focusPoint, label: 'Pocket ' + text(pocket.rank || index + 1) } : null);
      if (pocketFocused) { const target = focusSelection(pocket); if (target) focusOnPocket(pocket, target); else { pocketFocused = false; services.resetStructure?.(); } }
    }
    // "Focus this pocket" focuses the pocket's own geometric centre; it does not
    // stand in a contacted residue for the centre.
    function focusOnPocket(pocket, target) {
      if (!focusStructure || !target) return false;
      pocketFocused = true; viewStatus.textContent = 'Pocket ' + text(pocket.rank) + ' focus · centroid';
      return focusStructure(target) || true;
    }
    // The contacted residues are sent as ONE collection, so the adapter applies a
    // single combined selection rather than N replacing selections.
    function selectResidues(residueIds) {
      if (!selectStructure) return false;
      const residues = residueIds
        .map((token) => residueSelection(token))
        .filter((entry) => entry && entry.residue != null)
        .map(toStructureSelection);
      return selectStructure({ residues }) || true;
    }

    return {
      destroy() {
        destroyed = true;
        controller.abort();
        host.replaceChildren();
      },
    };
  },
};
