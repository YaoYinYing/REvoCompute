/* Example Runner result composition; file rendering remains server-owned. */
export default {
  mount(host, context) {
    const heading = document.createElement("h2");
    heading.textContent = "Protein sequence statistics";
    const description = document.createElement("p");
    description.textContent = "Each FASTA record is committed as its own work item. Open a per-record table or the task rollup.";
    const actions = document.createElement("div");
    const tables = context.files.get("statistics_table") || [];
    tables.forEach((file) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "btn btn-soft";
      button.textContent = file.path;
      button.addEventListener("click", () => context.services.openFile(file));
      actions.appendChild(button);
    });
    const rollup = context.files.get("task_summary");
    const summaryButton = document.createElement("button");
    summaryButton.type = "button";
    summaryButton.className = "btn btn-soft";
    summaryButton.textContent = "Open JSON summary";
    summaryButton.disabled = !rollup;
    if (rollup) summaryButton.addEventListener("click", () => context.services.openFile(rollup));
    actions.appendChild(summaryButton);
    host.replaceChildren(heading, description, actions);
  },
  destroy() {}
};
