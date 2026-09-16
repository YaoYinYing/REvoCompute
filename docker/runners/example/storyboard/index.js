/* Example Runner result composition; file rendering remains server-owned. */
export default {
  mount(host, context) {
    const heading = document.createElement("h2");
    heading.textContent = "Protein sequence statistics";
    const description = document.createElement("p");
    description.textContent = "Inspect the per-sequence table or the machine-readable aggregate summary.";
    const actions = document.createElement("div");
    [["statistics_table", "Open statistics table"], ["summary", "Open JSON summary"]].forEach(([id, label]) => {
      const file = context.files.get(id);
      const button = document.createElement("button");
      button.type = "button";
      button.className = "btn btn-soft";
      button.textContent = label;
      button.disabled = !file;
      if (file) button.addEventListener("click", () => context.services.openFile(file));
      actions.appendChild(button);
    });
    host.replaceChildren(heading, description, actions);
  },
  destroy() {}
};
