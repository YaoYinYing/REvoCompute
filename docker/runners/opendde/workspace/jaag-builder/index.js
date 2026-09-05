/* REvoCompute - JAAG-compatible target-neutral structure input builder */
/* SPDX-License-Identifier: GPL-3.0-only */

(function (global) {
  "use strict";
  var workspaceApi = global.REvoComputeInputWorkspace;
  if (!workspaceApi) throw new Error("input-workspace.js must be loaded before input-workspace-jaag.js");

  function asDocument(value, target) {
    if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("JAAG input must be a JSON object");
    if (target === "alphafold3" && (value.format_version || value.modelSeeds || value.sequences)) return value;
    if (target === "opendde" && (value.model_name || value.job_name || value.inputs)) return value;
    var entities = Array.isArray(value.entities) ? value.entities : [];
    if (!entities.length) throw new Error("JAAG input needs at least one molecular entity");
    if (target === "opendde") return { name: value.name || "jaag_input", entities: entities };
    return {
      name: value.name || "jaag_input", format_version: 1, modelSeeds: value.model_seeds || [1],
      sequences: entities.map(function (entity) {
        var type = entity.type || "protein", ids = Array.isArray(entity.id) ? entity.id : [entity.id || "A"];
        if (type === "ligand") return { ligand: { id: ids, smiles: entity.smiles || entity.ccdCode || "" } };
        var key = type === "dna" ? "dna" : type === "rna" ? "rna" : "protein";
        return { [key]: { id: ids, sequence: entity.sequence || "" } };
      })
    };
  }

  global.REvoComputeJaag = Object.freeze({ serialize: asDocument });

  workspaceApi.registry.register({
    id: "jaag-builder",
    mount: function (target, definition, context) {
      var options = definition.options || {};
      var targetName = options.target || (context.form.name === "opendde" ? "opendde" : "alphafold3");
      var selector = document.createElement("select"); selector.className = "text-input";
      ["alphafold3", "opendde"].forEach(function (name) {
        var option = document.createElement("option"); option.value = name; option.textContent = name === "opendde" ? "OpenDDE" : "AlphaFold 3";
        option.selected = name === targetName; selector.appendChild(option);
      });
      var input = document.createElement("textarea"); input.className = "sequence-input";
      input.placeholder = '{"name":"complex","entities":[{"type":"protein","id":"A","sequence":"..."}]}';
      input.setAttribute("aria-label", "JAAG biomolecular input");
      var error = document.createElement("p"); error.className = "param-error"; error.hidden = true;
      target.appendChild(selector); target.appendChild(input); target.appendChild(error);
      function parse() { return asDocument(JSON.parse(input.value), selector.value); }
      function materialize(documentValue) {
        context.setGeneratedFile(new File([JSON.stringify(documentValue, null, 2) + "\n"], "jaag-" + selector.value + ".json", { type: "application/json" }));
      }
      function clear() { error.hidden = true; error.textContent = ""; input.removeAttribute("aria-invalid"); context.changed(); }
      input.addEventListener("input", clear); selector.addEventListener("change", clear);
      return {
        readValue: function () {
          if (!input.value.trim()) { context.setGeneratedFile(null); return null; }
          var documentValue = parse();
          materialize(documentValue);
          return { schema: "jaag-superset", target: selector.value, document: documentValue };
        },
        summarize: function () { return input.value.trim() ? { label: "Structure input", value: "JAAG " + selector.value + " document" } : null; },
        validate: function () {
          if (!input.value.trim()) { context.setGeneratedFile(null); return []; }
          try { var documentValue = parse(); materialize(documentValue); clear(); return []; } catch (exception) {
            input.setAttribute("aria-invalid", "true"); error.textContent = exception.message || "Invalid JAAG JSON"; error.hidden = false; return [error.textContent];
          }
        },
        destroy: function () { input.removeEventListener("input", clear); selector.removeEventListener("change", clear); context.setGeneratedFile(null); }
      };
    }
  });
})(window);
