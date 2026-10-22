/* PRIME predicted optimal growth temperature. */
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
    root.append(el('h2', '', 'Predicted optimal growth temperature'));
    root.append(el('p', 'sl-note', 'The published row carries one model estimate per input sequence: `id` is the sequence identity and `ogt` is the optimal growth temperature in degrees Celsius. It is a sequence-level prediction, not a measured value, and should be read within the model\'s training domain.'));
    const stage = el('div', 'sl-stage');
    const status = el('p', 'result-note', 'Loading the published prediction…'); status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
    const downloads = el('div', 'sl-downloads'); downloads.setAttribute('role', 'group'); downloads.setAttribute('aria-label', 'Result downloads');
    const download = (id, label) => { const file = first(context, id); const button = el('button', '', label); button.type = 'button'; button.disabled = !file; button.onclick = () => file && services.downloadFile?.(file); downloads.append(button); };
    download('growth_temperature', 'Download prediction (CSV)');
    download('input_sequence', 'Download input sequence (FASTA)');
    download('citations', 'Download citations (BibTeX)');
    root.append(stage, status, downloads); host.replaceChildren(root);
    const view = list(context.views).find(item => item.id === 'growth_temperature');
    let embedded = null;
    try {
      if (!view || !services.mountView) throw new Error('The declared growth-temperature view is unavailable.');
      embedded = await services.mountView(view.id, stage, abort.signal) || null;
      status.textContent = 'One row per input sequence; `ogt` is in degrees Celsius.';
    } catch (error) {
      if (error.name !== 'AbortError') { stage.replaceChildren(el('p', 'sl-error', error.message)); status.textContent = 'The prediction could not be rendered; the download above remains available.'; }
    }
    services.describeResult?.({ title: 'Predicted growth temperature', subtitle: 'Pro-Prime sequence-level estimate (°C)' });
    return { destroy() { abort.abort(); embedded?.destroy?.(); } };
  },
};
