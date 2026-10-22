/* BioEmu result composition: the sampled ensemble, its provenance, and its limits. */
/* SPDX-License-Identifier: GPL-3.0-only */
const STYLE = `
.be-result{display:grid;gap:18px;min-width:0;font:14px/1.5 var(--font-sans)}
.be-result>*{min-width:0}.be-result h2,.be-result h3,.be-result p{margin:0}
.be-result h2{font:500 24px var(--font-display);letter-spacing:-.5px}.be-result h3{font:500 18px var(--font-display)}
.be-facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px 24px;margin:0}
.be-facts>div{padding:10px 0;border-bottom:1px solid var(--app-line-strong)}.be-facts dt{font-size:12px;color:var(--app-muted)}.be-facts dd{margin:4px 0 0;font:14px var(--font-mono);overflow-wrap:anywhere}
.be-note{font-size:14px;line-height:1.7;color:var(--app-muted);max-width:78ch}
.be-stage{min-width:0;border:1px solid var(--app-line);border-radius:8px;overflow:hidden;background:var(--app-surface)}
.be-stage:empty{display:none}.be-stage .trajectory-viewport{border:0}
.be-error{padding:18px;color:var(--app-danger)}
.be-downloads{display:flex;flex-wrap:wrap;gap:8px}.be-downloads button{font:14px var(--font-sans);min-height:34px;padding:7px 12px;border:1px solid var(--app-line-strong);border-radius:4px;color:var(--app-ink);background:var(--app-raised);cursor:pointer}
`;
const list = value => Array.isArray(value) ? value : value ? [value] : [];
const first = (context, id) => list(context.files.get(id))[0] || null;
function el(tag, className = '', text) { const node = document.createElement(tag); node.className = className; if (text != null) node.textContent = String(text); return node; }
function fact(label, value) { const row = el('div'); row.append(el('dt', '', label), el('dd', '', value)); return row; }

export default {
  async mount(host, context) {
    const services = context.services || {};
    const abort = new AbortController();
    const root = el('div', 'be-result'), style = el('style'); style.textContent = STYLE; root.append(style);
    const header = el('header'); header.append(
      el('h2', '', 'Sampled conformational ensemble'),
      el('p', 'be-note', 'BioEmu generates conformations from the sequence with a generative diffusion emulation; each published frame is one accepted sample.'),
    );
    const facts = el('dl', 'be-facts');
    const published = fact('Published samples', '—'); published.dataset.bioemu = 'published-samples';
    const input = fact('Input sequence', '—'); input.dataset.bioemu = 'input-sequence';
    const method = fact('Method', 'BioEmu equilibrium-ensemble emulation');
    facts.append(published, input, method);
    const caution = el('p', 'be-note', 'Generated samples are model predictions, not measured kinetics or calibrated thermodynamic populations. Sample order is generation order, not physical time.');
    const filtered = el('p', 'be-note', 'Only samples that pass BioEmu\'s physical-validity filter are published, so the published count can be lower than the number of draws requested.');
    const status = el('p', 'result-note be-status', 'Loading the sampled ensemble…'); status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
    const stage = el('div', 'be-stage');
    const downloads = el('div', 'be-downloads'); downloads.setAttribute('role', 'group'); downloads.setAttribute('aria-label', 'Result downloads');
    const download = (id, label) => { const file = first(context, id); const button = el('button', '', label); button.type = 'button'; button.dataset.download = id; button.disabled = !file; button.onclick = () => file && services.downloadFile?.(file); downloads.append(button); };
    download('coordinates', 'Download sampled frames (XTC)');
    download('topology', 'Download topology (PDB)');
    download('sequence', 'Download input sequence (FASTA)');
    download('citations', 'Download citations (BibTeX)');
    root.append(header, facts, caution, filtered, stage, status, downloads);
    host.replaceChildren(root);

    // Every failure the reader can see must name the file and the reason: a
    // silent null would leave the row showing the "not yet known" dash.
    function fastaLabel(fasta, name) {
      const records = fasta.split(/\r?\n/).filter(line => line.startsWith('>'));
      const residues = fasta.split(/\r?\n/).filter(line => !line.startsWith('>')).join('').replace(/[^A-Za-z]/g, '').length;
      return `${records[0]?.slice(1).trim() || name} · ${residues} residues`;
    }
    async function fetchText(file) {
      if (!file) throw new Error('No input sequence is published.');
      const name = file.name || 'The input file';
      if (Number(file.size) > 1024 * 1024) throw new Error(`${name} is too large to read inline.`);
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
      return (await response.text()).slice(0, 1024 * 1024);
    }
    // Start the read in parallel with the view, but settle it immediately: a
    // floating rejection would surface as an unhandled page error before the
    // row that reports it runs.
    const sequenceRead = fetchText(first(context, 'sequence')).then(text => ({ text }), error => ({ error }));
    const views = list(context.views), view = views.find(item => item.plugin === 'trajectory');
    let embedded = null;
    try {
      if (view && services.mountView) embedded = await services.mountView(view.id, stage, abort.signal) || null;
      else if (!view) throw new Error('This result declares no trajectory view.');
      else throw new Error('The shared trajectory view is unavailable.');
      const count = embedded && embedded.frameCount;
      if (Number.isFinite(count)) {
        const unit = view.mapping && view.mapping.frame_unit === 'sample' ? 'samples' : 'frames';
        published.lastElementChild.textContent = `${count} ${unit} · ${first(context, 'coordinates')?.name || 'coordinates'}`;
        status.textContent = `${count} ${unit} published. Use the sample controls to step through them.`;
      } else status.textContent = 'The sampled ensemble is ready.';
    } catch (error) {
      if (error.name !== 'AbortError') stage.replaceChildren(el('p', 'be-error', error.message));
      status.textContent = 'The inline ensemble could not be shown; the downloads below remain available.';
    }
    const { text: fasta, error: sequenceError } = await sequenceRead;
    if (sequenceError) {
      if (sequenceError.name !== 'AbortError') input.lastElementChild.textContent = sequenceError.message;
    } else input.lastElementChild.textContent = fastaLabel(fasta, first(context, 'sequence')?.name);
    return { destroy() { abort.abort(); embedded?.destroy?.(); } };
  },
};
