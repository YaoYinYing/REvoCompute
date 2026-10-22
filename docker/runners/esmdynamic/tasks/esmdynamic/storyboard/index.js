/* ESM Dynamic: the declared per-temperature predicted-dynamics evidence bundle. */
/* SPDX-License-Identifier: GPL-3.0-only */
const STYLE = `.sl-result{display:grid;gap:18px;min-width:0;font:14px/1.5 var(--font-sans)}.sl-result>*{min-width:0}.sl-result h2,.sl-result h3,.sl-result p{margin:0}.sl-result h2{font:500 24px var(--font-display);letter-spacing:-.5px}.sl-section{display:grid;gap:8px;min-width:0}.sl-section h3{font:500 18px var(--font-display)}.sl-note{color:var(--app-muted);line-height:1.7;max-width:78ch;white-space:pre-line}.sl-stage{border:1px solid var(--app-line);border-radius:8px;background:var(--app-surface);padding:12px;overflow-x:auto}.sl-stage:empty{display:none}.sl-error{padding:18px;color:var(--app-danger)}.sl-downloads{display:flex;flex-wrap:wrap;gap:8px}.sl-downloads button{font:14px var(--font-sans);min-height:34px;padding:7px 12px;border:1px solid var(--app-line-strong);border-radius:4px;color:var(--app-ink);background:var(--app-raised);cursor:pointer}`;
const list = value => Array.isArray(value) ? value : value ? [value] : [];
const first = (context, id) => list(context.files.get(id))[0] || null;
function el(tag, className = '', text) { const node = document.createElement(tag); node.className = className; if (text != null) node.textContent = String(text); return node; }

export default {
  async mount(host, context) {
    const services = context.services || {};
    const abort = new AbortController();
    const root = el('div', 'sl-result'), style = el('style'); style.textContent = STYLE; root.append(style);
    root.append(el('h2', '', 'Predicted contact dynamics'));
    root.append(el('p', 'sl-note', 'ESM Dynamic predicts contact dynamics from the sequence. The figures are model predictions at the temperatures listed in the runner output, not a molecular-dynamics trajectory, and the confidence values are model scores rather than measured probabilities. Plots at every reported temperature, the per-residue confidence tables and the probability arrays are available from the downloads below.'));
    const views = list(context.views);
    for (const view of views) {
      const section = el('section', 'sl-section'); section.dataset.viewId = view.id;
      section.append(el('h3', '', view.title));
      if (view.description) section.append(el('p', 'sl-note', view.description));
      const stage = el('div', 'sl-stage'); section.append(stage); root.append(section);
    }
    const downloads = el('div', 'sl-downloads'); downloads.setAttribute('role', 'group'); downloads.setAttribute('aria-label', 'Result downloads');
    const download = (id, label) => { const file = first(context, id); const button = el('button', '', label); button.type = 'button'; button.disabled = !file; button.onclick = () => file && services.downloadFile?.(file); downloads.append(button); };
    download('predicted_structure', 'Download predicted structure (PDB)');
    download('temperature_plots', 'Download dynamic plots (PNG)');
    download('confidence_tables', 'Download confidence tables (CSV)');
    download('plot_html', 'Download interactive plot (HTML)');
    download('input_sequence', 'Download input sequence (FASTA)');
    download('citations', 'Download citations (BibTeX)');
    const status = el('p', 'result-note', 'Loading the published dynamics evidence…'); status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
    root.append(status, downloads); host.replaceChildren(root);
    let mounted = [];
    try {
      if (!services.mountView) throw new Error('The declared dynamics views are unavailable.');
      for (const section of root.querySelectorAll('[data-view-id]')) {
        const view = views.find(item => item.id === section.dataset.viewId);
        mounted.push(await services.mountView(view.id, section.querySelector('.sl-stage'), abort.signal) || null);
      }
      const temperatures = [...new Set(list(context.files.get('temperature_plots')).flatMap(file => String(file.name || '').split('_')).filter(part => part.endsWith('K.png')).map(part => part.slice(0, -5)))];
      status.textContent = temperatures.length
        ? `The primary view shows the ${temperatures.join(', ')} K dynamic, frequency and kinetics plots; other temperatures are download-only.`
        : 'The primary view shows the reported-temperature dynamic, frequency and kinetics plots; other temperatures are download-only.';
    } catch (error) {
      if (error.name !== 'AbortError') { status.textContent = 'The dynamics evidence could not be rendered; the downloads above remain available.'; status.className = 'sl-error'; }
    }
    services.describeResult?.({ title: 'ESM Dynamic contact predictions', subtitle: 'Sequence-derived model predictions' });
    return { destroy() { abort.abort(); mounted.forEach(item => item?.destroy?.()); } };
  },
};
