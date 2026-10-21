/* LigandMPNN: ligand-context designs, the optional packed structure, and provenance. */
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
    root.append(el('h2', '', 'Ligand-aware designed sequences'));
    root.append(el('p', 'seq-note', 'Each published sequence is a model sample designed in the supplied ligand context. Ligand identity, atom records, and structure preparation all affect that context, and the FASTA headers carry the model\'s own overall and ligand confidence — model scores, not measured success. Designs still need independent folding and experimental validation.'));
    for (const view of views) {
      const section = el('section', 'seq-section'); section.dataset.viewId = view.id;
      section.append(el('h3', '', view.title));
      if (view.description) section.append(el('p', 'seq-note', view.description));
      section.append(el('div', 'seq-stage')); root.append(section);
    }
    const downloads = el('div', 'seq-downloads'); downloads.setAttribute('role', 'group'); downloads.setAttribute('aria-label', 'Result downloads');
    const download = (id, label) => { const file = first(context, id); const button = el('button', '', label); button.type = 'button'; button.disabled = !file; button.onclick = () => file && services.downloadFile?.(file); downloads.append(button); };
    download('designs', 'Download designed sequences (FASTA)');
    download('packed_structures', 'Download packed structure (PDB)');
    download('input_structure', 'Download input structure (PDB)');
    download('citations', 'Download citations (BibTeX)');
    const status = el('p', 'result-note', 'Loading the published sequences…'); status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
    root.append(status, downloads); host.replaceChildren(root);
    const mounted = [];
    try {
      if (!services.mountView) throw new Error('The declared sequence view is unavailable.');
      for (const section of root.querySelectorAll('[data-view-id]')) {
        mounted.push(await services.mountView(section.dataset.viewId, section.querySelector('.seq-stage'), abort.signal) || null);
      }
      status.textContent = first(context, 'packed_structures')
        ? 'Sequence identities are read from the published FASTA headers; the packed structure is offered for download.'
        : 'Sequence identities are read from the published FASTA headers. This run published no packed structure.';
    } catch (error) {
      if (error.name !== 'AbortError') { status.textContent = 'The sequences could not be rendered; the downloads above remain available.'; status.className = 'result-note seq-error'; }
    }
    return { destroy() { abort.abort(); mounted.forEach(item => item?.destroy?.()); } };
  },
};
