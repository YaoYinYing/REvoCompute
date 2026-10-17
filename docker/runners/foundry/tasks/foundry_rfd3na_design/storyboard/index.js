/* Foundry RFdiffusion3NA nucleic-acid design composition. */
/* SPDX-License-Identifier: GPL-3.0-only */

const TITLE = "RFdiffusion3 designs";
const STYLE = `.rfd3-result{display:grid;gap:1rem;padding:1rem}.rfd3-result h2,.rfd3-result h3,.rfd3-result p{margin:0}.rfd3-section{display:grid;gap:.55rem;min-width:0}.rfd3-designs,.rfd3-actions,.rfd3-downloads{display:flex;flex-wrap:wrap;gap:.45rem}.rfd3-designs button[aria-current="true"]{outline:2px solid var(--accent);outline-offset:2px}`;
function list(value) { return Array.isArray(value) ? value : value ? [value] : []; }
function element(tag, className, text) { const node = document.createElement(tag); if (className) node.className = className; if (text != null) node.textContent = text; return node; }
function button(label, onClick) { const node = element("button", "btn btn-soft", label); node.type = "button"; node.addEventListener("click", onClick); return node; }
function section(title, note) { const node = element("section", "rfd3-section"); node.append(element("h3", "", title)); if (note) node.append(element("p", "scientific-note", note)); return node; }
// A published design name is "<example_id>_model_<index>.cif.gz" (pinned
// RFD3Output.dump). The label a candidate carries is read back from that same
// name, so the storyboard never invents an identity the contract did not declare.
function identity(name) { const match = String(name || "").match(/^(.*)_model_(\d+)\.cif\.gz$/); return match ? { example: match[1], index: Number(match[2]) } : null; }

export default { mount(host, context) {
  const designs = list(context.files.get("designs")); const metadata = list(context.files.get("model_metadata"));
  const runRecord = list(context.files.get("run_record"))[0]; const modelAssets = list(context.files.get("model_assets"))[0];
  const root = element("div", "rfd3-result"); root.append(element("style", null, STYLE), element("h2", "", TITLE));
  const downloads = element("div", "rfd3-downloads");
  downloads.append(button("Download run record", () => context.services.downloadFile(runRecord)));
  downloads.append(button("Download model identity", () => context.services.downloadFile(modelAssets)));
  root.append(downloads);
  const designsSection = section("Designed structures", "One gzipped mmCIF per diffusion batch member; the published name keeps the specification key and the model index explicit.");
  const designHost = element("div", "rfd3-designs"); const actions = element("div", "rfd3-actions");
  designsSection.append(designHost, actions); root.append(designsSection);
  const idle = "Select a design to open it, and its per-design metadata when one was published.";
  function choose(index) {
    const artifact = designs[index]; if (!artifact) return;
    const item = identity(artifact.name || artifact.path);
    const buttons = [button("Open selected structure", () => context.services.openFile(artifact))];
    // RFD3Output.dump writes "<example_id>.json" beside the structure only when
    // prediction metadata is present, so a design without one offers no button.
    const wanted = item ? item.example + "_model_" + item.index + ".json" : null;
    const meta = wanted ? metadata.find((file) => (file.name || file.path) === wanted) : null;
    if (meta) buttons.push(button("Download design metadata", () => context.services.downloadFile(meta)));
    actions.replaceChildren.apply(actions, buttons);
    designHost.querySelectorAll("[data-index]").forEach((node) => node.setAttribute("aria-current", node.dataset.index === String(index) ? "true" : "false"));
  }
  designs.forEach((artifact, index) => {
    const item = identity(artifact.name || artifact.path);
    const node = element("button", "candidate-open", item ? item.example + " · model " + item.index : String(artifact.name || artifact.path));
    node.type = "button"; node.dataset.index = String(index); node.setAttribute("aria-current", "false");
    node.addEventListener("click", () => choose(index)); designHost.append(node);
  });
  if (designs.length) choose(0);
  else { const note = element("p", "preview-message", "No design structure was published."); designHost.replaceChildren(note); actions.replaceChildren(note.cloneNode(true)); }
  host.replaceChildren(root);
  return { destroy() { host.replaceChildren(); } };
} };
