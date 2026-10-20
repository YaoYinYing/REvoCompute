/* FA-MPNN scoring: per-substitution model log-likelihood changes. */
/* SPDX-License-Identifier: GPL-3.0-only */
const STYLE = `.score-result{display:grid;gap:16px;min-width:0;font:14px/1.5 var(--font-sans)}.score-result h2,.score-result h3,.score-result p{margin:0}.score-result h2{font:500 24px var(--font-display)}.score-section{display:grid;gap:8px;min-width:0}.score-note{color:var(--app-muted);line-height:1.7;max-width:78ch}.score-stage{border:1px solid var(--app-line);border-radius:8px;background:var(--app-surface);padding:12px;overflow:auto}.score-stage:empty{display:none}.score-downloads{display:flex;flex-wrap:wrap;gap:8px}.score-downloads button{font:14px var(--font-sans);min-height:34px;padding:7px 12px;border:1px solid var(--app-line-strong);border-radius:4px;color:var(--app-ink);background:var(--app-raised);cursor:pointer}`;
const list = value => Array.isArray(value) ? value : value ? [value] : [];
const first = (context, id) => list(context.files.get(id))[0] || null;
function el(tag, className = '', text) { const node = document.createElement(tag); node.className = className; if (text != null) node.textContent = String(text); return node; }

export default {
  async mount(host, context) {
    const services = context.services || {};
    const abort = new AbortController();
    const views = list(context.views);
    const root = el('div', 'score-result');
    const style = el('style'); style.textContent = STYLE; root.append(style);
    root.append(el('h2', '', 'Single-mutation scores'));
    root.append(el('p', 'score-note', 'Each cell is the model log-likelihood change for one substitution relative to the input residue, so the wild-type entry at each position is 0. Positive values mean the model prefers the substitution. These are likelihood scores, not calibrated experimental fitness values.'));
    for (const view of views) {
      const section = el('section', 'score-section'); section.dataset.viewId = view.id;
      section.append(el('h3', '', view.title));
      if (view.description) section.append(el('p', 'score-note', view.description));
      section.append(el('div', 'score-stage')); root.append(section);
    }
    const downloads = el('div', 'score-downloads'); downloads.setAttribute('role', 'group'); downloads.setAttribute('aria-label', 'Result downloads');
    const download = (id, label) => { const file = first(context, id); const button = el('button', '', label); button.type = 'button'; button.disabled = !file; button.onclick = () => file && services.downloadFile?.(file); downloads.append(button); };
    download('mutation_scores', 'Download score table (CSV)');
    download('config', 'Download run configuration (YAML)');
    download('input_structure', 'Download input structure (PDB)');
    download('citations', 'Download citations (BibTeX)');
    const status = el('p', 'result-note', 'Loading the published score table…'); status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
    root.append(status, downloads); host.replaceChildren(root);
    const mounted = [];
    try {
      if (!services.mountView) throw new Error('The declared score view is unavailable.');
      for (const section of root.querySelectorAll('[data-view-id]')) {
        mounted.push(await services.mountView(section.dataset.viewId, section.querySelector('.score-stage'), abort.signal) || null);
      }
      status.textContent = 'One row per input residue position; one column per amino acid.';
    } catch (error) {
      if (error.name !== 'AbortError') { status.textContent = 'The score table could not be rendered; the downloads above remain available.'; status.className = 'result-note'; }
    }
    return { destroy() { abort.abort(); mounted.forEach(item => item?.destroy?.()); } };
  },
};
