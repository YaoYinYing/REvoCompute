/* FA-MPNN design: jointly sampled sequences and full-atom structures. */
/* SPDX-License-Identifier: GPL-3.0-only */
const STYLE = `.seq-result{display:grid;gap:16px;min-width:0;font:14px/1.5 var(--font-sans)}.seq-result h2,.seq-result h3,.seq-result p{margin:0}.seq-result h2{font:500 24px var(--font-display)}.seq-section{display:grid;gap:8px;min-width:0}.seq-note{color:var(--app-muted);line-height:1.7;max-width:78ch}.seq-stage{border:1px solid var(--app-line);border-radius:8px;background:var(--app-surface);padding:12px;overflow-x:auto}.seq-stage:empty{display:none}.seq-downloads{display:flex;flex-wrap:wrap;gap:8px}.seq-downloads button{font:14px var(--font-sans);min-height:34px;padding:7px 12px;border:1px solid var(--app-line-strong);border-radius:4px;color:var(--app-ink);background:var(--app-raised);cursor:pointer}`;
const list = value => Array.isArray(value) ? value : value ? [value] : [];
const first = (context, id) => list(context.files.get(id))[0] || null;
function el(tag, className = '', text) { const node = document.createElement(tag); node.className = className; if (text != null) node.textContent = String(text); return node; }

export default {
  async mount(host, context) {
    const services = context.services || {};
    const abort = new AbortController();
    const views = list(context.views);
    const root = el('div', 'seq-result');
    const style = el('style'); style.textContent = STYLE; root.append(style);
    root.append(el('h2', '', 'Full-atom sequence designs'));
    root.append(el('p', 'seq-note', 'FA-MPNN samples each design\'s sequence and its compatible full-atom side-chain conformation together. The structure\'s B-factor field carries the model\'s own per-atom confidence, not a measured quality, and every design still needs independent validation.'));
    for (const view of views) {
      const section = el('section', 'seq-section'); section.dataset.viewId = view.id;
      section.append(el('h3', '', view.title));
      if (view.description) section.append(el('p', 'seq-note', view.description));
      section.append(el('div', 'seq-stage')); root.append(section);
    }
    const downloads = el('div', 'seq-downloads'); downloads.setAttribute('role', 'group'); downloads.setAttribute('aria-label', 'Result downloads');
    const download = (id, label) => { const file = first(context, id); const button = el('button', '', label); button.type = 'button'; button.disabled = !file; button.onclick = () => file && services.downloadFile?.(file); downloads.append(button); };
    download('structures', 'Download design structures (PDB)');
    download('designs', 'Download designed sequences (FASTA)');
    download('samples', 'Download serialized samples (PKL)');
    download('config', 'Download run configuration (YAML)');
    download('input_structure', 'Download input structure (PDB)');
    download('citations', 'Download citations (BibTeX)');
    const status = el('p', 'result-note', 'Loading the published designs…'); status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
    root.append(status, downloads); host.replaceChildren(root);
    const mounted = [];
    try {
      if (!services.mountView) throw new Error('The declared design view is unavailable.');
      for (const section of root.querySelectorAll('[data-view-id]')) {
        mounted.push(await services.mountView(section.dataset.viewId, section.querySelector('.seq-stage'), abort.signal) || null);
      }
      status.textContent = 'The FASTA header and the structure filename carry the same published sample name.';
    } catch (error) {
      if (error.name !== 'AbortError') { status.textContent = 'The designs could not be rendered; the downloads above remain available.'; status.className = 'result-note seq-error'; }
    }
    return { destroy() { abort.abort(); mounted.forEach(item => item?.destroy?.()); } };
  },
};
