/* REvoCompute — scientific experiment submission orchestration */
/* SPDX-License-Identifier: GPL-3.0-only */

(function () {
  "use strict";
  var A = window.REvoDesignAuth, T = window.REvoDesignTheme;
  var Workspace = window.REvoComputeInputWorkspace.InputWorkspace;
  var form = document.getElementById("uploadForm"), fileInput = document.getElementById("fileInput");
  var statusNode = document.getElementById("uploadStatus"), submitButton = document.getElementById("uploadButton");
  var clearButton = document.getElementById("clearButton"), workspaceRoot = document.getElementById("inputWorkspace");
  var chooser = document.getElementById("methodChooser"), workbench = document.getElementById("experimentWorkbench");
  var methodGroups = document.getElementById("methodGroups"), methodSearch = document.getElementById("methodSearch");
  var methodCategory = document.getElementById("methodCategory"), UI = window.REvoComputeUI;
  var catalogStatus = document.getElementById("catalogStatus");
  var validationChecks = document.getElementById("validationChecks"), validationSummary = document.getElementById("validationSummary");
  var catalog = { categories: [], task_types: [] }, currentForm = null, loadController = null, loadGeneration = 0;
  var serverPreflight = null;

  function setStatus(message, kind) {
    statusNode.className = "status" + (kind ? " " + kind : ""); statusNode.textContent = message;
  }
  function sanitizeHeader(value) {
    var cleaned = String(value || "").trim().replace(/\s+/g, "_").replace(/[^A-Za-z0-9_.-]/g, "");
    return cleaned || "sequence";
  }
  function wrapSequence(sequence, width) {
    var lines = []; for (var index = 0; index < sequence.length; index += width) lines.push(sequence.slice(index, index + width)); return lines.join("\n");
  }
  function categoryFor(name) { return catalog.categories.find(function (category) { return category.name === name; }); }

  function selectMethod(name) {
    var exists = catalog.task_types.some(function (task) { return task.name === name; });
    if (!exists) return showChooser(name ? "That method is not available on this server." : "Choose a method to begin.");
    var url = new URL(window.location.href); url.searchParams.set("task_type", name); history.replaceState(null, "", url);
    fetchFormDefinition(name);
  }

  function showChooser(message) {
    if (loadController) loadController.abort();
    if (currentForm) workspace.destroy(); currentForm = null; workspaceRoot.replaceChildren();
    chooser.hidden = false; workbench.hidden = true;
    catalogStatus.textContent = message || "Choose a method to begin."; catalogStatus.className = "status";
    var url = new URL(window.location.href); url.searchParams.delete("task_type"); history.replaceState(null, "", url);
    methodSearch.focus();
  }

  function methodCard(task) {
    var button = document.createElement("button"); button.type = "button"; button.className = "method-card";
    button.dataset.search = [task.display_name, task.name, task.category, task.summary].join(" ").toLowerCase();
    var title = document.createElement("strong"); title.textContent = task.display_name;
    var summary = document.createElement("span"); summary.textContent = task.summary;
    button.append(title, summary);
    if (task.access && task.access.restricted) {
      var access = document.createElement("small");
      access.className = "access-state";
      access.textContent = task.access.granted ? "Access granted" : (task.access.request_status === "pending" ? "Access requested" : "Restricted");
      button.appendChild(access);
    }
    button.addEventListener("click", function () { selectMethod(task.name); }); return button;
  }

  function renderCatalog(query) {
    query = String(query || "").trim().toLowerCase(); methodGroups.replaceChildren(); var shown = 0;
    catalog.categories.forEach(function (category) {
      var tasks = catalog.task_types.filter(function (task) {
        return task.category === category.name && (!methodCategory.value || methodCategory.value === category.name) && (!query || [task.display_name, task.name, task.category, task.summary].join(" ").toLowerCase().includes(query));
      });
      if (!tasks.length) return;
      var section = document.createElement("section"); section.className = "method-group";
      var header = document.createElement("header"), title = document.createElement("h2"), description = document.createElement("p");
      title.textContent = category.label; description.textContent = category.description || ""; header.append(title, description);
      var grid = document.createElement("div"); grid.className = "method-grid"; tasks.forEach(function (task) { grid.appendChild(methodCard(task)); shown += 1; });
      section.append(header, grid); methodGroups.appendChild(section);
    });
    catalogStatus.textContent = shown ? shown + " method" + (shown === 1 ? "" : "s") + " available" : "No methods match that search.";
  }

  async function mountForm(definition) {
    currentForm = definition;
    try {
      await workspace.mountAsync(definition);
    } catch (error) {
      setStatus(error.message || "Could not load the selected workspace editor.", "error");
      workspace.destroy();
      return;
    }
    var category = categoryFor(definition.category);
    document.getElementById("activeTaskCategory").textContent = category ? category.label : definition.category;
    document.getElementById("activeTaskName").textContent = definition.display_name;
    document.getElementById("taskSummary").textContent = definition.summary;
    document.getElementById("taskUseWhen").textContent = definition.use_when;
    document.getElementById("taskInput").textContent = definition.input_summary;
    document.getElementById("taskOutput").textContent = definition.output_summary;
    document.getElementById("taskAccelerator").textContent = definition.gpus ? "GPU method" : "CPU method";
    document.getElementById("taskNetwork").hidden = !definition.requires_network;
    renderRunnerAccess(definition.access);
    document.getElementById("taskDetails").href = "/runners/" + encodeURIComponent(definition.name);
    var considerations = document.getElementById("taskConsiderations"); considerations.replaceChildren();
    definition.considerations.forEach(function (item) { var row = document.createElement("li"); row.textContent = item; considerations.appendChild(row); });
    submitButton.textContent = "Review " + definition.display_name; chooser.hidden = true; workbench.hidden = false;
    setStatus("Preparing " + definition.display_name + "."); refreshValidation(); window.scrollTo({ top: 0, behavior: "auto" });
  }

  function renderRunnerAccess(access) {
    var panel = document.getElementById("runnerAccess"), button = document.getElementById("requestRunnerAccess");
    panel.hidden = !access || !access.restricted;
    if (panel.hidden) return;
    document.getElementById("runnerAccessTitle").textContent = access.granted ? "Access granted" : (access.request_status === "pending" ? "Access requested" : "Restricted access");
    document.getElementById("runnerAccessSummary").textContent = (access.notice && access.notice.summary) || access.description;
    button.hidden = access.granted || access.request_status === "pending" || !access.requestable;
  }

  async function requestRunnerAccess() {
    if (!currentForm || !currentForm.access) return;
    var button = document.getElementById("requestRunnerAccess");
    var reason = await UI.prompt({ title: "Request Runner access", label: "Research use and affiliation", message: "The administrator verifies eligibility under this Runner's configured access policy.", confirmLabel: "Request access", required: true, maxLength: 1000 });
    if (!reason || !reason.trim()) return;
    button.disabled = true;
    try {
      var response = await A.authFetch("/compute/api/access/requests", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ policy_id: currentForm.access.policy_id, reason: reason.trim() }),
      });
      if (!response.ok) { var payload = await response.json(); throw new Error(payload.error || "Request failed"); }
      currentForm.access.request_status = "pending";
      renderRunnerAccess(currentForm.access); refreshValidation();
    } catch (error) { setStatus(error.message, "error"); button.disabled = false; }
  }

  function parametersFromSchema(schema) {
    var required = new Set(schema.required || []);
    var typeMap = { string: "str", integer: "int", number: "float", boolean: "bool" };
    return Object.entries(schema.properties || {}).map(function (entry) {
      var name = entry[0], property = entry[1] || {};
      return {
        name: name,
        type: typeMap[property.type] || "str",
        default: property.default,
        required: required.has(name),
        description: property.description || "",
        label: property.title || name.replaceAll("_", " ").replace(/\b\w/g, function (letter) { return letter.toUpperCase(); }),
        choices: property.enum || [],
        minimum: property.minimum,
        maximum: property.maximum,
        step: property.multipleOf,
        unit: property["x-unit"] || "",
        help: property["x-help"] || "",
        advanced: Boolean(property["x-advanced"]),
        ui_control: property["x-ui-control"] || {},
      };
    });
  }

  async function fetchFormDefinition(name) {
    if (loadController) loadController.abort(); loadController = new AbortController(); var generation = ++loadGeneration;
    chooser.hidden = true; workbench.hidden = false; workspaceRoot.replaceChildren(); setStatus("Loading experiment protocol…", "busy");
    try {
      var response = await fetch("/compute/api/types/" + encodeURIComponent(name), { signal: loadController.signal });
      if (!response.ok) throw new Error("Failed to load method"); var definition = await response.json();
      var schemaResponse = await fetch(definition.parameters_url, { signal: loadController.signal });
      if (!schemaResponse.ok) throw new Error("Failed to load method parameters");
      definition.params = parametersFromSchema(await schemaResponse.json());
      if (generation !== loadGeneration) return; await mountForm(definition);
    } catch (error) {
      if (error.name === "AbortError") return;
      showChooser("Could not load the selected method. Check your connection and try again.");
    }
  }

  function validationRow(kind, text) {
    var row = document.createElement("li"); row.className = "validation-row " + kind;
    var marker = document.createElement("span"); marker.className = "validation-marker"; marker.setAttribute("aria-hidden", "true");
    row.append(marker, document.createTextNode(text)); return row;
  }

  function refreshValidation(preserveServerPreflight) {
    if (!preserveServerPreflight) serverPreflight = null;
    validationChecks.replaceChildren();
    if (!currentForm) { validationSummary.textContent = "Choose a method"; submitButton.disabled = true; return []; }
    var errors = workspace.validate();
    if (currentForm.access && currentForm.access.restricted && !currentForm.access.granted) errors.push("Runner access approval is required.");
    if (errors.length) {
      errors.forEach(function (error) { validationChecks.appendChild(validationRow("error", error)); });
    } else if (!serverPreflight) {
      validationChecks.appendChild(validationRow("ok", "Input contract satisfied"));
      validationChecks.appendChild(validationRow("ok", "Method settings are valid"));
      validationChecks.appendChild(validationRow("info", "Run Core preflight to complete the review"));
    } else {
      var admission = serverPreflight.admission || {};
      validationChecks.appendChild(validationRow(serverPreflight.security.status === "passed" ? "ok" : "error", "Input security " + serverPreflight.security.status));
      validationChecks.appendChild(validationRow(serverPreflight.contract.status === "passed" ? "ok" : "error", "Scientific contract " + serverPreflight.contract.status));
      if (admission.runner_ready != null) validationChecks.appendChild(validationRow(admission.runner_ready ? "ok" : "error", "Runner " + (admission.runner_ready ? "ready" : "unavailable")));
      if (admission.infrastructure_status) {
        var infrastructureKind = admission.infrastructure_ready ? (admission.infrastructure_status === "DEGRADED" ? "info" : "ok") : "error";
        validationChecks.appendChild(validationRow(infrastructureKind, "Infrastructure " + admission.infrastructure_status.toLowerCase()));
      }
      if (admission.scheduler_capacity) validationChecks.appendChild(validationRow("info", "Scheduler capacity " + admission.scheduler_capacity.toLowerCase()));
      if (currentForm.gpus && admission.gpu_capacity) validationChecks.appendChild(validationRow("info", "GPU capacity " + admission.gpu_capacity.toLowerCase()));
      if (currentForm.gpus && admission.gpu_credit_sufficient != null) {
        validationChecks.appendChild(validationRow(admission.gpu_credit_sufficient ? "ok" : "error", admission.gpu_credit_sufficient ? "GPU credit available" : "GPU credit exhausted"));
      }
      (serverPreflight.warnings || []).forEach(function (finding) { validationChecks.appendChild(validationRow("info", finding.message)); });
      (serverPreflight.errors || []).forEach(function (finding) { validationChecks.appendChild(validationRow("error", finding.message)); });
    }
    if (errors.length) validationSummary.textContent = errors.length + " issue" + (errors.length === 1 ? "" : "s") + " to fix";
    else if (serverPreflight && serverPreflight.valid) validationSummary.textContent = "Preflight passed";
    else if (serverPreflight) validationSummary.textContent = "Preflight blocked";
    else validationSummary.textContent = "Ready for review";
    validationSummary.className = errors.length || (serverPreflight && !serverPreflight.valid) ? "has-issues" : "ready";
    submitButton.disabled = errors.length > 0;
    submitButton.textContent = serverPreflight && serverPreflight.valid
      ? "Run " + currentForm.display_name
      : (serverPreflight ? "Review again" : "Review " + currentForm.display_name);
    return errors;
  }

  var workspace = new Workspace(workspaceRoot, { fileInput: fileInput, status: setStatus, onChange: refreshValidation });

  function buildSubmissionFormData(capabilities) {
    var sequence = workspace.sequence(), inputFiles = workspace.inputFiles();
    if (sequence) {
      var sequenceRole = workspace.sequenceRole();
      var role = currentForm.inputs.find(function (item) { return item.id === sequenceRole; });
      var extension = role.extensions[0], header = sanitizeHeader(workspace.sequenceName());
      var generated = new File([">" + header + "\n" + wrapSequence(sequence, 80) + "\n"], header + extension, { type: "text/plain" });
      inputFiles.push({ role: sequenceRole, file: generated });
    }
    var formData = new FormData();
    inputFiles.forEach(function (item) { formData.append("files", item.file); formData.append("input_paths", item.file.webkitRelativePath || item.file.name); formData.append("input_roles", item.role); });
    formData.append("task_type", currentForm.name);
    formData.append("workspace", JSON.stringify({ version: 2, capabilities: capabilities }));
    var params = workspace.paramValues(); Object.keys(params).forEach(function (name) { formData.append("params[" + name + "]", params[name]); });
    return formData;
  }

  async function submitTask() {
    if (!currentForm) return showChooser("Choose a method before running an experiment.");
    var capabilities = workspace.collect(), errors = refreshValidation(true);
    if (errors.length) { setStatus("Fix the highlighted issues before running this experiment.", "error"); var first = form.querySelector('[aria-invalid="true"]'); if (first) first.focus(); return; }
    var formData = buildSubmissionFormData(capabilities);
    if (!serverPreflight || !serverPreflight.valid) {
      submitButton.disabled = true; clearButton.disabled = true; setStatus("Running Core security, contract, and admission preflight…", "busy");
      try {
        var preflightResponse = await A.authFetch("/compute/api/preflight/" + encodeURIComponent(currentForm.name), { method: "POST", body: formData });
        serverPreflight = await preflightResponse.json();
        refreshValidation(true);
        setStatus(serverPreflight.valid ? "Preflight passed. Review the checks, then run the experiment." : "Preflight blocked. Review the reported checks before retrying.", serverPreflight.valid ? "ok" : "error");
      } catch (error) {
        serverPreflight = null; setStatus("Preflight failed: " + error.message, "error");
      } finally {
        clearButton.disabled = false; refreshValidation(true);
      }
      return;
    }
    submitButton.disabled = true; clearButton.disabled = true; setStatus("Uploading the immutable snapshot and queueing the task…", "busy");
    try {
      var response = await A.authFetch("/compute/api/post", { method: "POST", body: formData });
      if (response.ok || response.status === 202) { setStatus("Experiment queued. Opening the dashboard…", "ok"); window.location.assign("/compute/dashboard"); return; }
      var payload = (response.headers.get("Content-Type") || "").includes("application/json") ? await response.json() : {};
      var message = payload.error || payload.message || "Submission failed (HTTP " + response.status + ")";
      if (payload.details) message += ": " + payload.details.map(function (detail) { return (detail.field || detail.role || detail.code) + " " + detail.message; }).join("; "); setStatus(message, "error");
    } catch (error) { setStatus("Network error: " + error.message, "error"); }
    finally { clearButton.disabled = false; refreshValidation(); }
  }

  form.addEventListener("submit", function (event) { event.preventDefault(); submitTask(); });
  document.getElementById("requestRunnerAccess").addEventListener("click", requestRunnerAccess);
  clearButton.addEventListener("click", function () { if (!currentForm) return; workspace.mount(currentForm); setStatus("Workspace cleared.", "ok"); refreshValidation(); var first = form.querySelector("button, input, textarea, select"); if (first) first.focus(); });
  document.getElementById("changeMethod").addEventListener("click", function () { showChooser("Choose another method."); });
  methodSearch.addEventListener("input", function () { renderCatalog(methodSearch.value); });
  methodCategory.addEventListener("change", function () { renderCatalog(methodSearch.value); });
  UI.bindSegmented(document.getElementById("catalogDensity"), "catalogDensity", function (value) { methodGroups.dataset.density = value; });

  async function loadCatalog() {
    try {
      var response = await fetch("/compute/api/types"); if (!response.ok) throw new Error("Failed to load methods"); catalog = await response.json();
      catalog.categories.forEach(function (category) { var option = document.createElement("option"); option.value = category.name; option.textContent = category.label; methodCategory.appendChild(option); });
      renderCatalog("");
      var requested = new URLSearchParams(window.location.search).get("task_type");
      if (requested && catalog.task_types.some(function (task) { return task.name === requested; })) selectMethod(requested);
      else showChooser(requested ? "That method is not available on this server." : "Choose a method to begin.");
    } catch (error) { catalogStatus.textContent = "Could not reach the server. Check your connection and reload the page."; catalogStatus.className = "status error"; }
  }

  T.initToggle(document.getElementById("themeToggle")); loadCatalog();
})();
