/* ESM-2 representation bundle: the opaque artifact, stated as such. */
/* SPDX-License-Identifier: GPL-3.0-only */
const STYLE = `.sl-result{display:grid;gap:18px;min-width:0;font:14px/1.5 var(--font-sans)}.sl-result>*{min-width:0}.sl-result h2,.sl-result h3,.sl-result p{margin:0}.sl-result h2{font:500 24px var(--font-display);letter-spacing:-.5px}.sl-note{color:var(--app-muted);line-height:1.7;max-width:78ch;white-space:pre-line}.sl-stage{border:1px solid var(--app-line);border-radius:8px;background:var(--app-surface);padding:12px;overflow-x:auto}.sl-stage:empty{display:none}.sl-error{padding:18px;color:var(--app-danger)}.sl-downloads{display:flex;flex-wrap:wrap;gap:8px}.sl-downloads button{font:14px var(--font-sans);min-height:34px;padding:7px 12px;border:1px solid var(--app-line-strong);border-radius:4px;color:var(--app-ink);background:var(--app-raised);cursor:pointer}`;
const list = value => Array.isArray(value) ? value : value ? [value] : [];
const first = (context, id) => list(context.files.get(id))[0] || null;
function el(tag, className = '', text) { const node = document.createElement(tag); node.className = className; if (text != null) node.textContent = String(text); return node; }

export default {
  async mount(host, context) {
    const services = context.services || {};
    const abort = new AbortController();
    const embedding = first(context, 'embeddings');
    const root = el('div', 'sl-result'), style = el('style'); style.textContent = STYLE; root.append(style);
    root.append(el('h2', '', 'ESM-2 representation bundle'));
    root.append(el('p', 'sl-note', 'The Runner publishes one serialized PyTorch bundle holding the requested ESM-2 representations (for the reference run: layer-33 mean representations and contact values). The bundle is opaque to the browser by design, so this result offers the download and makes no numeric claim that was not read from the file itself.'));
    const downloads = el('div', 'sl-downloads'); downloads.setAttribute('role', 'group'); downloads.setAttribute('aria-label', 'Result downloads');
    const download = (id, label) => { const file = first(context, id); const button = el('button', '', label); button.type = 'button'; button.disabled = !file; button.onclick = () => file && services.downloadFile?.(file); downloads.append(button); };
    download('embeddings', 'Download representation bundle (PT)');
    download('input_sequence', 'Download input sequence (FASTA)');
    download('citations', 'Download citations (BibTeX)');
    const stage = el('div', 'sl-stage');
    const status = el('p', 'result-note', embedding ? `Published bundle: ${embedding.name} · ${embedding.size} bytes.` : 'No representation bundle was published.');
    status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
    root.append(status, stage, downloads); host.replaceChildren(root);
    const view = list(context.views).find(item => item.id === 'embeddings');
    let embedded = null;
    try {
      if (!view || !services.mountView) throw new Error('The declared embedding-bundle view is unavailable.');
      embedded = await services.mountView(view.id, stage, abort.signal) || null;
    } catch (error) {
      if (error.name !== 'AbortError') stage.replaceChildren(el('p', 'sl-error', error.message));
    }
    services.describeResult?.({ title: 'ESM-2 representation bundle', subtitle: 'Serialized model representations' });
    return { destroy() { abort.abort(); embedded?.destroy?.(); } };
  },
};
