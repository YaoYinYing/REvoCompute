/* AlphaFold 3 scientific result composition.

   The PAE matrix, its colour domain, and the chain-boundary rule are
   Runner-owned interpretation of ``*_confidences.json``. Generic file
   rendering and the 3D structure viewer stay in the server; this module only
   composes them and draws the matrix geometry on a canvas. Every piece of
   text - axis ticks, axis titles, the colour-scale legend - is a DOM node, so
   the plot has a real text alternative and stays readable by assistive
   technology. */

// Single-hue sequential ramp. The dark surface gets its own direction so
// "more error" keeps meaning "more contrast against the surface" instead of
// dissolving into the background.
const RAMP_LIGHT = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"];
const RAMP_DARK = ["#184f95", "#256abf", "#3987e5", "#6da7ec", "#9ec5f4", "#b7d3f6", "#cde2fb"];
const GREY = [119, 119, 119];
const TICKS = 5;
// Fixed geometry: the canvas never rescales, so the DOM tick labels sit at the
// same pixel coordinates the canvas draws into.
const PLOT = { width: 800, height: 600, left: 78, top: 30, size: 500, legendX: 604, legendWidth: 24 };

const STYLE = `
.af3-result { display: grid; gap: 1.1rem; padding: 1rem; }
.af3-result h2, .af3-result h3 { margin: 0; }
.af3-result p { margin: 0; }
.af3-section { display: grid; gap: 0.5rem; }
.af3-chips { display: flex; flex-wrap: wrap; gap: 0.5rem; }
.af3-plot { overflow-x: auto; }
.af3-figure { position: relative; width: 800px; height: 600px; }
.af3-canvas { display: block; width: 800px; height: 600px; }
.af3-canvas:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.af3-figure span { position: absolute; color: var(--muted); font-size: 11px; }
.af3-figure .af3-title { color: var(--ink); font-size: 12px; }
.af3-label-x { transform: translateX(-50%); }
.af3-label-y { transform: translateY(-50%); }
.af3-tick-y { left: 0; width: 69px; text-align: right; }
.af3-tick-legend { text-align: left; }
.af3-title-y { transform: translate(-50%, -50%) rotate(-90deg); white-space: nowrap; }
`;

function themeName() {
  const declared = document.documentElement.getAttribute("data-theme");
  if (declared === "dark" || declared === "light") return declared;
  return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function rampColor(ramp, ratio) {
  if (ratio == null || !Number.isFinite(ratio)) return GREY;
  const position = Math.max(0, Math.min(1, ratio)) * (ramp.length - 1);
  const low = Math.min(ramp.length - 2, Math.floor(position));
  const blend = position - low;
  const channel = (index) => {
    const from = parseInt(ramp[low].slice(index, index + 2), 16);
    const to = parseInt(ramp[low + 1].slice(index, index + 2), 16);
    return Math.round(from + (to - from) * blend);
  };
  return [channel(1), channel(3), channel(5)];
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

function chainBorderIndexes(chainIds) {
  const borders = [];
  for (let index = 1; index < chainIds.length; index += 1) {
    if (chainIds[index] !== chainIds[index - 1]) borders.push(index);
  }
  return borders;
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

function label(figure, text, style) {
  const node = document.createElement("span");
  node.textContent = text;
  Object.assign(node.style, style);
  figure.appendChild(node);
  return node;
}

function clearLabels(figure) {
  figure.querySelectorAll("span").forEach((node) => node.remove());
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

    const toolbar = document.createElement("div");
    toolbar.className = "scientific-toolbar";
    const borders = button("Show chain borders", () => {
      showBorders = !showBorders;
      borders.setAttribute("aria-pressed", String(showBorders));
      draw();
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
    plot.className = "af3-plot";
    const figure = document.createElement("div");
    figure.className = "af3-figure";
    const canvas = document.createElement("canvas");
    canvas.className = "af3-canvas";
    canvas.width = PLOT.width;
    canvas.height = PLOT.height;
    canvas.tabIndex = 0;
    canvas.setAttribute("role", "grid");
    canvas.setAttribute("aria-describedby", note.id);
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

    let values = [];
    let residueIds = [];
    let chainIds = [];
    let selected = { x: 0, y: 0 };
    let showBorders = false;

    function fail(error) {
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

    function report(x, y) {
      const row = values[y] || [];
      readout.textContent =
        "Aligned residue " + residueLabel(x) + " (chain " + chainLabel(x) + ")" +
        " · Scored residue " + residueLabel(y) + " (chain " + chainLabel(y) + ")" +
        " · " + formatValue(Number(row[x])) + " Å";
    }

    function selectedCell(event) {
      const box = canvas.getBoundingClientRect();
      return {
        x: Math.floor((((event.clientX - box.left) * (PLOT.width / box.width) - PLOT.left) / PLOT.size) * values[0].length),
        y: Math.floor((((event.clientY - box.top) * (PLOT.height / box.height) - PLOT.top) / PLOT.size) * values.length),
      };
    }

    function clampCell(x, y) {
      return {
        x: Math.max(0, Math.min(values[0].length - 1, x)),
        y: Math.max(0, Math.min(values.length - 1, y)),
      };
    }

    function draw() {
      const { width, height, left, top, size, legendX, legendWidth } = PLOT;
      const ctx = canvas.getContext("2d");
      ctx.clearRect(0, 0, width, height);
      const tokens = getComputedStyle(document.body);
      const ink = tokens.getPropertyValue("--ink").trim() || "#1d2a2f";
      const line = tokens.getPropertyValue("--line").trim() || "#d4ddd8";
      const ramp = themeName() === "dark" ? RAMP_DARK : RAMP_LIGHT;
      const rows = values.length;
      const columns = values[0].length;
      // PAE is a non-negative error: the domain starts at zero and ends at the
      // worst pair this model actually predicts. A plain loop, not
      // Math.max.apply: a real matrix spans hundreds of thousands of values
      // and spreading them into a call overflows the stack.
      let maximum = 0;
      for (let y = 0; y < rows; y += 1) {
        for (let x = 0; x < columns; x += 1) {
          const value = Number(values[y][x]);
          if (Number.isFinite(value) && value > maximum) maximum = value;
        }
      }
      const minimum = 0;
      const span = maximum - minimum || 1;

      const cells = document.createElement("canvas");
      cells.width = columns;
      cells.height = rows;
      const cellCtx = cells.getContext("2d");
      const image = cellCtx.createImageData(columns, rows);
      for (let y = 0; y < rows; y += 1) {
        for (let x = 0; x < columns; x += 1) {
          const value = Number(values[y][x]);
          const color = rampColor(ramp, Number.isFinite(value) ? (value - minimum) / span : null);
          const offset = (y * columns + x) * 4;
          image.data[offset] = color[0];
          image.data[offset + 1] = color[1];
          image.data[offset + 2] = color[2];
          image.data[offset + 3] = 255;
        }
      }
      cellCtx.putImageData(image, 0, 0);
      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(cells, left, top, size, size);

      const borderIndexes = chainBorderIndexes(chainIds);
      if (showBorders) {
        ctx.strokeStyle = ink;
        ctx.globalAlpha = 0.9;
        ctx.lineWidth = 1.5;
        borderIndexes.forEach((index) => {
          const offset = (size * index) / rows;
          ctx.beginPath();
          ctx.moveTo(left + offset, top);
          ctx.lineTo(left + offset, top + size);
          ctx.stroke();
          ctx.beginPath();
          ctx.moveTo(left, top + offset);
          ctx.lineTo(left + size, top + offset);
          ctx.stroke();
        });
        ctx.globalAlpha = 1;
      }

      ctx.strokeStyle = ink;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.rect(left, top, size, size);
      ctx.stroke();

      const gradient = ctx.createLinearGradient(0, top, 0, top + size);
      ramp.forEach((hex, index) => {
        gradient.addColorStop(1 - index / (ramp.length - 1), hex);
      });
      ctx.fillStyle = gradient;
      ctx.fillRect(legendX, top, legendWidth, size);
      ctx.strokeStyle = line;
      ctx.strokeRect(legendX + 0.5, top + 0.5, legendWidth, size);
      ctx.strokeStyle = ink;
      ctx.beginPath();
      for (let tick = 0; tick <= TICKS; tick += 1) {
        const y = top + size - (size * tick) / TICKS;
        ctx.moveTo(legendX + legendWidth, y);
        ctx.lineTo(legendX + legendWidth + 5, y);
      }
      for (let tick = 0; tick <= TICKS; tick += 1) {
        const index = Math.round(((rows - 1) * tick) / TICKS);
        const center = (size * (index + 0.5)) / rows;
        ctx.moveTo(left + center, top + size);
        ctx.lineTo(left + center, top + size + 5);
        ctx.moveTo(left, top + center);
        ctx.lineTo(left - 5, top + center);
      }
      ctx.stroke();

      const ring = selected;
      const centerX = left + (size * (ring.x + 0.5)) / columns;
      const centerY = top + (size * (ring.y + 0.5)) / rows;
      ctx.lineWidth = 3;
      ctx.strokeStyle = "#ffffff";
      ctx.strokeRect(centerX - 6, centerY - 6, 12, 12);
      ctx.lineWidth = 1;
      ctx.strokeStyle = ink;
      ctx.strokeRect(centerX - 6, centerY - 6, 12, 12);

      clearLabels(figure);
      for (let tick = 0; tick <= TICKS; tick += 1) {
        const index = Math.round(((rows - 1) * tick) / TICKS);
        const center = (size * (index + 0.5)) / rows;
        label(figure, residueLabel(index), {
          left: left + center + "px",
          top: top + size + 8 + "px",
          className: "af3-label-x",
        });
        label(figure, residueLabel(index), {
          top: top + center + "px",
          className: "af3-label-y af3-tick-y",
        });
      }
      label(figure, "PAE (Å) " + formatValue(maximum), {
        left: legendX, top: top - 18 + "px", className: "af3-title",
      });
      for (let tick = 0; tick <= TICKS; tick += 1) {
        label(figure, formatValue(minimum + (span * tick) / TICKS), {
          left: legendX + legendWidth + 8 + "px",
          top: top + size - (size * tick) / TICKS + "px",
          className: "af3-label-y af3-tick-legend",
        });
      }
      label(figure, "Aligned residue", {
        left: left + size / 2 + "px", top: top + size + 26 + "px", className: "af3-title af3-label-x",
      });
      label(figure, "Scored residue", {
        left: 20 + "px", top: top + size / 2 + "px", className: "af3-title af3-title-y",
      });

      const chains = new Set(chainIds.filter((id) => id != null));
      note.textContent =
        "PAE in ångströms: " + rows + " × " + columns + " scored and aligned residues across " +
        chains.size + " chains, from " + formatValue(minimum) + " to " + formatValue(maximum) +
        " Å in this model. Lower is better. Click the matrix or use the arrow keys to read a cell.";
      report(selected.x, selected.y);
    }

    canvas.addEventListener("click", (event) => {
      const cell = selectedCell(event);
      selected = clampCell(cell.x, cell.y);
      draw();
    });
    canvas.addEventListener("pointermove", (event) => {
      const cell = clampCell(selectedCell(event).x, selectedCell(event).y);
      report(cell.x, cell.y);
    });
    canvas.addEventListener("keydown", (event) => {
      const moves = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
      const move = moves[event.key];
      if (!move) return;
      event.preventDefault();
      selected = clampCell(selected.x + move[0], selected.y + move[1]);
      draw();
    });

    async function open(artifact) {
      const payload = await loadJson(artifact);
      const pae = payload.pae;
      if (!Array.isArray(pae) || !pae.length || !Array.isArray(pae[0])) {
        throw new Error("The confidence file does not contain a PAE matrix.");
      }
      values = pae;
      residueIds = Array.isArray(payload.token_res_ids) ? payload.token_res_ids : [];
      chainIds = Array.isArray(payload.token_chain_ids) ? payload.token_chain_ids : [];
      const canBorder = chainIds.length > 0;
      borders.disabled = !canBorder;
      if (!canBorder && showBorders) {
        showBorders = false;
        borders.setAttribute("aria-pressed", "false");
      }
      selected = { x: 0, y: 0 };
      if (selector) {
        const position = models.indexOf(artifact);
        if (position >= 0) selector.value = String(position);
      }
      draw();
    }

    if (!models.length) {
      fail(new Error("No confidence file was published for this run."));
      return { destroy() {} };
    }
    try {
      await open(models[0]);
    } catch (error) {
      fail(error);
    }
    return { destroy() {} };
  },
  destroy() {},
};
