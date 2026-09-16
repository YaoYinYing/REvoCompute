/* GREMLIN_LH scientific result composition; generic file rendering stays in the server. */

function downloadUrl(artifact) {
  return artifact.url + (artifact.url.indexOf("?") === -1 ? "?" : "&") + "download=1";
}

function artifactAction(artifact, label, context) {
  // The server previews artifacts it can fetch by URL directly. Other logical
  // files (nested tables, the MRF, JSON) stay downloadable, which also keeps
  // the Runner from duplicating the server's viewer vocabulary.
  if (typeof artifact.media_type === "string" && artifact.media_type.startsWith("image/")) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "btn btn-soft";
    button.textContent = `Inspect ${label}`;
    button.addEventListener("click", () => context.services.openFile(artifact));
    return button;
  }
  const link = document.createElement("a");
  link.className = "btn btn-soft";
  link.href = downloadUrl(artifact);
  link.setAttribute("download", "");
  link.textContent = `Download ${label}`;
  return link;
}

export default {
  mount(host, context) {
    const heading = document.createElement("h2");
    heading.textContent = "GREMLIN_LH coevolution analysis";

    const description = document.createElement("p");
    description.textContent =
      "A Potts/MRF model fitted to the submitted alignment. Inspect the modeled alignment, " +
      "the per-position profile, the ranked pairwise couplings, and the durable model artifact.";

    const sections = [
      {
        title: "Alignment and preprocessing",
        note: "What GREMLIN actually modeled, including the filtered alignment and sequence weighting.",
        entries: [
          ["alignment", "filtered alignment (A3M)"],
          ["alignment_statistics", "alignment statistics"],
          ["sequence_weights", "per-sequence weights"],
          ["query", "query sequence"],
        ],
      },
      {
        title: "Model",
        note: "Durable single-site fields and pairwise couplings, plus fit provenance.",
        entries: [
          ["mrf_model", "GREMLIN MRF model (NPZ)"],
          ["model_metadata", "model metadata"],
          ["training_history", "optimization history"],
          ["sequence_scores", "per-sequence scores"],
        ],
      },
      {
        title: "Profile and couplings",
        note: "Observed per-position state frequencies and APC-corrected residue-pair couplings.",
        entries: [
          ["profile", "position profile (TSV)"],
          ["pairwise_scores", "ranked residue pairs"],
          ["apc_matrix", "APC coupling matrix"],
          ["raw_matrix", "raw coupling matrix"],
          ["coupling_plot", "coupling heatmap"],
        ],
      },
      {
        title: "Summary",
        note: "Run-level metadata for this fit.",
        entries: [["summary", "summary JSON"]],
      },
    ];

    const container = document.createElement("div");
    container.className = "storyboard-sections";

    sections.forEach((section) => {
      const group = document.createElement("section");
      group.className = "storyboard-section";
      const title = document.createElement("h3");
      title.textContent = section.title;
      const note = document.createElement("p");
      note.className = "storyboard-note";
      note.textContent = section.note;
      const actions = document.createElement("div");
      actions.className = "storyboard-actions";
      section.entries.forEach(([id, label]) => {
        const artifact = context.files.get(id);
        if (artifact) {
          actions.appendChild(artifactAction(artifact, label, context));
        } else {
          const unavailable = document.createElement("span");
          unavailable.className = "storyboard-unavailable";
          unavailable.textContent = `${label} unavailable`;
          actions.appendChild(unavailable);
        }
      });
      group.append(title, note, actions);
      container.appendChild(group);
    });

    host.replaceChildren(heading, description, container);
  },
  destroy() {},
};
