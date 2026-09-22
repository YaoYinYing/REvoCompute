/* REvoCompute — sandboxed Mol* host shell (runs inside the viewer iframe) */
/* SPDX-License-Identifier: GPL-3.0-only */

/* This page lives under its own CSP that permits 'unsafe-eval' (Mol*'s
   bundle calls new Function at load) — scoped to this shell only. All
   structure data arrives via postMessage from the authenticated parent;
   nothing is fetched here. */

(function () {
  "use strict";

  var MOLSTAR_VERSION = "5.11.0";
  var MOLSTAR_BASE = "https://cdn.jsdelivr.net/npm/molstar@" + MOLSTAR_VERSION + "/build/viewer/";
  var MOLSTAR_SCRIPT_INTEGRITY = "sha384-5Mfx4eL50NkWPky+mcH//qY0sbml4il0CLFFmrMp8uv/saB3Z6uZMHn2dUpAnH92";
  var MOLSTAR_STYLE_INTEGRITY = "sha384-RIontCdJN53gEl2fmiHN+4bscIBvaUaOiCeeGktXqmFqdEBF+COnSdt9O4IKFSvq";
  var MOLSTAR_DARK_STYLE_INTEGRITY = "sha384-LDnli0hRX1wCV3HrFyNGSy145zkcGA8P6EZPC8VyLVS6+TJO3jgsncYeD+cZuLjO";
  var MOLSTAR_COLORS = { plddt: "plddt-confidence", confidence: "plddt-confidence", chain: "chain-id", rainbow: "sequence-id" };
  var MOLSTAR_CANVAS_COLORS = { light: 0xf8faf7, dark: 0x111318 };
  // One presentation vocabulary, shared with the py2Dmol fallback (which
  // supports a bounded subset). A preset is what the model is drawn as; a
  // color mode is how it is shaded.
  //
  // Each representation preset names an identifier in Mol*'s own
  // *representation* registry, which `builders.structure.representation`
  // resolves. `cartoon_ligand` is the one curated composition (polymer
  // cartoon + ligand ball and stick + carbohydrate symbols) and is applied
  // through the component manager's preset path instead.
  var MOLSTAR_PRESETS = {
    cartoon: "cartoon",
    cartoon_ligand: "polymer-and-ligand",
    sticks: "ball-and-stick",
    surface_ligand: "molecular-surface"
  };
  var MOLSTAR_COMPOSED_PRESETS = { cartoon_ligand: true };
  var DEFAULT_PRESET = "cartoon";
  var DEFAULT_COLOR = "chain";

  var stateNode = document.getElementById("shellState");
  var host = document.getElementById("viewerHost");
  var assetsPromise = null;
  var viewer = null;
  var viewerId = null;
  var activeTheme = "light";
  var selectionSubscription = null;
  var activeRequestId = null;

  async function prepareViewer(message) {
    await ensureMolstarAssets();
    if (viewer) {
      await viewer.plugin.clear();
    } else {
      setLoadingPhase("Preparing the interactive structure…");
      viewerId = "molstar-shell-" + Math.random().toString(36).slice(2);
      var target = document.createElement("div");
      target.id = viewerId;
      host.appendChild(target);
      viewer = await window.molstar.Viewer.create(target.id, {
        layoutIsExpanded: false,
        layoutShowControls: Boolean(message.showControls),
        layoutShowRemoteState: false,
        layoutShowSequence: true,
        layoutShowLog: false,
        layoutShowLeftPanel: false,
        viewportShowExpand: true,
        viewportShowSelectionMode: true,
        viewportShowAnimation: true,
        viewportShowTrajectoryControls: true
      });
    }
    viewer.plugin.canvas3d.setProps({ renderer: { backgroundColor: MOLSTAR_CANVAS_COLORS[activeTheme] } });
  }

  function setLoadingPhase(text) {
    stateNode.dataset.state = "loading";
    stateNode.textContent = text;
  }

  function selectedResidues() {
    var residues = new Map();
    if (!viewer || !viewer.plugin || !viewer.plugin.managers.structure) return [];
    // The viewer bundle only exposes the library under window.molstar.lib.
    var lib = window.molstar.lib;
    var selection = viewer.plugin.managers.structure.selection;
    var structures = viewer.plugin.managers.structure.hierarchy.current.structures;
    var StructureElement = lib.structure.StructureElement;
    var StructureProperties = lib.structure.StructureProperties;
    if (!selection || !structures || !StructureElement || !StructureProperties) return [];
    // Canvas picks, sequence-panel clicks, and structureInteractivity all
    // funnel into structure.selection (lociSelects.sel IS this manager).
    structures.forEach(function (structureRef) {
      var structure = structureRef && structureRef.cell && structureRef.cell.obj && structureRef.cell.obj.data;
      if (!structure) return;
      var loci = selection.getLoci(structure);
      if (!loci || !loci.elements) return;
      StructureElement.Loci.forEachLocation(loci, function (location) {
        if (!location.unit || location.unit.kind !== 0) return;  // kind 0 = atomic units only
        var chain = String(StructureProperties.chain.auth_asym_id(location) || StructureProperties.chain.label_asym_id(location) || "_");
        var auth = Number(StructureProperties.residue.auth_seq_id(location));
        var label = Number(StructureProperties.residue.label_seq_id(location));
        residues.set(chain + ":" + auth + ":" + label, { chain: chain, auth_seq_id: auth, label_seq_id: label, residue: auth });
      });
    });
    return Array.from(residues.values());
  }

  function reportSelection() {
    try {
      report({ type: "selection", requestId: activeRequestId, residues: selectedResidues() });
    } catch (error) {
      report({ type: "selection-error", requestId: activeRequestId, message: error.message || String(error) });
    }
  }

  function bindSelectionEvents(enabled) {
    if (selectionSubscription) selectionSubscription.unsubscribe();
    selectionSubscription = null;
    if (!enabled || !viewer || !viewer.plugin || !viewer.plugin.managers.structure) return;
    var selection = viewer.plugin.managers.structure.selection;
    if (!selection || !selection.events || !selection.events.changed) return;
    selectionSubscription = selection.events.changed.subscribe(function () {
      setTimeout(reportSelection, 0);
    });
  }

  function selectResidue(message) {
    if (!viewer || typeof viewer.structureInteractivity !== "function") return;
    var elements = {};
    var prefix = message.numbering === "auth_seq_id" ? "auth" : "label";
    elements["beg_" + prefix + "_seq_id"] = Number(message.residue);
    elements["end_" + prefix + "_seq_id"] = Number(message.residue);
    if (message.chain) elements[prefix + "_asym_id"] = String(message.chain);
    viewer.plugin.managers.interactivity.lociSelects.deselectAll();
    viewer.structureInteractivity({ elements: elements, action: "select" });
  }

  // Surface any boot error in the shell UI instead of leaving the
  // "Waiting for structure data…" placeholder frozen forever.
  window.addEventListener("error", function (event) {
    stateNode.hidden = false;
    stateNode.dataset.state = "error";
    stateNode.textContent = "Shell error: " + (event.message || "unknown error");
  });

  function parentOrigin() {
    try { return window.parent.origin; } catch (e) { return "*"; }
  }

  function report(payload) {
    // The sandboxed frame has an opaque origin ("null") — target the
    // parent's real origin, never location.origin.
    window.parent.postMessage(payload, parentOrigin());
  }

  function fail(message) {
    stateNode.hidden = false;
    stateNode.dataset.state = "error";
    host.hidden = true;
    stateNode.textContent = "Mol* could not be loaded: " + message;
  }

  function ensureMolstarStyle() {
    if (document.querySelector("link[data-molstar-style]")) return;
    var style = document.createElement("link");
    style.rel = "stylesheet";
    style.href = MOLSTAR_BASE + "molstar.css";
    style.integrity = MOLSTAR_STYLE_INTEGRITY;
    style.crossOrigin = "anonymous";
    style.dataset.molstarStyle = MOLSTAR_VERSION;
    document.head.appendChild(style);
  }

  function applyTheme(theme) {
    var resolved = theme === "dark" ? "dark" : "light";
    activeTheme = resolved;
    document.documentElement.dataset.theme = resolved;
    ensureMolstarStyle();
    var darkStyle = document.querySelector("link[data-molstar-dark-style]");
    if (resolved === "dark" && !darkStyle) {
      darkStyle = document.createElement("link");
      darkStyle.rel = "stylesheet";
      darkStyle.href = MOLSTAR_BASE + "theme/dark.css";
      darkStyle.integrity = MOLSTAR_DARK_STYLE_INTEGRITY;
      darkStyle.crossOrigin = "anonymous";
      darkStyle.dataset.molstarDarkStyle = MOLSTAR_VERSION;
      document.head.appendChild(darkStyle);
    } else if (resolved === "light" && darkStyle) {
      darkStyle.remove();
    }
    if (viewer && viewer.plugin.canvas3d) {
      viewer.plugin.canvas3d.setProps({ renderer: { backgroundColor: MOLSTAR_CANVAS_COLORS[resolved] } });
    }
  }

  function ensureMolstarAssets() {
    if (window.molstar && window.molstar.Viewer) return Promise.resolve(window.molstar);
    if (assetsPromise) return assetsPromise;
    assetsPromise = new Promise(function (resolve, reject) {
      ensureMolstarStyle();
      // Mol* is a ~5 MB bundle: poll for the global (deferred init) for up
      // to 15 s and retry the fetch once before giving up.
      var settled = false;

      function waitForGlobal(start) {
        if (settled) return;
        if (window.molstar && window.molstar.Viewer) { settled = true; resolve(window.molstar); return; }
        if (Date.now() - start > 15000) { settled = true; reject(new Error("Mol* did not initialize")); return; }
        setTimeout(function () { waitForGlobal(start); }, 500);
      }

      var attempts = 0;
      function loadScript() {
        attempts += 1;
        var script = document.createElement("script");
        script.src = MOLSTAR_BASE + "molstar.js";
        script.integrity = MOLSTAR_SCRIPT_INTEGRITY;
        script.crossOrigin = "anonymous";
        script.dataset.molstarScript = MOLSTAR_VERSION;
        script.addEventListener("load", function () { waitForGlobal(Date.now()); }, { once: true });
        script.addEventListener("error", function () {
          if (attempts < 2) { loadScript(); return; }
          settled = true;
          reject(new Error("Mol* could not be loaded"));
        }, { once: true });
        document.head.appendChild(script);
      }
      loadScript();
    }).catch(function (error) { assetsPromise = null; throw error; });
    return assetsPromise;
  }

  // Serialize mounts: a warm shell receiving structure N+1 while N is still
  // loading must not interleave plugin.clear()/load calls on the shared
  // viewer. mountStructure never rejects (errors report per requestId), so
  // the chain stays unbroken.
  var mountChain = Promise.resolve();
  function queueMount(message) {
    mountChain = mountChain.then(function () { return mountStructure(message); });
  }

  async function mountStructure(message) {
    activeRequestId = message.requestId;
    applyTheme(message.theme);
    // Warm remounts keep the current structure visible while the next one
    // loads — showing the loading state on every swap flashes for the
    // short (cached/warm) awaits and reads as a refresh.
    if (!viewer) {
      stateNode.hidden = false;
      host.hidden = true;
      setLoadingPhase("Downloading the Mol* viewer…");
    }
    try {
      await prepareViewer(message);
      // Sequence-strip and canvas clicks select only while Mol* selection mode
      // is active. Input workbenches request selection explicitly; result
      // viewers retain Mol*'s ordinary focus-oriented default.
      viewer.plugin.selectionMode = Boolean(message.selectionEnabled);
      var format = message.format === "mmcif" ? "mmcif" : "pdb";
      await viewer.loadStructureFromData(message.text, format, { label: message.label || "structure" });
      // A new structure arrives with Mol*'s own default representation, so the
      // requested presentation is applied after the load and after the ready
      // report. Presenting is not loading: a representation this structure does
      // not support must never turn a successful load into a reported failure.
      presentation.representation = message.preset && MOLSTAR_PRESETS[message.preset]
        ? message.preset
        : DEFAULT_PRESET;
      presentation.color = message.colorMode || DEFAULT_COLOR;
      presentation.applied = null;
      presentation.dirty = true;
      bindSelectionEvents(Boolean(message.selectionEnabled));
      stateNode.hidden = true;
      host.hidden = false;
      report({ type: "ready", requestId: message.requestId });
      queuePresentation(applyRepresentationState);
    } catch (error) {
      fail(error.message || String(error));
      report({ type: "error", requestId: message.requestId, message: error.message || String(error) });
    }
  }

  // Presentation state. Mol* resets a representation's color theme to
  // `element-symbol` whenever the representation layer is replaced, so the
  // color has to be re-applied after a swap. That means the shell must
  // remember which color is current, rather than relying on Mol* to keep it.
  // `applied` is the representation Mol* is actually showing right now, which
  // is not the same as the one the user asked for: a load resets it to Mol*'s
  // default and a failed swap leaves the previous one in place.
  var presentation = { representation: null, color: null, applied: null, dirty: false };

  function hierarchy() { return viewer.plugin.managers.structure.hierarchy; }

  // Add one representation by its Mol* registry name through the builders
  // API. `managers.structure.component.addRepresentation(components, {type})`
  // accepts the call and silently does nothing; only the builder path, handed
  // the component's own cell, actually adds the representation.
  async function addRepresentationByName(name) {
    var plugin = viewer.plugin;
    var builders = plugin.builders.structure.representation;
    // Resolve the provider before touching the representation tree: removing
    // first would leave the component blank when the name is unknown, which is
    // a visible outcome for a call that only ever meant to be a no-op.
    var provider = plugin.representation.structure.registry.get(name);
    if (!provider) throw new Error("Unknown structure representation: " + name);
    var components = [].concat.apply([], hierarchy().currentComponentGroups);
    await plugin.dataTransaction(async function () {
      try { await plugin.managers.structure.component.removeRepresentations(components); } catch (e) { /* nothing to remove */ }
      var fresh = [].concat.apply([], hierarchy().currentComponentGroups);
      // Removing representations drops the component group itself, so the
      // fresh list is re-read inside the transaction and each surviving
      // component is added by its own cell.
      for (var index = 0; index < fresh.length; index += 1) {
        await builders.addRepresentation(fresh[index].cell, { type: provider });
      }
    }, { canUndo: "Structure preset" });
  }

  // `cartoon_ligand` is the one curated composition (polymer cartoon + ligand
  // ball-and-stick + carbohydrate symbols), so it goes through the component
  // manager's own preset path with a resolved provider. The theme is passed
  // explicitly because the preset would otherwise pick its own.
  async function applyComposedPreset(name) {
    var plugin = viewer.plugin;
    var structures = hierarchy().current.structures;
    if (!structures || !structures.length) return;
    var provider = plugin.builders.structure.representation.resolveProvider(name);
    if (!provider) throw new Error("Unknown structure preset: " + name);
    await plugin.managers.structure.component.applyPreset(structures, provider, {
      theme: { globalName: MOLSTAR_COLORS[presentation.color] || presentation.color }
    });
  }

  async function reapplyColor(mode) {
    var resolved = mode || presentation.color || DEFAULT_COLOR;
    var components = [].concat.apply([], hierarchy().currentComponentGroups);
    if (!components.length) return;
    await viewer.plugin.managers.structure.component.updateRepresentationsTheme(components, {
      color: MOLSTAR_COLORS[resolved] || resolved
    });
  }

  // One serialized entry point for both presentation axes. Serializing is what
  // makes each application atomic: a color change that arrives while a preset
  // swap is mid-transaction waits for it rather than interleaving with it.
  var presentationChain = Promise.resolve();
  function queuePresentation(work) {
    presentationChain = presentationChain.then(work).catch(function () {
      // Presentation is never data: a representation the structure does not
      // support leaves the current one in place and the viewer usable.
    });
  }

  async function applyRepresentationState() {
    if (!viewer || !viewer.plugin) return;
    var target = MOLSTAR_PRESETS[presentation.representation] || MOLSTAR_PRESETS[DEFAULT_PRESET];
    // A fresh load already carries Mol*'s default representation, and the
    // composition preset is requested as the load's own preset — either way
    // there is nothing to swap, and a redundant swap would only reset the
    // color.
    if (presentation.applied === presentation.representation) {
      await reapplyColor();
      presentation.dirty = false;
      return;
    }
    if (presentation.representation === DEFAULT_PRESET) {
      // A fresh load already carries Mol*'s default representation; swapping
      // it for the identical one would only reset the color.
      await reapplyColor();
      presentation.applied = presentation.representation;
      presentation.dirty = false;
      return;
    }
    if (MOLSTAR_COMPOSED_PRESETS[presentation.representation]) {
      await applyComposedPreset(target);
    } else {
      await addRepresentationByName(target);
    }
    await reapplyColor();
    presentation.applied = presentation.representation;
    presentation.dirty = false;
  }

  function setStructurePreset(name) {
    if (!MOLSTAR_PRESETS[name]) return;
    presentation.representation = name;
    queuePresentation(applyRepresentationState);
  }

  async function updateStructureColor(mode) {
    presentation.color = mode || DEFAULT_COLOR;
    // A color change needs a live representation to restyle, so wait for the
    // current mount to finish and for any queued swap ahead of it. Applying
    // the requested mode directly (not the coalesced state) keeps each
    // distinct request observable while still landing on the latest one.
    var requested = presentation.color;
    queuePresentation(function () {
      if (!viewer || !viewer.plugin) return Promise.resolve();
      if (presentation.dirty) return applyRepresentationState();
      return reapplyColor(requested);
    });
  }

  function trajectoryInfo() {
    if (!viewer) return null;
    var state = viewer.plugin.state.data;
    var transform = window.molstar.lib.plugin.StateTransforms.Model.ModelFromTrajectory;
    var models = state.selectQ(function (query) { return query.ofTransformer(transform); });
    if (!models.length) return null;
    var model = models[0];
    var trajectory = state.cells.get(model.transform.parent);
    return {
      model: model,
      frame: Number(model.params.values.modelIndex || 0),
      frameCount: Number(trajectory && trajectory.obj && trajectory.obj.data.frameCount || 1)
    };
  }

  async function setTrajectoryFrame(action, value) {
    var info = trajectoryInfo();
    if (!info) return;
    var frame = action === "set" ? Number(value) : info.frame + Number(value || 0);
    frame = ((Math.round(frame) % info.frameCount) + info.frameCount) % info.frameCount;
    var update = viewer.plugin.state.data.build();
    update.to(info.model).update({ modelIndex: frame });
    await viewer.plugin.state.data.updateTree(update).run();
    report({ type: "trajectory-frame", requestId: activeRequestId, frame: frame, frameCount: info.frameCount });
  }

  async function mountTrajectory(message) {
    activeRequestId = message.requestId;
    applyTheme(message.theme);
    if (!viewer) { stateNode.hidden = false; host.hidden = true; setLoadingPhase("Downloading the Mol* viewer…"); }
    try {
      await prepareViewer(message);
      if (message.coordinateFormat === "pdb") {
        await viewer.loadStructureFromData(message.coordinates, "pdb", { dataLabel: message.label || "trajectory" });
      } else {
        await viewer.loadTrajectory({
          model: { kind: "model-data", data: message.topology, format: "pdb" },
          modelLabel: "Declared topology",
          coordinates: {
            kind: "coordinates-data",
            data: message.coordinateBytes,
            format: message.coordinateFormat
          },
          coordinatesLabel: message.label || "coordinates",
          preset: "default"
        });
      }
      var info = trajectoryInfo();
      if (!info) throw new Error("Mol* did not create a trajectory");
      stateNode.hidden = true; host.hidden = false;
      report({ type: "trajectory-ready", requestId: message.requestId, frame: info.frame, frameCount: info.frameCount });
    } catch (error) {
      fail(error.message || String(error));
      report({ type: "error", requestId: message.requestId, message: error.message || String(error) });
    }
  }

  window.addEventListener("message", function (event) {
    if (event.source !== window.parent) return;
    if (!event.data || typeof event.data !== "object") return;
    if (event.data.type === "structure") queueMount(event.data);
    else if (event.data.type === "trajectory") mountChain = mountChain.then(function () { return mountTrajectory(event.data); });
    else if (event.data.type === "trajectory-control") {
      mountChain = mountChain.then(function () { return setTrajectoryFrame(event.data.action, event.data.value); }).catch(function (error) { fail(error.message || String(error)); });
    }
    else if (event.data.type === "theme") applyTheme(event.data.theme);
    else if (event.data.type === "preset") setStructurePreset(event.data.preset);
    else if (event.data.type === "color") updateStructureColor(event.data.mode);
    else if (event.data.type === "select-residue") selectResidue(event.data);
    else if (event.data.type === "dispose") {
      if (selectionSubscription) selectionSubscription.unsubscribe();
      selectionSubscription = null;
      if (viewer) viewer.plugin.dispose();
      viewer = null;
      host.replaceChildren();
      // Acknowledge teardown so the parent can remove the iframe only after
      // this shell's resources (subscriptions, plugin, WebGL context) are gone.
      report({ type: "disposed" });
    }
  });

  report({ type: "shell-ready" });
})();
