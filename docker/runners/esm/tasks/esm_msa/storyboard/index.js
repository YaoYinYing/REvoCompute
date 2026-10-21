/* ESM-MSA-1b per-position profile and its summary. */
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
    root.append(el('h2', '', 'Per-residue masked-marginal profile'));
    root.append(el('p', 'sl-note', 'Wild-type log probability and predictive entropy along the query sequence, in natural log units, as reported by ESM-MSA-1b. Both series are model values; entropy is uncertainty of the model, not an experimental measurement. The profile reflects the retained alignment rows, so a shallow alignment yields a near single-sequence profile.'));
    const downloads = el('div', 'sl-downloads'); downloads.setAttribute('role', 'group'); downloads.setAttribute('aria-label', 'Result downloads');
    const download = (id, label) => { const file = first(context, id); const button = el('button', '', label); button.type = 'button'; button.disabled = !file; button.onclick = () => file && services.downloadFile?.(file); downloads.append(button); };
    download('residue_profile', 'Download per-residue profile (CSV)');
    download('profile_summary', 'Download profile summary (JSON)');
    download('input_alignment', 'Download input alignment (A3M)');
    download('citations', 'Download citations (BibTeX)');
    const sections = [];
    for (const view of views) {
      const section = el('section', 'sl-section'); section.dataset.viewId = view.id;
      section.append(el('h3', '', view.title));
      if (view.description) section.append(el('p', 'sl-note', view.description));
      const stage = el('div', 'sl-stage'); section.append(stage);
      sections.push({ view, section, stage });
      root.append(section);
    }
    root.append(downloads);
    host.replaceChildren(root);
    const status = el('p', 'result-note', ''); status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
    root.insertBefore(status, downloads);
    status.textContent = 'Loading the published profile…';
    let mounted = [];
    try {
      for (const item of sections) {
        if (!services.mountView) throw new Error('The declared profile views are unavailable.');
        mounted.push(await services.mountView(item.view.id, item.stage, abort.signal) || null);
      }
      status.textContent = 'One point per query position; the summary repeats the profile means.';
    } catch (error) {
      if (error.name !== 'AbortError') { status.textContent = 'The profile views could not be rendered; the downloads above remain available.'; status.className = 'sl-error'; }
    }
    services.describeResult?.({ title: 'ESM-MSA-1b profile', subtitle: 'Masked-marginal log probability and entropy' });
    return { destroy() { abort.abort(); mounted.forEach(item => item?.destroy?.()); } };
  },
};
