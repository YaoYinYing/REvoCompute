/* BioEmu2 result composition: the sampled ensemble and upstream's per-frame physicality verdict, side by side. */
/* SPDX-License-Identifier: GPL-3.0-only */
const STYLE = `
.be2-result{display:grid;gap:16px;min-width:0;color:var(--app-ink);font:14px/1.5 var(--font-sans)}
.be2-result h2,.be2-result h3,.be2-result p{margin:0}
.be2-head{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 18px}
.be2-head h2{font:500 26px var(--font-display);letter-spacing:-.5px;width:100%}
.be2-note{color:var(--app-muted);font-size:14px;line-height:1.7;max-width:78ch}
.be2-verdict{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:2px;padding:4px;border:1px solid var(--app-line);border-radius:8px;background:var(--app-raised)}
.be2-verdict>div{display:grid;gap:2px;padding:10px 16px}
.be2-verdict dt{font-size:12px;color:var(--app-muted)}
.be2-verdict dd{margin:0;font:500 19px var(--font-mono);overflow-wrap:anywhere}
.be2-verdict dd .be2-unit{font:400 12px var(--font-sans);color:var(--app-muted);margin-left:5px}
.be2-hero{display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:18px;min-width:0;align-items:stretch}
.be2-stage{position:relative;min-width:0;min-height:600px;border:1px solid var(--app-line);border-radius:8px;overflow:hidden;background:var(--app-stage)}
.be2-stage:empty::after{content:'The sampled ensemble is not shown';position:absolute;inset:0;display:grid;place-items:center;color:var(--app-muted);font-size:14px}
.be2-stage .trajectory-viewport{border:0;height:100%;min-height:600px}
.be2-side{min-width:0;display:grid;gap:14px;align-content:start}
.be2-section{display:grid;gap:8px;min-width:0}
.be2-section h3{font:500 18px var(--font-display);letter-spacing:-.2px}
.be2-table-wrap{min-width:0;border:1px solid var(--app-line);border-radius:6px;overflow:auto;max-height:300px}
.be2-table{width:100%;border-collapse:collapse;font-size:13px}
.be2-table th,.be2-table td{padding:7px 11px;text-align:left;border-bottom:1px solid var(--app-line);white-space:nowrap}
.be2-table th{position:sticky;top:0;background:var(--app-bg);color:var(--app-muted);font-weight:400}
.be2-table td{font:13px var(--font-mono)}
.be2-state{font-weight:600}
.be2-state[data-status=rejected]{color:var(--app-danger)}
.be2-empty{padding:14px;color:var(--app-muted);font-size:13px;line-height:1.6}
.be2-caveat{padding:10px 12px;border:1px solid var(--app-line);border-left:3px solid var(--app-plum);border-radius:4px;background:var(--app-soft);font-size:13px;line-height:1.6;color:var(--app-muted)}
.be2-foot{display:grid;gap:12px;padding-top:14px;border-top:1px solid var(--app-line-strong)}
.be2-facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:0 24px;margin:0}
.be2-facts>div{display:flex;justify-content:space-between;gap:14px;padding:6px 0;border-bottom:1px solid var(--app-line)}
.be2-facts dt{color:var(--app-muted);font-size:13px}
.be2-facts dd{margin:0;font:13px var(--font-mono);overflow-wrap:anywhere;text-align:right}
.be2-downloads{display:flex;flex-wrap:wrap;gap:8px}
.be2-downloads button{font:14px var(--font-sans);min-height:34px;padding:7px 12px;border:1px solid var(--app-line-strong);border-radius:4px;color:var(--app-ink);background:var(--app-raised);cursor:pointer}
.be2-downloads button:disabled{opacity:.55;cursor:default}
.be2-error{padding:16px;color:var(--app-danger)}
@container(max-width:980px){.be2-hero{grid-template-columns:minmax(0,1fr)}.be2-stage,.be2-stage .trajectory-viewport{min-height:420px}}
`;

const list = value => Array.isArray(value) ? value : value ? [value] : [];
const first = (context, id) => list(context.files.get(id))[0] || null;
function el(tag, className = '', text) { const node = document.createElement(tag); node.className = className; if (text != null) node.textContent = String(text); return node; }
function text(value) { return value == null || value === '' ? '—' : String(value); }
function metric(label, value, unit) {
  const row = el('div');
  const term = el('dt', '', label), definition = el('dd', '', value);
  if (unit) definition.append(el('span', 'be2-unit', unit));
  return row.append(term, definition), row;
}
function factRow(label, value) { const row = el('div'); row.append(el('dt', '', label), el('dd', '', value)); return row; }

export default {
  async mount(host, context) {
    const services = context.services || {};
    const abort = new AbortController();
    const root = el('div', 'be2-result'), style = el('style'); style.textContent = STYLE; root.append(style);

    const head = el('header', 'be2-head');
    head.append(
      el('h2', '', 'BioEmu2 equilibrium ensemble'),
      el('p', 'be2-note', 'Each published sample is one conformation drawn by the released BioEmu2 checkpoint from the input sequence. Sample order is generation order, not physical time.'),
    );

    // The headline numbers are read from the published files, not from the
    // submitted parameters: the page describes what this run published.
    const verdict = el('dl', 'be2-verdict');
    const framesMetric = metric('Published samples', '—'); framesMetric.dataset.bioemu2 = 'frames';
    const acceptedMetric = metric('Physicality', '—'); acceptedMetric.dataset.bioemu2 = 'physicality';
    const coordinateMetric = metric('Coordinates', '—'); coordinateMetric.dataset.bioemu2 = 'coordinates';
    verdict.append(framesMetric, acceptedMetric, coordinateMetric);

    // Ensemble and physicality share the first screen: the structure is the
    // result, and the per-sample verdict is the qualifier a reader needs beside
    // it, not a paragraph or a table further down the page.
    const hero = el('div', 'be2-hero');
    const stage = el('div', 'be2-stage');
    const side = el('aside', 'be2-side');
    side.setAttribute('aria-label', 'Per-sample physicality');

    const physicalitySection = el('section', 'be2-section');
    const tableWrap = el('div', 'be2-table-wrap');
    physicalitySection.append(el('h3', '', 'Per-sample physicality'), tableWrap);

    const caveat = el('p', 'be2-caveat', 'Upstream\'s physicality check is a report, not a filter: every generated sample is published and none is removed. A sample marked rejected failed a bond-length, clash, chirality or chain-break threshold and must not be read as a physically valid conformation. The released checkpoint is a preview, so treat small-sample runs as contract demonstrations rather than converged ensembles.');

    side.append(physicalitySection, caveat);
    hero.append(stage, side);

    const status = el('p', 'result-note be2-status', 'Loading the sampled ensemble…');
    status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');

    const foot = el('div', 'be2-foot');
    const systemFacts = el('dl', 'be2-facts');
    const modeFact = factRow('Sampling mode', '—'); modeFact.dataset.bioemu2 = 'mode';
    const entityFact = factRow('Entity', '—'); entityFact.dataset.bioemu2 = 'entity';
    const sequenceFact = factRow('Input sequence', '—'); sequenceFact.dataset.bioemu2 = 'sequence';
    systemFacts.append(modeFact, entityFact, sequenceFact);
    const downloads = el('div', 'be2-downloads'); downloads.setAttribute('role', 'group'); downloads.setAttribute('aria-label', 'Result downloads');
    const download = (id, label) => {
      const file = first(context, id); const button = el('button', '', label); button.type = 'button';
      button.dataset.download = id; button.disabled = !file;
      button.onclick = () => file && services.downloadFile?.(file);
      downloads.append(button);
    };
    download('coordinates', 'Download sampled frames (XTC)');
    download('topology', 'Download topology (PDB)');
    download('upstream_topology', 'Download upstream topology (CIF)');
    download('physicality', 'Download physicality report (JSON)');
    download('system', 'Download sampling system (YAML)');
    download('sequence', 'Download input sequence (FASTA)');
    foot.append(systemFacts, downloads);

    root.append(head, verdict, hero, status, foot);
    host.replaceChildren(root);

    async function fetchText(file, limit) {
      if (!file) return null;
      const name = file.name || 'The published file';
      if (Number(file.size) > limit) throw new Error(`${name} is too large to read inline.`);
      let response;
      try {
        response = window.REvoDesignAuth
          ? await window.REvoDesignAuth.authFetch(file.url, { signal: abort.signal })
          : await fetch(file.url, { credentials: 'same-origin', signal: abort.signal });
      } catch (error) {
        if (error.name === 'AbortError') throw error;
        throw new Error(`${name} could not be fetched: ${error.message}`);
      }
      if (!response.ok) throw new Error(`${name} could not be read (HTTP ${response.status}).`);
      return (await response.text()).slice(0, limit);
    }
    // A reader that fails names the file and the reason in the row it feeds, and
    // settles here so a rejection never escapes as an unhandled page error.
    const read = (file, limit) => fetchText(file, limit).then(value => ({ value }), error => ({ error }));

    const physicalityRead = read(first(context, 'physicality'), 1024 * 1024);
    const systemRead = read(first(context, 'system'), 256 * 1024);

    // Upstream writes a JSON array, one entry per published sample:
    // {"frame": n, "status": "passed" | "rejected" | "not_checked", "reason": "..."}.
    // The status and reason are upstream's own vocabulary and are shown verbatim.
    function renderPhysicality(report) {
      tableWrap.replaceChildren();
      if (!Array.isArray(report) || report.length === 0) {
        tableWrap.append(el('p', 'be2-empty', 'The physicality report lists no samples.'));
        acceptedMetric.lastElementChild.textContent = 'no samples reported';
        return;
      }
      const table = el('table', 'be2-table');
      const headRow = el('tr');
      for (const label of ['Sample', 'Status', 'Reason']) headRow.append(el('th', '', label));
      const body = el('tbody');
      for (const entry of report) {
        const state = text(entry.status);
        const row = el('tr');
        const stateCell = el('td', 'be2-state', state); stateCell.dataset.status = state;
        row.append(el('td', '', text(entry.frame)), stateCell, el('td', '', text(entry.reason)));
        body.append(row);
      }
      table.append(headRow, body);
      tableWrap.append(table);
      const statuses = report.map(entry => text(entry.status));
      const accepted = statuses.filter(status => status === 'passed').length;
      const unchecked = statuses.filter(status => status === 'not_checked').length;
      const definition = el('dd', '', `${accepted} of ${report.length} accepted`);
      if (unchecked) definition.append(el('span', 'be2-unit', `${unchecked} not checked`));
      acceptedMetric.replaceChildren(el('dt', '', 'Physicality'), definition);
    }

    // system.yaml is upstream's resolved system: the protein entity and the
    // sampling mode. Only the facts this page states are read, and an
    // unreadable file says so rather than guessing.
    function renderSystem(source) {
      if (source == null) return;
      const entity = /entity_type:\s*(\S+)/.exec(source);
      const mode = /^mode:\s*(\S+)/m.exec(source);
      if (mode) modeFact.lastElementChild.textContent = text(mode[1]);
      if (entity) entityFact.lastElementChild.textContent = text(entity[1]);
    }

    // The ensemble itself is the declared trajectory view: a persistent Mol*
    // stage with previous/next and a scrubber over the samples.
    const views = list(context.views);
    const view = views.find(item => item.plugin === 'trajectory' && item.role === 'primary')
      || views.find(item => item.plugin === 'trajectory');
    let embedded = null;
    try {
      if (!view || !services.mountView) throw new Error('The sampled-ensemble trajectory view is unavailable.');
      embedded = await services.mountView(view.id, stage, abort.signal) || null;
      const count = embedded && embedded.frameCount;
      if (Number.isFinite(count)) {
        framesMetric.lastElementChild.textContent = String(count);
        coordinateMetric.lastElementChild.textContent = first(context, 'coordinates')?.name || 'not published';
        status.textContent = `${count} samples published. Use the sample controls to step through them.`;
      } else status.textContent = 'The sampled ensemble is ready.';
    } catch (error) {
      if (error.name !== 'AbortError') stage.replaceChildren(el('p', 'be2-error', error.message));
      status.textContent = 'The inline ensemble could not be shown; the downloads below remain available.';
    }

    const { value: report, error: reportError } = await physicalityRead;
    if (reportError) {
      if (reportError.name !== 'AbortError') {
        tableWrap.replaceChildren(el('p', 'be2-empty', reportError.message));
        acceptedMetric.lastElementChild.textContent = 'report unavailable';
      }
    } else {
      try { renderPhysicality(JSON.parse(report)); }
      catch (error) {
        if (error.name === 'AbortError') throw error;
        tableWrap.replaceChildren(el('p', 'be2-empty', 'The physicality report could not be parsed as JSON.'));
        acceptedMetric.lastElementChild.textContent = 'report unreadable';
      }
    }

    const { value: system, error: systemError } = await systemRead;
    if (systemError) {
      if (systemError.name !== 'AbortError') modeFact.lastElementChild.textContent = systemError.message;
    } else renderSystem(system);

    const sequence = first(context, 'sequence');
    sequenceFact.lastElementChild.textContent = sequence ? (sequence.name || 'published FASTA') : 'not published';

    return { destroy() { abort.abort(); embedded?.destroy?.(); } };
  },
};
