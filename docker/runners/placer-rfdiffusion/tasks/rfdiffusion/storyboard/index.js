/* RFdiffusion: generated backbones, the diffusion trajectory, and its limits. */
/* SPDX-License-Identifier: GPL-3.0-only */
const STYLE = `.rf-result{display:grid;gap:16px;min-width:0;font:14px/1.5 var(--font-sans)}.rf-result h2,.rf-result h3,.rf-result p{margin:0}.rf-result h2{font:500 24px var(--font-display)}.rf-section{display:grid;gap:8px;min-width:0}.rf-note{color:var(--app-muted);line-height:1.7;max-width:78ch}.rf-stage{border:1px solid var(--app-line);border-radius:8px;background:var(--app-surface);padding:12px;overflow:auto}.rf-stage:empty{display:none}.rf-stage .trajectory-viewport{border:0}.rf-downloads{display:flex;flex-wrap:wrap;gap:8px}.rf-downloads button{font:14px var(--font-sans);min-height:34px;padding:7px 12px;border:1px solid var(--app-line-strong);border-radius:4px;color:var(--app-ink);background:var(--app-raised);cursor:pointer}`;
const list = value => Array.isArray(value) ? value : value ? [value] : [];
const first = (context, id) => list(context.files.get(id))[0] || null;
function el(tag, className = '', text) { const node = document.createElement(tag); node.className = className; if (text != null) node.textContent = String(text); return node; }

export default {
  async mount(host, context) {
    const services = context.services || {};
    const abort = new AbortController();
    const views = list(context.views);
    const root = el('div', 'rf-result');
    const style = el('style'); style.textContent = STYLE; root.append(style);
    root.append(el('h2', '', 'Generated backbones'));
    root.append(el('p', 'rf-note', 'Each published backbone is a de novo structure sampled by reverse diffusion. The trajectory beside it is the same design across diffusion steps: one frame is one diffusion step, not a physical time, and the last frame is the final backbone. Generated backbones are design hypotheses and need independent validation.'));
    const trajectory = views.find(view => view.plugin === 'trajectory');
    let mountedTrajectory = null;
    for (const view of views) {
      const section = el('section', 'rf-section'); section.dataset.viewId = view.id;
      section.append(el('h3', '', view.title));
      if (view.description) section.append(el('p', 'rf-note', view.description));
      const stage = el('div', 'rf-stage'); section.append(stage); root.append(section);
      if (view.plugin === 'trajectory') mountedTrajectory = stage;
    }
    const downloads = el('div', 'rf-downloads'); downloads.setAttribute('role', 'group'); downloads.setAttribute('aria-label', 'Result downloads');
    const download = (id, label) => { const file = first(context, id); const button = el('button', '', label); button.type = 'button'; button.disabled = !file; button.onclick = () => file && services.downloadFile?.(file); downloads.append(button); };
    download('backbones', 'Download generated backbones (PDB)');
    download('diffusion_px0', 'Download x0-prediction trajectories (PDB)');
    download('diffusion_noisy', 'Download noisy-state trajectories (PDB)');
    download('design_records', 'Download design records (TRB)');
    download('submission', 'Download submission snapshot (JSON)');
    download('citations', 'Download citations (BibTeX)');
    const status = el('p', 'result-note', 'Loading the published backbones…'); status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
    root.append(status, downloads); host.replaceChildren(root);
    const mounted = [];
    try {
      if (!services.mountView) throw new Error('The declared backbone view is unavailable.');
      if (trajectory && !first(context, 'diffusion_px0') && mountedTrajectory) {
        mountedTrajectory.append(el('p', 'rf-note', 'This run published no diffusion trajectory; the final backbone is the only published result of the diffusion.'));
        mountedTrajectory = null;
      }
      for (const section of root.querySelectorAll('[data-view-id]')) {
        const view = views.find(item => item.id === section.dataset.viewId);
        if (view?.plugin === 'trajectory' && !first(context, 'diffusion_px0')) continue;
        mounted.push(await services.mountView(view.id, section.querySelector('.rf-stage'), abort.signal) || null);
      }
      status.textContent = 'The backbone and its trajectory are the same published design.';
    } catch (error) {
      if (error.name !== 'AbortError') { status.textContent = 'The backbones could not be rendered; the downloads above remain available.'; status.className = 'result-note'; }
    }
    return { destroy() { abort.abort(); mounted.forEach(item => item?.destroy?.()); } };
  },
};
