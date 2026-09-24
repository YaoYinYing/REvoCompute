/* REvoCompute — manifest result preview plugin registry */
/* SPDX-License-Identifier: GPL-3.0-only */

(function (global) {
  "use strict";
  var Core = global.REvoComputePlugins;
  if (!Core) throw new Error("plugin-host.js must be loaded before result-preview-plugins.js");

  function createRegistry(renderers) {
    var registry = new Core.PluginRegistry("result preview");
    [
      { id: "structure", label: "3D structure", maxBytes: 64 * 1024 * 1024 },
      { id: "image", label: "Image", maxBytes: 32 * 1024 * 1024 },
      { id: "table", label: "Table", maxBytes: null },
      { id: "text", label: "Text", maxBytes: null }
    ].forEach(function (definition) {
      registry.register({
        id: definition.id,
        label: definition.label,
        maxBytes: definition.maxBytes,
        // The structure viewer is long-lived: it owns the host stage so its
        // booted browser bundle survives a switch to the next structure.
        stageOwner: definition.id === "structure",
        supports: function (artifact) { return artifact && !artifact.plugin && artifact.preview === definition.id; },
        render: renderers[definition.id]
      });
    });
    [
      "candidate-collection", "entity-table", "evidence-bundle", "alignment",
      "trajectory", "metric-series", "matrix", "scalar-summary"
    ].forEach(function (id) {
      if (typeof renderers[id] === "function") registry.register({ id: id, label: id, maxBytes: null, render: renderers[id] });
    });
    return registry;
  }

  function ResultPreviewHost(registry, stage, services) {
    this.registry = registry;
    this.stage = stage;
    this.services = services || {};
    this.active = null;
    this.controller = null;
    this.generation = 0;
  }

  ResultPreviewHost.prototype.render = async function (subject, context) {
    var plugin = this.registry.resolve(subject, context || this.services);
    if (!plugin) {
      this.destroy(null);
      throw new Error("No inline preview is available for this result.");
    }
    if (plugin.maxBytes && Number(subject.size || 0) > plugin.maxBytes) {
      this.destroy(null);
      throw new Error("This file exceeds the safe inline preview limit. Download it instead.");
    }
    // A viewer with a costly boot (Mol*) asks to keep its live nodes across a
    // switch between the same kind of result, so the boot happens once per
    // session rather than once per structure.
    var keep = this.services.preserve ? this.services.preserve(this.stage, plugin) : [];
    this.destroy(keep);
    var surface;
    if (plugin.stageOwner) {
      surface = this.stage;
    } else {
      surface = document.createElement("div");
      surface.className = "result-plugin-surface";
      this.stage.appendChild(surface);
    }
    var generation = this.generation;
    var controller = new AbortController();
    this.stage.setAttribute("aria-busy", "true");
    this.controller = controller;
    this.active = { plugin: plugin, instance: null };
    var services = Object.assign({}, this.services, context || {}, { signal: controller.signal });
    if (this.services.statusNode) this.services.statusNode.textContent = "Loading result…";
    try {
      var instance = await plugin.render(subject, surface, services);
      if (generation !== this.generation) {
        if (instance && typeof instance.destroy === "function") instance.destroy();
        return null;
      }
      this.active.instance = instance || null;
      if (this.services.statusNode) this.services.statusNode.textContent = "Result loaded.";
      return plugin;
    } catch (error) {
      if (generation !== this.generation || controller.signal.aborted) return null;
      throw error;
    } finally {
      if (generation === this.generation) this.stage.setAttribute("aria-busy", "false");
    }
  };

  ResultPreviewHost.prototype.destroy = function (keep) {
    this.generation += 1;
    if (this.controller) this.controller.abort();
    if (this.active && this.active.instance && typeof this.active.instance.destroy === "function") {
      this.active.instance.destroy();
    }
    if (this.services.beforeClear) this.services.beforeClear();
    this.controller = null;
    this.active = null;
    var kept = keep || [];
    Array.prototype.slice.call(this.stage.children).forEach(function (child) {
      if (kept.indexOf(child) === -1) child.remove();
    });
    this.stage.setAttribute("aria-busy", "false");
  };

  global.REvoComputeResultPreviews = Object.freeze({
    createRegistry: createRegistry,
    ResultPreviewHost: ResultPreviewHost,
    FileViewerRegistry: createRegistry,
    FileViewerHost: ResultPreviewHost
  });
})(window);
