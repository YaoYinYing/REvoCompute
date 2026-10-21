/* FreeBindCraft: ranked binder designs, campaign metrics, and their limits. */
/* SPDX-License-Identifier: GPL-3.0-only */
const STYLE = `.fb-result{display:grid;gap:16px;min-width:0;font:14px/1.5 var(--font-sans)}.fb-result h2,.fb-result h3,.fb-result p{margin:0}.fb-result h2{font:500 24px var(--font-display)}.fb-section{display:grid;gap:8px;min-width:0}.fb-note{color:var(--app-muted);line-height:1.7;max-width:78ch}.fb-stage{border:1px solid var(--app-line);border-radius:8px;background:var(--app-surface);padding:12px;overflow:auto}.fb-stage:empty{display:none}.fb-downloads{display:flex;flex-wrap:wrap;gap:8px}.fb-downloads button{font:14px var(--font-sans);min-height:34px;padding:7px 12px;border:1px solid var(--app-line-strong);border-radius:4px;color:var(--app-ink);background:var(--app-raised);cursor:pointer}`;
const list = value => Array.isArray(value) ? value : value ? [value] : [];
const first = (context, id) => list(context.files.get(id))[0] || null;
function el(tag, className = '', text) { const node = document.createElement(tag); node.className = className; if (text != null) node.textContent = String(text); return node; }

export default {
  async mount(host, context) {
    const services = context.services || {};
    const abort = new AbortController();
    const views = list(context.views);
    const root = el('div', 'fb-result');
    const style = el('style'); style.textContent = STYLE; root.append(style);
    root.append(el('h2', '', 'Ranked binder designs'));
    root.append(el('p', 'fb-note', 'Each published binder is a designed structure scored against the supplied target by the campaign\'s own confidence model. Rank and confidence columns order the designs; they are model predictions, not measured binding affinity, and a design still needs experimental validation.'));
    // The campaign always publishes Trajectory/Animation.zip, but a run that
    // produced no trajectory animation writes the empty archive (22 bytes, no
    // entries). The file stays downloadable; nothing here presents it as frames.
    const animation = first(context, 'trajectory_animation');
    if (animation) root.append(el('p', 'fb-note', animation.size <= 22
      ? `Trajectory/Animation.zip is an empty archive (${animation.size} bytes, no entries); this run published no trajectory animation, and this page does not present it as frames.`
      : `Trajectory/Animation.zip (${animation.size} bytes) is published with this campaign; this page does not read its frames.`));
    for (const view of views) {
      const section = el('section', 'fb-section'); section.dataset.viewId = view.id;
      section.append(el('h3', '', view.title));
      if (view.description) section.append(el('p', 'fb-note', view.description));
      section.append(el('div', 'fb-stage')); root.append(section);
    }
    const downloads = el('div', 'fb-downloads'); downloads.setAttribute('role', 'group'); downloads.setAttribute('aria-label', 'Result downloads');
    const download = (id, label) => { const file = first(context, id); const button = el('button', '', label); button.type = 'button'; button.disabled = !file; button.onclick = () => file && services.downloadFile?.(file); downloads.append(button); };
    download('ranked_binders', 'Download ranked binders (PDB)');
    download('design_metrics', 'Download design metrics (CSV)');
    download('trajectory_plots', 'Download trajectory plots (ZIP)');
    download('trajectory_animation', 'Download trajectory animation (ZIP)');
    download('run_settings', 'Download run settings (JSON)');
    download('target_settings', 'Download target settings (JSON)');
    download('input_structure', 'Download target structure (PDB)');
    download('citations', 'Download citations (BibTeX)');
    const status = el('p', 'result-note', 'Loading the published campaign…'); status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
    root.append(status, downloads); host.replaceChildren(root);
    const mounted = [];
    try {
      if (!services.mountView) throw new Error('The declared campaign view is unavailable.');
      for (const section of root.querySelectorAll('[data-view-id]')) {
        mounted.push(await services.mountView(section.dataset.viewId, section.querySelector('.fb-stage'), abort.signal) || null);
      }
      status.textContent = 'A design\'s identity in the metrics table is the same name its structure carries.';
    } catch (error) {
      if (error.name !== 'AbortError') { status.textContent = 'The campaign could not be rendered; the downloads above remain available.'; status.className = 'result-note'; }
    }
    return { destroy() { abort.abort(); mounted.forEach(item => item?.destroy?.()); } };
  },
};
