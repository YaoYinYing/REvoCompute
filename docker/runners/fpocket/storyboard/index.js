/* fpocket result storyboard: rank the detected pockets and read one pocket structurally. */
/* SPDX-License-Identifier: GPL-3.0-only */

const STYLE = `
.fpl-result { display: grid; gap: 1rem; padding: 1rem; min-width: 0; }
.fpl-result h2, .fpl-result h3, .fpl-result h4, .fpl-result p { margin: 0; }
.fpl-result h2 { font-family: var(--font-display); font-size: 1.35rem; font-weight: 600; }
.fpl-intro, .fpl-note, .fpl-unavailable { color: var(--muted); font-size: .82rem; line-height: 1.5; }
.fpl-unavailable { font-style: italic; }
.fpl-layout { display: grid; gap: 1.1rem; grid-template-columns: minmax(0, 1fr); min-width: 0; }
@media (min-width: 60rem) { .fpl-layout { grid-template-columns: minmax(0, 3fr) minmax(0, 2fr); } }
.fpl-section { display: grid; gap: .55rem; min-width: 0; align-content: start; }
.fpl-section h3 { font-size: .95rem; font-weight: 650; }
.fpl-section h4 { font-size: .85rem; font-weight: 600; }
.fpl-table-wrap { overflow: auto; max-width: 100%; }
table.fpl-pockets { border-collapse: collapse; width: 100%; font-size: .8rem; }
table.fpl-pockets th, table.fpl-pockets td { text-align: right; padding: .25rem .45rem; white-space: nowrap; border-bottom: 1px solid color-mix(in srgb, currentColor 15%, transparent); }
table.fpl-pockets th:first-child, table.fpl-pockets td:first-child { text-align: left; }
table.fpl-pockets thead th { position: sticky; top: 0; font-weight: 600; }
.fpl-pocket-row { cursor: pointer; }
.fpl-pocket-row:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
.fpl-pocket-row[aria-current="true"] { background: color-mix(in srgb, var(--accent) 16%, transparent); }
.fpl-pocket-row[aria-current="true"] td:first-child { font-weight: 650; }
.fpl-detail { display: grid; gap: .7rem; }
.fpl-actions { display: flex; flex-wrap: wrap; gap: .45rem; }
.fpl-metrics { display: grid; gap: .3rem; }
.fpl-pair { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: .5rem; align-items: baseline; }
.fpl-pair dt { font-size: .78rem; color: var(--muted); }
.fpl-pair dd { margin: 0; font-size: .9rem; text-align: right; }
.fpl-residues { display: flex; flex-wrap: wrap; gap: .25rem; }
.fpl-chip { padding: .05rem .4rem; border-radius: .5rem; font-size: .78rem; background: color-mix(in srgb, currentColor 10%, transparent); }
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
  { key: "alpha_spheres", label: "Alpha spheres" },
  { key: "volume_angstrom3", label: "Volume (A^3)" },
  { key: "total_sasa_angstrom2", label: "Total SASA (A^2)" },
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
  const match = /^([0-9]+)(.*)$/.exec(text.slice(split + 1));
  if (!match) return null;
  return { chain: chain || undefined, residue: Number(match[1]), insertionCode: match[2] || undefined };
}
function toStructureSelection(entry) {
  const selection = { chain: entry.chain, residue: entry.residue, numbering: "auth_seq_id" };
  if (entry.insertionCode) selection.insertionCode = entry.insertionCode;
  return selection;
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
    const heading = document.createElement("h2"); heading.textContent = "fpocket pockets";
    const intro = document.createElement("p"); intro.className = "fpl-intro";
    intro.textContent = "Candidate surface pockets fpocket detected on the submitted structure, in descending fpocket score order. "
      + "Selecting a pocket shows its fpocket-reported descriptors and the residues its alpha spheres contact; "
      + "the pocket can then be focused in the structure and its geometry files opened.";
    root.append(style, heading, intro);

    const layout = document.createElement("div"); layout.className = "fpl-layout";
    const selector = document.createElement("section"); selector.className = "fpl-section";
    const selectorTitle = document.createElement("h3"); selectorTitle.textContent = "Ranked pockets";
    const tableWrap = document.createElement("div"); tableWrap.className = "fpl-table-wrap";
    selector.append(selectorTitle, tableWrap);
    const detail = document.createElement("section"); detail.className = "fpl-section";
    const detailTitle = document.createElement("h3"); detailTitle.textContent = "Selected pocket";
    const detailBody = document.createElement("div"); detailBody.className = "fpl-detail";
    detail.append(detailTitle, detailBody);
    layout.append(selector, detail); root.append(layout);

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
      download.textContent = "Download pockets.csv"; download.dataset.fileId = pocketsFile.id;
      download.addEventListener("click", () => services.downloadFile?.(pocketsFile));
      genericActions.append(download);
    }
    generic.append(genericTitle, genericActions); root.append(generic);
    host.replaceChildren(root);

    // Pocket geometry files are optional: a result whose per-pocket files were
    // not published must still list and describe its pockets.
    const structureArtifact = first(context, "protein_structure");
    let structureOpened = false;
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
    renderEmptyDetail();

    function message(value, className) {
      const node = document.createElement("p"); node.className = className || "fpl-note"; node.textContent = value; return node;
    }
    function renderTable() {
      const table = document.createElement("table"); table.className = "fpl-pockets";
      const head = document.createElement("thead"); const headRow = document.createElement("tr");
      COLUMNS.forEach((column) => { const cell = document.createElement("th"); cell.scope = "col"; cell.textContent = column.label; headRow.append(cell); });
      head.append(headRow); table.append(head);
      const body = document.createElement("tbody");
      pockets.forEach((pocket, index) => {
        const row = document.createElement("tr"); row.className = "fpl-pocket-row";
        row.dataset.pocket = String(pocketNumber(pocket.pocket) ?? index + 1); row.tabIndex = 0;
        row.setAttribute("role", "button");
        COLUMNS.forEach((column) => { const cell = document.createElement("td"); cell.textContent = text(pocket[column.key]); row.append(cell); });
        row.addEventListener("click", () => selectPocket(index));
        row.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); selectPocket(index); } });
        body.append(row);
      });
      table.append(body); tableWrap.replaceChildren(table);
    }
    function renderEmptyDetail() {
      detailBody.replaceChildren(message("Select a pocket to see its fpocket-reported descriptors and contacted residues.", "fpl-note"));
    }

    // The pocket's own descriptor readout, then the structural interpretation:
    // focus the viewer on the pocket's geometric centre, highlight the residues
    // its alpha spheres contact, and open the contacted-atom / vertex files.
    function renderDetail(pocket, index) {
      const nodes = [];
      const pairList = document.createElement("dl"); pairList.className = "fpl-metrics";
      DETAIL.forEach((entry) => {
        if (pocket[entry.key] == null || pocket[entry.key] === "") return;
        const pair = document.createElement("div"); pair.className = "fpl-pair";
        const term = document.createElement("dt"); term.textContent = entry.label;
        const value = document.createElement("dd"); value.textContent = text(pocket[entry.key]);
        pair.append(term, value); pairList.append(pair);
      });
      if (pairList.childElementCount) nodes.push(pairList);

      const number = pocketNumber(pocket.pocket) ?? index + 1;
      const files = geometry.get(number) || {};
      const residueIds = residueTokens(pocket.residue_ids);
      const residueHeader = document.createElement("h4"); residueHeader.textContent = "Contacted residues (" + text(pocket.residue_count) + ")";
      nodes.push(residueHeader);
      if (residueIds.length) {
        const chips = document.createElement("div"); chips.className = "fpl-residues";
        residueIds.forEach((token) => { const chip = document.createElement("span"); chip.className = "fpl-chip"; chip.textContent = token; chips.append(chip); });
        nodes.push(chips);
      } else {
        nodes.push(message("No contacted residues were reported for this pocket.", "fpl-note"));
      }

      const actions = document.createElement("div"); actions.className = "fpl-actions";
      const target = focusSelection(pocket);
      if (target && focusStructure) {
        actions.append(actionButton("Focus this pocket", () => focusOnPocket(pocket, target)));
      }
      if (residueIds.length && selectStructure) {
        actions.append(actionButton("Select contacted residues", () => selectResidues(residueIds)));
      }
      if (files.contacts) actions.append(actionButton("Open contacted atoms", () => services.openFile?.(files.contacts)));
      if (files.spheres) actions.append(actionButton("Open alpha spheres", () => services.openFile?.(files.spheres)));
      if (structureArtifact && !structureOpened) actions.append(actionButton("Show structure", () => { structureOpened = true; return services.openFile?.(structureArtifact); }));
      if (actions.childElementCount) nodes.push(actions);
      if (!files.contacts && !files.spheres) {
        nodes.push(message("Pocket geometry files were not published, so only the reported descriptors are shown.", "fpl-note"));
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
      const [x, y, z] = ["center_x", "center_y", "center_z"].map((axis) => Number(pocket[axis]));
      if (![x, y, z].every((value) => Number.isFinite(value))) return null;
      const radius = Number(pocket.mean_alpha_sphere_radius_angstrom);
      return { focusPoint: { x, y, z, radius: Number.isFinite(radius) && radius > 0 ? radius * 2 : undefined } };
    }
    function selectPocket(index) {
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
        try { void services.openFile?.(structureArtifact); } catch (_error) { structureOpened = false; }
      }
    }
    // "Focus this pocket" focuses the pocket's own geometric centre; it does not
    // stand in a contacted residue for the centre.
    function focusOnPocket(pocket, target) {
      if (!focusStructure || !target) return false;
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
      if (!residues.length) return false;
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
