/* ESM-IF1 sampled designs for the selected backbone chain. */
/* SPDX-License-Identifier: GPL-3.0-only */
const STYLE = `.sl-result{display:grid;gap:18px;min-width:0;font:14px/1.5 var(--font-sans)}.sl-result>*{min-width:0}.sl-result h2,.sl-result h3,.sl-result p{margin:0}.sl-result h2{font:500 24px var(--font-display);letter-spacing:-.5px}.sl-note{color:var(--app-muted);line-height:1.7;max-width:78ch;white-space:pre-line}.sl-stage{border:1px solid var(--app-line);border-radius:8px;background:var(--app-surface);padding:12px;overflow-x:auto}.sl-stage:empty{display:none}.sl-error{padding:18px;color:var(--app-danger)}.sl-downloads{display:flex;flex-wrap:wrap;gap:8px}.sl-downloads button{font:14px var(--font-sans);min-height:34px;padding:7px 12px;border:1px solid var(--app-line-strong);border-radius:4px;color:var(--app-ink);background:var(--app-raised);cursor:pointer}`;
const list = value => Array.isArray(value) ? value : value ? [value] : [];
const first = (context, id) => list(context.files.get(id))[0] || null;
function el(tag, className = '', text) { const node = document.createElement(tag); node.className = className; if (text != null) node.textContent = String(text); return node; }

export default {
  async mount(host, context) {
    const services = context.services || {};
    const abort = new AbortController();
    const root = el('div', 'sl-result'), style = el('style'); style.textContent = STYLE; root.append(style);
    root.append(el('h2', '', 'Designed sequences'));
    root.append(el('p', 'sl-note', 'Sequences sampled by ESM-IF1 conditioned on the selected backbone chain, in runner output order. A design is a model sample: its identity to the wild-type chain is not a score, and neither structure nor function is validated by this result.'));
    const stage = el('div', 'sl-stage');
    const status = el('p', 'result-note', 'Loading the published designs…'); status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
    const downloads = el('div', 'sl-downloads'); downloads.setAttribute('role', 'group'); downloads.setAttribute('aria-label', 'Result downloads');
    const download = (id, label) => { const file = first(context, id); const button = el('button', '', label); button.type = 'button'; button.disabled = !file; button.onclick = () => file && services.downloadFile?.(file); downloads.append(button); };
    download('designs', 'Download designs (FASTA)');
    download('input_structure', 'Download input backbone (PDB)');
    download('citations', 'Download citations (BibTeX)');
    root.append(stage, status, downloads); host.replaceChildren(root);
    const view = list(context.views).find(item => item.id === 'designed_sequences');
    let embedded = null;
    try {
      if (!view || !services.mountView) throw new Error('The declared candidate view is unavailable.');
      embedded = await services.mountView(view.id, stage, abort.signal) || null;
      status.textContent = 'Each published FASTA record is one sample; the header is the record\'s own identity.';
    } catch (error) {
      if (error.name !== 'AbortError') { stage.replaceChildren(el('p', 'sl-error', error.message)); status.textContent = 'The designs could not be rendered; the download above remains available.'; }
    }
    services.describeResult?.({ title: 'ESM-IF1 designs', subtitle: 'Sampled sequences for the selected chain' });
    return { destroy() { abort.abort(); embedded?.destroy?.(); } };
  },
};
