/* AutoDock Vina result storyboard: ranked poses, the run record, and the receptor context. */
/* SPDX-License-Identifier: GPL-3.0-only */

const STYLE = `
.vina-result{display:grid;gap:20px;min-width:0;color:var(--app-ink);font:14px/1.5 var(--font-sans)}
.vina-result h2,.vina-result h3,.vina-result h4,.vina-result p{margin:0}
.vina-result .btn{font:14px var(--font-sans);min-height:35px;padding:7px 11px;border:1px solid var(--app-line-strong);border-radius:4px;background:var(--app-raised);color:inherit;cursor:pointer}
.vina-result .btn:disabled{opacity:.55;cursor:default}
.vina-head{display:flex;flex-wrap:wrap;align-items:flex-end;gap:8px 24px;padding-bottom:16px;border-bottom:1px solid var(--app-line-strong)}
.vina-head h2{font:500 24px var(--font-display);letter-spacing:-.5px;width:100%}
.vina-head .vina-note{max-width:78ch}
.vina-eyebrow{font:10px var(--font-mono);letter-spacing:1.3px;text-transform:uppercase;color:var(--app-muted)}
.vina-note{color:var(--app-muted);font-size:14px;line-height:1.7}
.vina-caveat{padding:12px 14px;border:1px solid var(--app-line);border-left:3px solid var(--app-plum);border-radius:4px;background:var(--app-soft)}
.vina-layout{display:grid;grid-template-columns:minmax(0,1fr) 320px;gap:24px;min-width:0}
.vina-stage{position:relative;min-height:420px;border:1px solid var(--app-line);border-radius:8px;background:var(--app-stage);overflow:hidden}
.vina-stage-label{position:absolute;left:18px;top:14px;z-index:3;color:var(--app-muted);font-size:12px;pointer-events:none}
.vina-structure-slot{position:absolute;inset:40px 10px 10px}
.vina-structure-slot:empty::after{content:'Receptor structure not published';position:absolute;inset:0;display:grid;place-items:center;color:var(--app-muted);font-size:14px}
.vina-tools{position:absolute;right:12px;bottom:10px;z-index:4;display:flex;gap:8px}
.vina-inspector{min-width:0;display:flex;flex-direction:column;gap:16px}
.vina-inspector-head{border-bottom:1px solid var(--app-line-strong);padding-bottom:12px}
.vina-inspector-head h3{font:500 20px var(--font-display);letter-spacing:-.3px;margin-top:6px}
.vina-facts{display:grid;grid-template-columns:1fr;gap:10px;margin:0}
.vina-facts>div{display:flex;justify-content:space-between;gap:12px;border-bottom:1px solid var(--app-line);padding:5px 0}
.vina-facts dt{color:var(--app-muted)}
.vina-facts dd{margin:0;font:14px var(--font-mono);overflow-wrap:anywhere;text-align:right}
.vina-actions{display:flex;flex-wrap:wrap;gap:8px}
.vina-table-wrap{min-width:0;border:1px solid var(--app-line);border-radius:8px;overflow:auto;max-height:320px}
.vina-table{width:100%;min-width:640px;border-collapse:collapse;font-size:14px}
.vina-table th,.vina-table td{padding:10px 14px;text-align:left;border-bottom:1px solid var(--app-line);white-space:nowrap}
.vina-table th{position:sticky;top:0;background:var(--app-bg);color:var(--app-muted);font-weight:400}
.vina-table td{font:14px var(--font-mono)}
.vina-row{cursor:pointer}
.vina-row:focus-visible{outline:2px solid var(--app-plum);outline-offset:-2px}
.vina-row[aria-current=true] td{background:var(--app-soft)}
.vina-row[aria-current=true] td:first-child{box-shadow:inset 3px 0 var(--app-plum)}
.vina-score{font-weight:600}
.vina-empty{padding:18px;color:var(--app-muted)}
.vina-artifacts{border-top:1px solid var(--app-line-strong);padding-top:12px}
.vina-artifacts>summary{cursor:pointer;padding:8px 0;font-size:14px}
.vina-file-list{display:flex;flex-wrap:wrap;gap:8px;padding-top:8px}
@container(max-width:900px){.vina-layout{grid-template-columns:minmax(0,1fr)}.vina-stage{min-height:340px}}
`;

const list = value => Array.isArray(value) ? value : value ? [value] : [];
const first = (context, id) => list(context.files.get(id))[0] || null;
function el(tag, className = '', text) { const node = document.createElement(tag); node.className = className; if (text != null) node.textContent = String(text); return node; }
function text(value) { return value == null || value === '' ? '—' : String(value); }

// Parse the normalized scores.csv: one header row plus one row per ranked pose.
function parseCsv(source) {
  const rows = []; let row = []; let field = ''; let quoted = false;
  for (let index = 0; index < source.length; index += 1) {
    const character = source[index];
    if (quoted) {
      if (character === '"') { if (source[index + 1] === '"') { field += '"'; index += 1; } else quoted = false; }
      else field += character;
    } else if (character === '"') quoted = true;
    else if (character === ',') { row.push(field); field = ''; }
    else if (character === '\n') { row.push(field); rows.push(row); row = []; field = ''; }
    else if (character !== '\r') field += character;
  }
  if (field || row.length) { row.push(field); rows.push(row); }
  if (!rows.length) return [];
  const header = rows[0].map(name => name.trim());
  return rows.slice(1).filter(values => values.some(value => value !== ''))
    .map(values => Object.fromEntries(header.map((name, column) => [name, values[column]])));
}

// The normalizer records each pose's identity as "<pose file>#MODEL=<n>"; the file
// part is matched against the published pose names, never guessed from a name.
function poseIdentity(value) {
  const raw = String(value || '');
  const split = raw.indexOf('#');
  return split < 0 ? { file: raw, model: null } : { file: raw.slice(0, split), model: raw.slice(split + 1) || null };
}

// The published ranking is read from summary.json; no direction is claimed when
// the run did not record one.
function rankingText(summary) {
  const metric = summary && typeof summary.ranking_metric === 'string' ? summary.ranking_metric : null;
  const order = summary && typeof summary.ranking_order === 'string' ? summary.ranking_order : null;
  if (!metric || !order) return 'How poses were ranked was not published with this result.';
  const direction = order === 'ascending' ? 'lowest first' : order === 'descending' ? 'highest first' : order;
  return `Ranked by ${metric}, ${direction}, as published by the run.`;
}

export default {
  async mount(host, context) {
    const controller = new AbortController();
    const services = context.services || {};
    let destroyed = false;
    let rows = [];
    let selected = 0;
    let summary = null;
    let runRecord = null;

    const root = el('div', 'vina-result');
    const style = el('style'); style.textContent = STYLE; root.append(style);
    const header = el('header', 'vina-head');
    header.append(
      el('p', 'vina-eyebrow', 'Docking result'),
      el('h2', '', 'AutoDock Vina ranked poses'),
      el('p', 'vina-note', 'Each row is one binding mode Vina reported for the ligand it docked. Pose geometry is published as PDBQT, which this viewer does not parse, so poses are downloaded rather than drawn.'),
    );
    const caveat = el('p', 'vina-caveat', 'Vina scores are scoring-function estimates. They are not measured binding free energies or experimental affinities, and a lower Vina score is not evidence of a stronger binder.');
    caveat.dataset.vinaCaveat = 'score';
    const ranking = el('p', 'vina-note', 'Loading the pose ranking…'); ranking.dataset.vina = 'ranking';
    const status = el('p', 'vina-note', 'Loading the ranked pose table…'); status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');

    const layout = el('div', 'vina-layout');
    const stage = el('section', 'vina-stage');
    const stageLabel = el('div', 'vina-stage-label', 'Receptor input');
    const structureSlot = el('div', 'vina-structure-slot'); structureSlot.dataset.structureSlot = 'true';
    structureSlot.dataset.molecularWorkspace = 'true';
    const tools = el('div', 'vina-tools'); tools.dataset.structureTools = 'true';
    stage.append(stageLabel, structureSlot, tools);

    const inspector = el('aside', 'vina-inspector'); inspector.setAttribute('aria-label', 'Selected pose');
    const inspectorHead = el('div', 'vina-inspector-head');
    const inspectorTitle = el('h3', '', 'Select a pose');
    const inspectorStatus = el('p', 'vina-note', 'No pose selected.');
    inspectorHead.append(el('p', 'vina-eyebrow', 'Pose inspector'), inspectorTitle, inspectorStatus);
    const facts = el('dl', 'vina-facts');
    const actions = el('div', 'vina-actions');
    const runFacts = el('section'); runFacts.setAttribute('aria-label', 'Run record');
    const runTitle = el('h4', '', 'Run record');
    const runBody = el('dl', 'vina-facts');
    runFacts.append(runTitle, runBody);
    inspector.append(inspectorHead, facts, actions, runFacts);
    layout.append(stage, inspector);

    const tableWrap = el('div', 'vina-table-wrap');
    const artifacts = el('details', 'vina-artifacts');
    const artifactsTitle = el('summary', '', 'Downloads and published files');
    const fileList = el('div', 'vina-file-list');
    artifacts.append(artifactsTitle, fileList);
    root.append(header, caveat, ranking, tableWrap, status, layout, artifacts);
    host.replaceChildren(root);

    async function fetchText(file, limit = 1024 * 1024) {
      if (!file) return null;
      if (Number(file.size) > limit) throw new Error('The published file exceeds the preview limit.');
      const response = window.REvoDesignAuth
        ? await window.REvoDesignAuth.authFetch(file.url, { signal: controller.signal })
        : await fetch(file.url, { credentials: 'same-origin', signal: controller.signal });
      if (!response.ok) throw new Error('A published result file could not be loaded.');
      return response.text();
    }

    const download = (file, label) => {
      if (!file) return null;
      const button = el('button', 'btn', label); button.type = 'button';
      button.dataset.vinaDownload = file.id || label;
      button.addEventListener('click', () => services.downloadFile?.(file));
      return button;
    };
    for (const [id, label] of [['scores', 'Download scores (CSV)'], ['summary', 'Download summary (JSON)'], ['run_record', 'Download run record (JSON)'], ['citations', 'Download citations (BibTeX)']]) {
      const button = download(first(context, id), label); if (button) fileList.append(button);
    }
    for (const file of list(context.files.get('poses'))) {
      const button = download(file, 'Download ' + (file.name || 'pose PDBQT')); if (button) fileList.append(button);
    }
    for (const file of list(context.files.get('pose_logs'))) {
      const button = download(file, 'Download ' + (file.name || 'pose log')); if (button) fileList.append(button);
    }
    for (const file of list(context.files.get('prepared'))) {
      const button = download(file, 'Download ' + (file.name || 'prepared ligand')); if (button) fileList.append(button);
    }

    const views = list(context.views);
    if (typeof services.openView === 'function') {
      for (const view of views) {
        const button = el('button', 'btn', 'Open ' + view.title); button.type = 'button';
        button.dataset.viewId = view.id;
        button.addEventListener('click', () => { void services.openView(view.id); });
        fileList.append(button);
      }
    }

    // The receptor is the immutable input snapshot; it is the only structure this
    // Task publishes, so mounting it is the whole molecular context available.
    const receptor = first(context, 'receptor');
    let structureRequested = false;
    if (receptor && typeof services.openFile === 'function') {
      structureRequested = true;
      try { await services.openFile(receptor); }
      catch (_error) { structureRequested = false; }
    }

    async function loadRunRecord() {
      try {
        const raw = await fetchText(first(context, 'run_record'));
        if (raw) runRecord = JSON.parse(raw);
      } catch (error) { if (error.name === 'AbortError') throw error; runRecord = null; }
    }
    async function loadSummary() {
      try {
        const raw = await fetchText(first(context, 'summary'));
        if (raw) summary = JSON.parse(raw);
      } catch (error) { if (error.name === 'AbortError') throw error; summary = null; }
      ranking.textContent = rankingText(summary);
    }
    async function loadScores() {
      try {
        const raw = await fetchText(first(context, 'scores'));
        rows = raw ? parseCsv(raw) : [];
      } catch (error) {
        if (error.name === 'AbortError') throw error;
        tableWrap.replaceChildren(el('p', 'vina-empty', error.message || 'The ranked pose table could not be loaded.'));
        status.textContent = 'The pose table is unavailable; published files remain downloadable.';
        return;
      }
      renderTable();
    }

    function poseFor(entry) {
      const identity = poseIdentity(entry.pose_file);
      return list(context.files.get('poses')).find(file => (file.name || '') === identity.file) || null;
    }

    function renderTable() {
      if (!rows.length) {
        tableWrap.replaceChildren(el('p', 'vina-empty', 'Vina reported no poses for this run.'));
        status.textContent = 'No poses were reported.';
        return;
      }
      const table = el('table', 'vina-table');
      const head = el('thead'); const headRow = el('tr');
      for (const [key, label] of [['ligand', 'Ligand'], ['pose_rank', 'Rank'], ['affinity_kcal_mol', 'Vina score (kcal/mol)'], ['rmsd_lb_angstrom', 'RMSD lower bound (Å)'], ['rmsd_ub_angstrom', 'RMSD upper bound (Å)'], ['pose_file', 'Pose']]) {
        const cell = el('th', '', label); cell.scope = 'col'; headRow.append(cell);
      }
      head.append(headRow); table.append(head);
      const body = el('tbody');
      rows.forEach((entry, index) => {
        const row = el('tr', 'vina-row'); row.dataset.vinaRow = String(index); row.tabIndex = 0;
        row.setAttribute('role', 'button'); row.setAttribute('aria-current', String(index === selected));
        for (const key of ['ligand', 'pose_rank', 'affinity_kcal_mol', 'rmsd_lb_angstrom', 'rmsd_ub_angstrom', 'pose_file']) {
          const cell = el('td', key === 'affinity_kcal_mol' ? 'vina-score' : '', text(entry[key]));
          if (key === 'affinity_kcal_mol') cell.dataset.vinaScore = 'true';
          row.append(cell);
        }
        const activate = () => selectRow(index);
        row.addEventListener('click', activate);
        row.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); activate(); } });
        body.append(row);
      });
      table.append(body); tableWrap.replaceChildren(table);
      status.textContent = `${rows.length} ranked pose${rows.length === 1 ? '' : 's'} published.`;
      selectRow(selected);
    }

    function renderRunRecord() {
      runBody.replaceChildren();      const inputs = runRecord && runRecord.inputs && typeof runRecord.inputs === 'object' ? runRecord.inputs : {};
      const add = (label, value) => {
        if (value == null || value === '') return;
        const row = el('div'); row.append(el('dt', '', label), el('dd', '', value)); runBody.append(row);
      };
      for (const [role, entries] of Object.entries(inputs)) {
        for (const entry of list(entries)) {
          if (entry && typeof entry === 'object') add(role, entry.original_name || entry.relative_path || entry.path || null);
          else if (typeof entry === 'string') add(role, entry);
        }
      }
      const parameters = runRecord && runRecord.parameters && typeof runRecord.parameters === 'object' ? runRecord.parameters : {};
      for (const [name, value] of Object.entries(parameters)) {
        if (value == null || typeof value === 'object') continue;
        add(name, String(value));
      }
      if (!runBody.childElementCount) {
        const row = el('div'); row.append(el('dd', 'vina-empty', 'The run record was not published.')); runBody.append(row);
      }
    }

    function renderInspector() {
      const entry = rows[selected];
      facts.replaceChildren(); actions.replaceChildren();
      if (!entry) {
        inspectorTitle.textContent = 'Select a pose';
        inspectorStatus.textContent = rows.length ? 'Select a ranked pose to read its published values.' : 'No pose rows were published.';
        return;
      }
      const identity = poseIdentity(entry.pose_file);
      inspectorTitle.textContent = `Ligand ${text(entry.ligand)} · rank ${text(entry.pose_rank)}`;
      inspectorStatus.textContent = identity.model ? `Mode ${identity.model} of ${identity.file}` : text(identity.file);
      const add = (label, value) => {
        const row = el('div'); row.append(el('dt', '', label), el('dd', '', value)); facts.append(row);
      };
      add('Vina score (kcal/mol)', text(entry.affinity_kcal_mol));
      add('RMSD lower bound (Å)', text(entry.rmsd_lb_angstrom));
      add('RMSD upper bound (Å)', text(entry.rmsd_ub_angstrom));
      add('Ligand input', text(entry.ligand));
      add('Pose identity', text(entry.pose_file));
      if (summary) {
        if (summary.pose_count != null) add('Published poses', text(summary.pose_count));
        if (summary.ligand_count != null) add('Docked ligands', text(summary.ligand_count));
      }
      const pose = poseFor(entry);
      const poseButton = download(pose, pose ? 'Download ' + pose.name : 'Pose file not published');
      if (poseButton) { poseButton.dataset.vinaPoseDownload = 'true'; actions.append(poseButton); }
      else actions.append(el('p', 'vina-note', 'The pose file this row names was not published as a logical file.'));
      // The search box is the resolved parameter set, so focusing its centre is a
      // spatial fact of the run, not a claim about where the ligand binds.
      const parameters = runRecord && runRecord.parameters && typeof runRecord.parameters === 'object' ? runRecord.parameters : {};
      const centre = ['center_x', 'center_y', 'center_z'].map(axis => Number(parameters[axis]));
      if (structureRequested && centre.every(Number.isFinite) && typeof services.focusStructure === 'function') {
        const size = ['size_x', 'size_y', 'size_z'].map(axis => Number(parameters[axis])).filter(Number.isFinite);
        const radius = size.length === 3 ? Math.max(...size) / 2 : undefined;
        const focus = el('button', 'btn', 'Focus search box'); focus.type = 'button';
        focus.dataset.vinaFocus = 'true';
        focus.addEventListener('click', () => { services.focusStructure({ focusPoint: { x: centre[0], y: centre[1], z: centre[2], radius } }); services.annotateStructure?.({ point: { x: centre[0], y: centre[1], z: centre[2] }, label: 'Vina search box centre' }); });
        actions.append(focus);
      }
      if (structureRequested && receptor) {
        const reset = el('button', 'btn', 'Whole receptor'); reset.type = 'button'; reset.dataset.vinaReset = 'true';
        reset.addEventListener('click', () => { services.resetStructure?.(); services.annotateStructure?.(null); });
        actions.append(reset);
      }
    }
    function selectRow(index) {
      selected = index;
      const entry = rows[index];
      tableWrap.querySelectorAll('.vina-row').forEach(node => node.setAttribute('aria-current', node.dataset.vinaRow === String(index) ? 'true' : 'false'));
      renderInspector();
      if (entry) context.selection?.set?.({ candidate: String(entry.pose_file || index), entityA: null, entityB: null, token: null }, tableWrap);
    }

    try {
      await Promise.all([loadRunRecord(), loadSummary()]);
      if (destroyed) return { destroy() {} };
      renderRunRecord();
      await loadScores();
    } catch (error) {
      if (error.name !== 'AbortError') status.textContent = 'The published pose evidence could not be loaded; downloads remain available.';
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
