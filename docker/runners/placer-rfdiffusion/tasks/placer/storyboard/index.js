/* PLACER: protein–ligand complex samples and the scores that rank them. */
/* SPDX-License-Identifier: GPL-3.0-only */
const STYLE = `.pl-result{display:grid;gap:16px;min-width:0;font:14px/1.5 var(--font-sans)}.pl-result h2,.pl-result h3,.pl-result p{margin:0}.pl-result h2{font:500 24px var(--font-display)}.pl-section{display:grid;gap:8px;min-width:0}.pl-note{color:var(--app-muted);line-height:1.7;max-width:78ch}.pl-stage{border:1px solid var(--app-line);border-radius:8px;background:var(--app-surface);padding:12px;overflow:auto}.pl-stage:empty{display:none}.pl-structure{display:grid;grid-template-rows:minmax(0,1fr) auto;height:480px;border:1px solid var(--app-line);border-radius:8px;background:var(--app-stage);overflow:hidden}.pl-structure-slot{position:relative;min-height:0}.pl-structure-tools{background:var(--app-surface)}.pl-downloads{display:flex;flex-wrap:wrap;gap:8px}.pl-downloads button{font:14px var(--font-sans);min-height:34px;padding:7px 12px;border:1px solid var(--app-line-strong);border-radius:4px;color:var(--app-ink);background:var(--app-raised);cursor:pointer}`;
const list = value => Array.isArray(value) ? value : value ? [value] : [];
const first = (context, id) => list(context.files.get(id))[0] || null;
function el(tag, className = '', text) { const node = document.createElement(tag); node.className = className; if (text != null) node.textContent = String(text); return node; }

export default {
  async mount(host, context) {
    const services = context.services || {};
    const abort = new AbortController();
    const views = list(context.views);
    const root = el('div', 'pl-result');
    const style = el('style'); style.textContent = STYLE; root.append(style);
    root.append(el('h2', '', 'Sampled complex models'));
    root.append(el('p', 'pl-note', 'Every sampled placement is one MODEL in the published complex file, and the row with the same model_idx scores that MODEL. A single sample is a hypothesis, not a converged ensemble. The complex keeps the input\'s chain and residue numbering; a residue number absent from the complex was not placed in this sample, and this page never renumbers it.'));
    // The sampled complex is the run's own protein–ligand model. The declared
    // views list candidates and table rows and mount no viewer, so the complex
    // opens here, on the first screen.
    const complex = first(context, 'complexes');
    const structureNote = el('p', 'pl-note', complex ? `Loading ${complex.name || 'the sampled complex'}…` : 'This run published no complex model.');
    const structureStage = el('section', 'pl-structure');
    const structureSlot = el('div', 'pl-structure-slot'); structureSlot.dataset.structureSlot = 'true';
    const structureTools = el('div', 'pl-structure-tools'); structureTools.dataset.structureTools = 'true';
    structureStage.append(structureSlot, structureTools);
    root.append(structureNote);
    if (complex) root.append(structureStage);
    for (const view of views) {
      const section = el('section', 'pl-section'); section.dataset.viewId = view.id;
      section.append(el('h3', '', view.title));
      if (view.description) section.append(el('p', 'pl-note', view.description));
      section.append(el('div', 'pl-stage')); root.append(section);
    }
    const downloads = el('div', 'pl-downloads'); downloads.setAttribute('role', 'group'); downloads.setAttribute('aria-label', 'Result downloads');
    const download = (id, label) => { const file = first(context, id); const button = el('button', '', label); button.type = 'button'; button.disabled = !file; button.onclick = () => file && services.downloadFile?.(file); downloads.append(button); };
    download('complexes', 'Download complex models (PDB)');
    download('model_scores', 'Download model scores (CSV)');
    download('input_structures', 'Download input structures');
    download('citations', 'Download citations (BibTeX)');
    const status = el('p', 'result-note', 'Loading the published complex…'); status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
    root.append(status, downloads); host.replaceChildren(root);
    let structureMounted = false;
    if (complex && typeof services.openFile === 'function') {
      try { await services.openFile(complex); structureMounted = true; }
      catch (error) { if (error.name === 'AbortError') { structureStage.remove(); return { destroy() { abort.abort(); } }; } }
    }
    if (!structureMounted) structureStage.remove();
    structureNote.textContent = !complex ? 'This run published no complex model.'
      : structureMounted ? `The file ${complex.name || ''} holds the sampled placements published with this run.`
        : 'The complex could not be drawn here; it stays downloadable below.';
    const mounted = [];
    try {
      if (!services.mountView) throw new Error('The declared complex view is unavailable.');
      for (const section of root.querySelectorAll('[data-view-id]')) {
        mounted.push(await services.mountView(section.dataset.viewId, section.querySelector('.pl-stage'), abort.signal) || null);
      }
      status.textContent = 'Each score row names the MODEL it scores by model_idx.';
    } catch (error) {
      if (error.name !== 'AbortError') { status.textContent = 'The complex could not be rendered; the downloads above remain available.'; status.className = 'result-note'; }
    }
    return { destroy() { abort.abort(); mounted.forEach(item => item?.destroy?.()); } };
  },
};
