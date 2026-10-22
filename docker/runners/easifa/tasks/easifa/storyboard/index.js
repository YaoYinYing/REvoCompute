/* EasIFA: the residue-level active-site table paired with the annotated structure. */
/* SPDX-License-Identifier: GPL-3.0-only */
const STYLE = `.sl-result{display:grid;gap:18px;min-width:0;font:14px/1.5 var(--font-sans)}.sl-result>*{min-width:0}.sl-result h2,.sl-result h3,.sl-result p{margin:0}.sl-result h2{font:500 24px var(--font-display);letter-spacing:-.5px}.sl-section{display:grid;gap:8px;min-width:0}.sl-section h3{font:500 18px var(--font-display)}.sl-note{color:var(--app-muted);line-height:1.7;max-width:78ch;white-space:pre-line}.sl-stage{border:1px solid var(--app-line);border-radius:8px;background:var(--app-surface);padding:12px;overflow-x:auto}.sl-stage:empty{display:none}.sl-error{padding:18px;color:var(--app-danger)}.sl-downloads{display:flex;flex-wrap:wrap;gap:8px}.sl-downloads button{font:14px var(--font-sans);min-height:34px;padding:7px 12px;border:1px solid var(--app-line-strong);border-radius:4px;color:var(--app-ink);background:var(--app-raised);cursor:pointer}`;
const list = value => Array.isArray(value) ? value : value ? [value] : [];
const first = (context, id) => list(context.files.get(id))[0] || null;
function el(tag, className = '', text) { const node = document.createElement(tag); node.className = className; if (text != null) node.textContent = String(text); return node; }
async function fetchJson(file, signal) {
  const response = window.REvoDesignAuth ? await window.REvoDesignAuth.authFetch(file.url, { signal }) : await fetch(file.url, { credentials: 'same-origin', signal });
  if (!response.ok) throw new Error('The published EasIFA prediction could not be loaded.');
  return response.json();
}
// The published prediction owns the class vocabulary; the note names it only when
// the run actually published one, never from a hard-coded copy of the model labels.
function classVocabulary(prediction) {
  const mapping = prediction && prediction.site_type_mapping;
  if (!mapping || typeof mapping !== 'object') return null;
  return Object.keys(mapping).sort((a, b) => Number(a) - Number(b)).map(key => `${key} ${mapping[key]}`).join(', ');
}

export default {
  async mount(host, context) {
    const services = context.services || {};
    const abort = new AbortController();
    const views = list(context.views);
    const root = el('div', 'sl-result'), style = el('style'); style.textContent = STYLE; root.append(style);
    root.append(el('h2', '', 'Predicted enzyme active sites'));
    const note = el('p', 'sl-note', 'One row per residue of the submitted structure, with the predicted site class and its class probabilities. A run in which every residue is class 0 is a negative prediction for this structure, not a missing analysis: a probability is present for every row.');
    root.append(note);
    for (const view of views) {
      const section = el('section', 'sl-section'); section.dataset.viewId = view.id;
      section.append(el('h3', '', view.title));
      if (view.description) section.append(el('p', 'sl-note', view.description));
      const stage = el('div', 'sl-stage'); section.append(stage); root.append(section);
    }
    const downloads = el('div', 'sl-downloads'); downloads.setAttribute('role', 'group'); downloads.setAttribute('aria-label', 'Result downloads');
    const download = (id, label) => { const file = first(context, id); const button = el('button', '', label); button.type = 'button'; button.disabled = !file; button.onclick = () => file && services.downloadFile?.(file); downloads.append(button); };
    download('active_sites', 'Download active-site table (CSV)');
    download('enzyme_structure', 'Download annotated structure (PDB)');
    download('prediction', 'Download full prediction (JSON)');
    download('input_structure', 'Download input structure (PDB)');
    download('citations', 'Download citations (BibTeX)');
    const status = el('p', 'result-note', 'Loading the published active-site predictions…'); status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
    root.append(status, downloads); host.replaceChildren(root);
    const prediction = first(context, 'prediction');
    if (prediction) {
      fetchJson(prediction, abort.signal).then((payload) => {
        const vocabulary = classVocabulary(payload);
        note.textContent = `${note.textContent} ${vocabulary ? `Published site classes: ${vocabulary}.` : 'This run published no site-class vocabulary.'}`;
      }, () => { if (!abort.signal.aborted) note.textContent = `${note.textContent} The site-class vocabulary could not be read from the published prediction.`; });
    } else {
      note.textContent = `${note.textContent} This run published no prediction JSON, so the site-class vocabulary is not known.`;
    }
    let mounted = [];
    try {
      if (!services.mountView) throw new Error('The declared active-site views are unavailable.');
      for (const section of root.querySelectorAll('[data-view-id]')) {
        const view = views.find(item => item.id === section.dataset.viewId);
        mounted.push(await services.mountView(view.id, section.querySelector('.sl-stage'), abort.signal) || null);
      }
      status.textContent = 'The structure is the submitted coordinates; the table carries the per-residue predictions.';
    } catch (error) {
      if (error.name !== 'AbortError') { status.textContent = 'The active-site result could not be rendered; the downloads above remain available.'; status.className = 'sl-error'; }
    }
    services.describeResult?.({ title: 'EasIFA active sites', subtitle: 'Per-residue site-class predictions' });
    return { destroy() { abort.abort(); mounted.forEach(item => item?.destroy?.()); } };
  },
};
