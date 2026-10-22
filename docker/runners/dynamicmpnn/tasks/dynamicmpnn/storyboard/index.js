/* dynamicMPNN: the sampled designs and the backbone that conditioned them. */
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
    root.append(el('h2', '', 'Dynamic-conditioned designs'));
    root.append(el('p', 'sl-note', 'Each design is a model sample conditioned on the submitted backbone at the requested sampling temperature. The FASTA also carries the wild-type query, so the design is the record after it. Per-design confidence values (`overall_confidence`, `ligand_confidence`, `seq_rec`) are model scores, not measured success; independent folding and functional validation are still required.'));
    for (const view of views) {
      const section = el('section', 'sl-section'); section.dataset.viewId = view.id;
      section.append(el('h3', '', view.title));
      if (view.description) section.append(el('p', 'sl-note', view.description));
      const stage = el('div', 'sl-stage'); section.append(stage); root.append(section);
    }
    const downloads = el('div', 'sl-downloads'); downloads.setAttribute('role', 'group'); downloads.setAttribute('aria-label', 'Result downloads');
    const download = (id, label) => { const file = first(context, id); const button = el('button', '', label); button.type = 'button'; button.disabled = !file; button.onclick = () => file && services.downloadFile?.(file); downloads.append(button); };
    download('designs', 'Download designs (FASTA)');
    download('backbones', 'Download design backbone (PDB)');
    download('input_structure', 'Download input structure (PDB)');
    download('citations', 'Download citations (BibTeX)');
    const status = el('p', 'result-note', 'Loading the published designs…'); status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
    root.append(status, downloads); host.replaceChildren(root);
    let mounted = [];
    try {
      if (!services.mountView) throw new Error('The declared design view is unavailable.');
      for (const section of root.querySelectorAll('[data-view-id]')) {
        const view = views.find(item => item.id === section.dataset.viewId);
        mounted.push(await services.mountView(view.id, section.querySelector('.sl-stage'), abort.signal) || null);
      }
      status.textContent = 'The candidate source is the published FASTA; the backbone is the design\'s own coordinates.';
    } catch (error) {
      if (error.name !== 'AbortError') { status.textContent = 'The designs could not be rendered; the downloads above remain available.'; status.className = 'sl-error'; }
    }
    services.describeResult?.({ title: 'dynamicMPNN designs', subtitle: 'Backbone-conditioned sequence samples' });
    return { destroy() { abort.abort(); mounted.forEach(item => item?.destroy?.()); } };
  },
};
