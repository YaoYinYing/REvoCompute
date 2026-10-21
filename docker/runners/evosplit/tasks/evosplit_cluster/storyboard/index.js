/* EvoSplit: subfamily alignment clusters and their contact-probability matrix. */
/* SPDX-License-Identifier: GPL-3.0-only */
const STYLE = `.sl-result{display:grid;gap:18px;min-width:0;font:14px/1.5 var(--font-sans)}.sl-result>*{min-width:0}.sl-result h2,.sl-result h3,.sl-result p{margin:0}.sl-result h2{font:500 24px var(--font-display);letter-spacing:-.5px}.sl-section{display:grid;gap:8px;min-width:0}.sl-section h3{font:500 18px var(--font-display)}.sl-note{color:var(--app-muted);line-height:1.7;max-width:78ch;white-space:pre-line}.sl-stage{border:1px solid var(--app-line);border-radius:8px;background:var(--app-surface);padding:12px;overflow-x:auto}.sl-stage:empty{display:none}.sl-error{padding:18px;color:var(--app-danger)}.sl-downloads{display:flex;flex-wrap:wrap;gap:8px}.sl-downloads button{font:14px var(--font-sans);min-height:34px;padding:7px 12px;border:1px solid var(--app-line-strong);border-radius:4px;color:var(--app-ink);background:var(--app-raised);cursor:pointer}`;
const list = value => Array.isArray(value) ? value : value ? [value] : [];
const first = (context, id) => list(context.files.get(id))[0] || null;
function el(tag, className = '', text) { const node = document.createElement(tag); node.className = className; if (text != null) node.textContent = String(text); return node; }

export default {
  async mount(host, context) {
    const services = context.services || {};
    const abort = new AbortController();
    const views = list(context.views);
    const root = el('div', 'sl-result'), style = el('style'); style.textContent = STYLE; root.append(style);
    root.append(el('h2', '', 'Subfamily clustering and contact probabilities'));
    root.append(el('p', 'sl-note', 'EvoSplit clusters the input alignment into coevolution-derived subfamilies, then predicts per-residue-pair contact probabilities from the clustered alignment. Matrix values are model outputs on a 0–1 scale; higher values rank pairs as more likely to be in contact, but they are not a physical contact map, particularly at the toy alignment depths a small submission produces.'));
    for (const view of views) {
      const section = el('section', 'sl-section'); section.dataset.viewId = view.id;
      section.append(el('h3', '', view.title));
      if (view.description) section.append(el('p', 'sl-note', view.description));
      const stage = el('div', 'sl-stage'); section.append(stage); root.append(section);
    }
    const downloads = el('div', 'sl-downloads'); downloads.setAttribute('role', 'group'); downloads.setAttribute('aria-label', 'Result downloads');
    const download = (id, label) => { const file = first(context, id); const button = el('button', '', label); button.type = 'button'; button.disabled = !file; button.onclick = () => file && services.downloadFile?.(file); downloads.append(button); };
    download('contact_probabilities', 'Download contact matrix (CSV)');
    download('contact_map_image', 'Download contact map (PNG)');
    download('sequence_assignments', 'Download sequence assignments (CSV)');
    download('clustering_summary', 'Download summary (JSON)');
    download('cluster_alignments', 'Download cluster alignments (A3M)');
    download('processed_alignment', 'Download processed alignment (A3M)');
    download('input_alignment', 'Download input alignment (A3M)');
    download('citations', 'Download citations (BibTeX)');
    const status = el('p', 'result-note', 'Loading the published clustering and contact matrix…'); status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
    root.append(status, downloads); host.replaceChildren(root);
    let mounted = [];
    try {
      if (!services.mountView) throw new Error('The declared clustering views are unavailable.');
      for (const section of root.querySelectorAll('[data-view-id]')) {
        const view = views.find(item => item.id === section.dataset.viewId);
        mounted.push(await services.mountView(view.id, section.querySelector('.sl-stage'), abort.signal) || null);
      }
      status.textContent = 'Each sequence row is assigned to a cluster; the query anchors its own cluster and the reference columns are populated only in supervised mode.';
    } catch (error) {
      if (error.name !== 'AbortError') { status.textContent = 'The clustering result could not be rendered; the downloads above remain available.'; status.className = 'sl-error'; }
    }
    services.describeResult?.({ title: 'EvoSplit subfamily clustering', subtitle: 'Clusters and predicted contact probabilities' });
    return { destroy() { abort.abort(); mounted.forEach(item => item?.destroy?.()); } };
  },
};
