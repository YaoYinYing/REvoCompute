/* LASErMPNN: all-atom designs, their sequences, and the protonation caveat. */
/* SPDX-License-Identifier: GPL-3.0-only */
const STYLE = `.seq-result{display:grid;gap:16px;min-width:0;font:14px/1.5 var(--font-sans)}.seq-result h2,.seq-result h3,.seq-result p{margin:0}.seq-result h2{font:500 24px var(--font-display)}.seq-section{display:grid;gap:8px;min-width:0}.seq-note{color:var(--app-muted);line-height:1.7;max-width:78ch}.seq-stage{border:1px solid var(--app-line);border-radius:8px;background:var(--app-surface);padding:12px;overflow-x:auto}.seq-stage:empty{display:none}.seq-structure{display:grid;grid-template-rows:minmax(0,1fr) auto;height:480px;border:1px solid var(--app-line);border-radius:8px;background:var(--app-stage);overflow:hidden}.seq-structure-slot{position:relative;min-height:0}.seq-structure-tools{background:var(--app-surface)}.seq-downloads{display:flex;flex-wrap:wrap;gap:8px}.seq-downloads button{font:14px var(--font-sans);min-height:34px;padding:7px 12px;border:1px solid var(--app-line-strong);border-radius:4px;color:var(--app-ink);background:var(--app-raised);cursor:pointer}`;
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
    root.append(el('h2', '', 'Ligand-conditioned designs'));
    root.append(el('p', 'seq-note', 'Each design is a model sample with its own all-atom structure and matching sequence. The intended LASErMPNN contract expects all-atom, protonated inputs; a design from a lighter input is still a hypothesis that needs independent folding and experimental validation.'));
    // The design structure is published as its own all-atom PDB. The declared
    // view is a candidate list with no viewer, so the structure opens here, on
    // the first screen, as the drawing of the same published design.
    const structure = first(context, 'designs');
    const structureNote = el('p', 'seq-note', structure ? `Loading ${structure.name || 'the design structure'}…` : 'This run published no design structure.');
    const structureStage = el('section', 'seq-structure');
    const structureSlot = el('div', 'seq-structure-slot'); structureSlot.dataset.structureSlot = 'true';
    const structureTools = el('div', 'seq-structure-tools'); structureTools.dataset.structureTools = 'true';
    structureStage.append(structureSlot, structureTools);
    root.append(structureNote);
    if (structure) root.append(structureStage);
    for (const view of views) {
      const section = el('section', 'seq-section'); section.dataset.viewId = view.id;
      section.append(el('h3', '', view.title));
      if (view.description) section.append(el('p', 'seq-note', view.description));
      section.append(el('div', 'seq-stage')); root.append(section);
    }
    const downloads = el('div', 'seq-downloads'); downloads.setAttribute('role', 'group'); downloads.setAttribute('aria-label', 'Result downloads');
    const download = (id, label) => { const file = first(context, id); const button = el('button', '', label); button.type = 'button'; button.disabled = !file; button.onclick = () => file && services.downloadFile?.(file); downloads.append(button); };
    download('designs', 'Download designed structures (PDB)');
    download('sequences', 'Download designed sequences (FASTA)');
    download('input_structure', 'Download input structure (PDB)');
    download('citations', 'Download citations (BibTeX)');
    const status = el('p', 'result-note', 'Loading the published designs…'); status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
    root.append(status, downloads); host.replaceChildren(root);
    let structureMounted = false;
    if (structure && typeof services.openFile === 'function') {
      try { await services.openFile(structure); structureMounted = true; }
      catch (error) { if (error.name === 'AbortError') { structureStage.remove(); return { destroy() { abort.abort(); } }; } }
    }
    if (!structureMounted) structureStage.remove();
    structureNote.textContent = !structure ? 'This run published no design structure.'
      : structureMounted ? `The all-atom structure ${structure.name || ''} is the design model published with this run.`
        : 'The design structure could not be drawn here; it stays downloadable below.';
    const mounted = [];
    try {
      if (!services.mountView) throw new Error('The declared design view is unavailable.');
      for (const section of root.querySelectorAll('[data-view-id]')) {
        mounted.push(await services.mountView(section.dataset.viewId, section.querySelector('.seq-stage'), abort.signal) || null);
      }
      status.textContent = 'The sequence and the structure are the same published design.';
    } catch (error) {
      if (error.name !== 'AbortError') { status.textContent = 'The designs could not be rendered; the downloads above remain available.'; status.className = 'result-note seq-error'; }
    }
    return { destroy() { abort.abort(); mounted.forEach(item => item?.destroy?.()); } };
  },
};
