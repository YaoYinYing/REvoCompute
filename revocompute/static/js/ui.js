/* REvoCompute — shared presentation preferences and dialogs */
/* SPDX-License-Identifier: GPL-3.0-only */

(function (global) {
  "use strict";

  var preferences = Object.freeze({
    catalogDensity: { key: "revocompute.ui.catalog-density.v1", values: ["comfortable", "compact"], fallback: "comfortable" },
    taskLayout: { key: "revocompute.ui.task-layout.v1", values: ["detailed", "compact", "table"], fallback: "detailed" },
  });
  var activeDialog = null;

  function preference(name) {
    var definition = preferences[name];
    if (!definition) throw new Error("Unknown UI preference: " + name);
    try {
      var value = global.localStorage.getItem(definition.key);
      return definition.values.includes(value) ? value : definition.fallback;
    } catch (_) {
      return definition.fallback;
    }
  }

  function setPreference(name, value) {
    var definition = preferences[name];
    if (!definition || !definition.values.includes(value)) return false;
    try { global.localStorage.setItem(definition.key, value); } catch (_) { /* presentation still works */ }
    return true;
  }

  function bindSegmented(root, name, onChange) {
    if (!root) return;
    function select(value, persist) {
      var definition = preferences[name];
      if (!definition || !definition.values.includes(value)) return;
      root.querySelectorAll("button[data-value]").forEach(function (button) {
        var selected = button.dataset.value === value;
        button.setAttribute("aria-pressed", String(selected));
        button.classList.toggle("active", selected);
      });
      if (persist) setPreference(name, value);
      if (onChange) onChange(value);
    }
    function clicked(event) {
      var button = event.target.closest("button[data-value]");
      if (button && root.contains(button)) select(button.dataset.value, true);
    }
    root.addEventListener("click", clicked);
    select(preference(name), false);
  }

  function dialogElement() {
    var dialog = document.getElementById("uiDialog");
    if (dialog) return dialog;
    dialog = document.createElement("dialog");
    dialog.id = "uiDialog";
    dialog.className = "ui-dialog";
    dialog.setAttribute("aria-labelledby", "uiDialogTitle");
    dialog.innerHTML =
      '<div class="ui-dialog-frame">' +
        '<header><h2 id="uiDialogTitle"></h2><button class="ui-dialog-close" type="button" data-dialog-cancel aria-label="Close dialog">&times;</button></header>' +
        '<div class="ui-dialog-body" id="uiDialogBody"></div>' +
        '<div class="ui-dialog-actions" id="uiDialogActions"></div>' +
      '</div>';
    document.body.appendChild(dialog);
    return dialog;
  }

  function openDialog(options) {
    options = options || {};
    if (activeDialog) activeDialog(null);
    var dialog = dialogElement();
    var title = dialog.querySelector("#uiDialogTitle");
    var body = dialog.querySelector("#uiDialogBody");
    var actions = dialog.querySelector("#uiDialogActions");
    var close = dialog.querySelector(".ui-dialog-close");
    title.textContent = options.title || "Confirm action";
    body.replaceChildren(); actions.replaceChildren();
    if (options.message) { var message = document.createElement("p"); message.textContent = options.message; body.appendChild(message); }
    if (options.content) body.appendChild(options.content);
    close.hidden = options.cancelLabel === null;
    return new Promise(function (resolve) {
      var settled = false;
      function finish(value) {
        if (settled) return;
        settled = true; activeDialog = null;
        dialog.removeEventListener("cancel", cancelled);
        if (dialog.open) dialog.close();
        resolve(value);
      }
      function cancelled(event) { event.preventDefault(); finish(null); }
      activeDialog = finish;
      dialog.addEventListener("cancel", cancelled);
      close.onclick = function () { finish(null); };
      if (options.cancelLabel !== null) {
        var cancel = document.createElement("button"); cancel.type = "button"; cancel.className = "btn btn-soft";
        cancel.textContent = options.cancelLabel || "Cancel"; cancel.addEventListener("click", function () { finish(null); }); actions.appendChild(cancel);
      }
      if (options.confirmLabel) {
        var confirm = document.createElement("button"); confirm.type = "button";
        confirm.className = "btn " + (options.destructive ? "btn-danger" : "btn-primary");
        confirm.textContent = options.confirmLabel; confirm.addEventListener("click", function () { confirm.disabled = true; finish(options.value == null ? true : options.value()); });
        actions.appendChild(confirm);
      }
      dialog.showModal();
      if (options.initialFocus && options.initialFocus.isConnected) options.initialFocus.focus();
    });
  }

  function confirm(options) {
    return openDialog(Object.assign({ confirmLabel: "Confirm", cancelLabel: "Cancel", destructive: true }, options));
  }

  function alert(options) {
    if (typeof options === "string") options = { message: options };
    return openDialog(Object.assign({ title: "Notice", confirmLabel: "Close", cancelLabel: null }, options));
  }

  function prompt(options) {
    options = options || {};
    var field = document.createElement("label"); field.className = "field";
    var label = document.createElement("span"); label.textContent = options.label || "Details";
    var input = document.createElement(options.multiline === false ? "input" : "textarea");
    input.className = "text-input"; input.value = options.defaultValue || "";
    if (options.maxLength) input.maxLength = options.maxLength;
    if (input.tagName === "TEXTAREA") input.rows = options.rows || 4;
    field.append(label, input);
    var config = Object.assign({}, options, { content: field, initialFocus: input, confirmLabel: options.confirmLabel || "Continue", value: function () { return input.value; } });
    return openDialog(config).then(function (value) {
      if (value == null) return null;
      if (options.required && !String(value).trim()) return prompt(Object.assign({}, options, { defaultValue: value, message: options.requiredMessage || "Enter a value to continue." }));
      return value;
    });
  }

  global.REvoComputeUI = Object.freeze({
    preferences: preferences,
    preference: preference,
    setPreference: setPreference,
    bindSegmented: bindSegmented,
    openDialog: openDialog,
    confirm: confirm,
    alert: alert,
    prompt: prompt,
  });
})(window);
