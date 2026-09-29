/* AlphaFold 3 scientific result composition.

   The PAE matrix, its colour domain, and the chain-boundary rule are
   Runner-owned interpretation of ``*_confidences.json``. Generic file
   rendering and the 3D structure viewer stay in the server; this module
   supplies AF3 semantics to the shared matrix renderer. */

// Single-hue sequential ramp. The Runner owns the scientific colour semantics;
// the shared PairMatrix owns canvas mechanics and interaction.
const RAMP_LIGHT = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"];
const RAMP_DARK = ["#184f95", "#256abf", "#3987e5", "#6da7ec", "#9ec5f4", "#b7d3f6", "#cde2fb"];
const PLOT = { width: 800, height: 600, left: 78, top: 30, size: 500, legendX: 604, legendWidth: 24 };

const STYLE = `
.af3-result { display: grid; gap: 1.1rem; padding: 1rem; }
.af3-result h2, .af3-result h3 { margin: 0; }
.af3-result p { margin: 0; }
.af3-section { display: grid; gap: 0.5rem; }
.af3-chips { display: flex; flex-wrap: wrap; gap: 0.5rem; }
`;

function themeName() {
  const declared = document.documentElement.getAttribute("data-theme");
  if (declared === "dark" || declared === "light") return declared;
  return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function asList(value) {
  return Array.isArray(value) ? value : value ? [value] : [];
}

function basename(path) {
  return String(path || "").split("/").pop();
}

function formatValue(value) {
  return Number.isFinite(value) ? value.toFixed(1) : "—";
}

async function loadJson(artifact) {
  const auth = window.REvoDesignAuth;
  const response = auth
    ? await auth.authFetch(artifact.url)
    : await fetch(artifact.url, { credentials: "same-origin" });
  if (!response.ok) throw new Error("AlphaFold 3 confidence data could not be loaded.");
  return response.json();
}

function button(label, onClick) {
  const node = document.createElement("button");
  node.type = "button";
  node.className = "btn btn-soft";
  node.textContent = label;
  node.addEventListener("click", onClick);
  return node;
}

function section(title, note) {
  const group = document.createElement("section");
  group.className = "af3-section";
  const heading = document.createElement("h3");
  heading.textContent = title;
  group.appendChild(heading);
  if (note) {
    const description = document.createElement("p");
    description.className = "scientific-note";
    description.textContent = note;
    group.appendChild(description);
  }
  return group;
}

function message(text) {
  const node = document.createElement("p");
  node.className = "preview-message";
  node.textContent = text;
  return node;
}

/* Per-residue confidence for the top-ranked model. The per-model table is the
   server-rendered "Structure confidence" tab; this is the headline only. */
async function renderConfidence(group, summaries) {
  if (!summaries.length) {
    group.appendChild(message("No summary confidence file was published for this run."));
    return;
  }
  const fields = [
    ["ptm", "pTM", "score"],
    ["iptm", "ipTM", "score"],
    ["ranking_score", "Ranking score", "score"],
    ["fraction_disordered", "Fraction disordered", "fraction"],
  ];
  const list = document.createElement("dl");
  list.className = "scalar-grid";
  group.appendChild(list);
  try {
    const payload = await loadJson(summaries[0]);
    fields.forEach(([key, fieldLabel, unit]) => {
      const term = document.createElement("dt");
      term.textContent = fieldLabel;
      const value = document.createElement("dd");
      value.textContent = payload[key] == null ? "N/A" : String(payload[key]) + " " + unit;
      list.append(term, value);
    });
  } catch (error) {
    list.remove();
    group.appendChild(message(error.message));
  }
}

export default {
  async mount(host, context) {
    const scientific = window.REvoComputeScientific;
    if (!scientific || typeof scientific.PairMatrix !== "function") {
      throw new Error("Shared scientific visualizations are unavailable.");
    }
    const style = document.createElement("style");
    style.textContent = STYLE;
    const root = document.createElement("div");
    root.className = "af3-result";
    const heading = document.createElement("h2");
    heading.textContent = "AlphaFold 3 prediction";
    const description = document.createElement("p");
    description.textContent =
      "Structure candidates, headline confidence, and the predicted aligned error (PAE) between " +
      "every pair of scored and aligned residues.";
    root.append(style, heading, description);

    const structures = asList(context.files.get("structures"));
    const structureGroup = section("Predicted structures", "Structures open in the shared result viewer.");
    const chips = document.createElement("div");
    chips.className = "af3-chips";
    structures.forEach((artifact) => {
      chips.appendChild(button(basename(artifact.path), () => context.services.openFile(artifact)));
    });
    if (!structures.length) chips.appendChild(message("No structure candidate was published."));
    structureGroup.appendChild(chips);
    root.appendChild(structureGroup);

    const confidenceGroup = section("Global confidence", "Headline confidence for the top-ranked model.");
    root.appendChild(confidenceGroup);
    const confidenceDone = renderConfidence(confidenceGroup, asList(context.files.get("summaries")));

    const models = asList(context.files.get("confidences"))
      // The declared pattern also matches the per-model summary file, which
      // carries the same name plus "summary" and has no matrix.
      .filter((artifact) => !/_summary_confidences\.json$/.test(artifact.path));
    const paeGroup = section("Expected position error", null);
    const note = document.createElement("p");
    note.className = "scientific-note";
    note.id = "af3-pae-note";
    note.textContent = "Predicted aligned error between every pair of scored and aligned residues.";
    paeGroup.appendChild(note);

    let showBorders = false;
    let matrix = null;
    const toolbar = document.createElement("div");
    toolbar.className = "scientific-toolbar";
    const borders = button("Show chain borders", () => {
      showBorders = !showBorders;
      borders.setAttribute("aria-pressed", String(showBorders));
      if (matrix) matrix.setBorders(showBorders);
    });
    borders.setAttribute("aria-pressed", "false");
    toolbar.appendChild(borders);
    let selector = null;
    if (models.length > 1) {
      const picker = document.createElement("label");
      picker.textContent = "Model ";
      selector = document.createElement("select");
      selector.setAttribute("aria-label", "Model");
      models.forEach((artifact, index) => {
        const option = document.createElement("option");
        option.value = String(index);
        option.textContent = basename(artifact.path).replace(/_confidences\.json$/, "");
        selector.appendChild(option);
      });
      selector.addEventListener("change", () => open(models[Number(selector.value)]).catch(fail));
      picker.appendChild(selector);
      toolbar.appendChild(picker);
    }
    paeGroup.appendChild(toolbar);

    const plot = document.createElement("div");
    plot.className = "af3-plot pair-matrix-plot";
    const figure = document.createElement("div");
    figure.className = "af3-figure pair-matrix-figure";
    const canvas = document.createElement("canvas");
    canvas.className = "af3-canvas pair-matrix-canvas";
    canvas.width = PLOT.width;
    canvas.height = PLOT.height;
    canvas.tabIndex = 0;
    canvas.setAttribute("role", "grid");
    canvas.setAttribute("aria-describedby", note.id);
    // The matrix arrives over the network, so the plot is inert until it does:
    // a focusable canvas whose handlers dereference an empty matrix is a
    // keyboard trap that throws on the first arrow key. PairMatrix enables it
    // once there are values to read.
    canvas.setAttribute("aria-disabled", "true");
    figure.appendChild(canvas);
    plot.appendChild(figure);
    paeGroup.appendChild(plot);

    const readout = document.createElement("p");
    readout.className = "matrix-readout";
    readout.setAttribute("role", "status");
    paeGroup.appendChild(readout);
    root.appendChild(paeGroup);
    host.replaceChildren(root);
    await confidenceDone;

    let residueIds = [];
    let chainIds = [];

    function fail(error) {
      if (matrix) matrix.destroy();
      plot.replaceChildren(message(error.message || "The PAE matrix could not be drawn."));
      readout.textContent = "";
    }

    function residueLabel(index) {
      const residue = residueIds[index];
      return residue == null ? String(index + 1) : String(residue);
    }

    function chainLabel(index) {
      return chainIds[index] == null ? "?" : String(chainIds[index]);
    }

    matrix = new scientific.PairMatrix({
      figure,
      canvas,
      readout,
      observe: plot,
      geometry: PLOT,
      minimum: 0,
      decimals: 1,
      ticks: 5,
      xTitle: "Aligned residue",
      yTitle: "Scored residue",
      legendTitle: "PAE (Å)",
      unit: "Å",
      ramp: () => themeName() === "dark" ? RAMP_DARK : RAMP_LIGHT,
      formatReadout: ({ x, y, value }) =>
        "Aligned residue " + residueLabel(x) + " (chain " + chainLabel(x) + ")" +
        " · Scored residue " + residueLabel(y) + " (chain " + chainLabel(y) + ")" +
        " · " + formatValue(value) + " Å",
      onDraw: ({ rows, columns, minimum, maximum }) => {
        const chains = new Set(chainIds.filter((id) => id != null));
        note.textContent =
          "PAE in ångströms: " + rows + " × " + columns + " scored and aligned residues across " +
          chains.size + " chains, from " + formatValue(minimum) + " to " + formatValue(maximum) +
          " Å in this model. Lower is better. Click the matrix or use the arrow keys to read a cell.";
      },
    });

    async function open(artifact) {
      const payload = await loadJson(artifact);
      const pae = payload.pae;
      if (!Array.isArray(pae) || !pae.length || !Array.isArray(pae[0])) {
        throw new Error("The confidence file does not contain a PAE matrix.");
      }
      residueIds = Array.isArray(payload.token_res_ids) ? payload.token_res_ids : [];
      chainIds = Array.isArray(payload.token_chain_ids) ? payload.token_chain_ids : [];
      const canBorder = chainIds.length > 0;
      borders.disabled = !canBorder;
      if (!canBorder && showBorders) {
        showBorders = false;
        borders.setAttribute("aria-pressed", "false");
      }
      matrix.setData({ values: pae, xLabels: residueIds, yLabels: residueIds, xGroups: chainIds, yGroups: chainIds });
      if (selector) {
        const position = models.indexOf(artifact);
        if (position >= 0) selector.value = String(position);
      }
    }

    if (!models.length) {
      fail(new Error("No confidence file was published for this run."));
      return { destroy() { if (matrix) matrix.destroy(); } };
    }
    try {
      await open(models[0]);
    } catch (error) {
      fail(error);
    }
    return { destroy() { if (matrix) matrix.destroy(); } };
  },
  destroy() {},
};
