/* PPIformer per-residue interface embeddings and their index. */
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
    root.append(el('h2', '', 'Interface residue embeddings'));
    root.append(el('p', 'sl-note', 'One row per residue of the submitted complex, keyed by chain, residue number and insertion code. `embedding_norm` is the Euclidean norm of that residue\'s 128-dimensional PPIformer vector; it describes the learned representation, not affinity or stability. The full arrays are published as opaque NumPy files for download.'));
    for (const view of views) {
      const section = el('section', 'sl-section'); section.dataset.viewId = view.id;
      section.append(el('h3', '', view.title));
      if (view.description) section.append(el('p', 'sl-note', view.description));
      const stage = el('div', 'sl-stage'); section.append(stage); root.append(section);
    }
    const downloads = el('div', 'sl-downloads'); downloads.setAttribute('role', 'group'); downloads.setAttribute('aria-label', 'Result downloads');
    const download = (id, label) => { const file = first(context, id); const button = el('button', '', label); button.type = 'button'; button.disabled = !file; button.onclick = () => file && services.downloadFile?.(file); downloads.append(button); };
    download('residue_index', 'Download residue index (CSV)');
    download('residue_embeddings', 'Download residue embeddings (NPY)');
    download('interface_embedding', 'Download interface embedding (NPY)');
    download('embedding_summary', 'Download embedding summary (JSON)');
    download('run_metadata', 'Download run metadata (JSON)');
    download('input_complex', 'Download input complex (PDB)');
    download('citations', 'Download citations (BibTeX)');
    const status = el('p', 'result-note', 'Loading the published residue index…'); status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
    root.append(status, downloads); host.replaceChildren(root);
    let mounted = [];
    try {
      if (!services.mountView) throw new Error('The declared embedding views are unavailable.');
      for (const section of root.querySelectorAll('[data-view-id]')) {
        const view = views.find(item => item.id === section.dataset.viewId);
        mounted.push(await services.mountView(view.id, section.querySelector('.sl-stage'), abort.signal) || null);
      }
      status.textContent = '`embedding_norm` is the norm of the per-residue vector; it is not a score or an affinity.';
    } catch (error) {
      if (error.name !== 'AbortError') { status.textContent = 'The embeddings could not be rendered; the downloads above remain available.'; status.className = 'sl-error'; }
    }
    services.describeResult?.({ title: 'PPIformer interface embeddings', subtitle: 'Per-residue learned representations' });
    return { destroy() { abort.abort(); mounted.forEach(item => item?.destroy?.()); } };
  },
};
