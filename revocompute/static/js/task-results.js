/* REvoCompute — dedicated manifest-first task result workspace */
/* SPDX-License-Identifier: GPL-3.0-only */

(function () {
  "use strict";
  var A = window.REvoDesignAuth;
  var T = window.REvoDesignTheme;
  var task = JSON.parse(document.getElementById("result-task-data").textContent);
  var artifacts = [];
  var previewRegistry = null;
  var previewHost = null;
  var resultViews = [];
  var activeStoryboard = null;
  // Warm Mol* viewer: one shell iframe and plugin instance stay alive within
  // the active preview surface. Changing views disposes it with that surface.
  var warmMolstar = null;
  var structureHolder = null;
  var warmPending = {};
  var warmListenerInstalled = false;

  // One presentation vocabulary for both backends. Represented presets keep
  // the current color mode and only replace the representation layer; color
  // presets leave the representation alone and restyle it. py2Dmol draws an
  // alpha-carbon trace, so it honestly supports only the color axis — the
  // representation presets are disabled there rather than silently doing
  // nothing.
  var STRUCTURE_PRESETS = [
    { id: "cartoon", label: "Cartoon", colorMode: null, backends: ["molstar"] },
    { id: "cartoon_ligand", label: "Cartoon + ligand", colorMode: null, backends: ["molstar"] },
    { id: "sticks", label: "Sticks", colorMode: null, backends: ["molstar"] },
    { id: "surface_ligand", label: "Surface", colorMode: null, backends: ["molstar"] },
    { id: "chain", label: "Chain", colorMode: "chain", backends: ["molstar", "py2dmol"] },
    { id: "rainbow", label: "Rainbow", colorMode: "rainbow", backends: ["molstar", "py2dmol"] },
    { id: "confidence", label: "Confidence", colorMode: "confidence", requiresConfidence: true, backends: ["molstar", "py2dmol"] }
  ];
  var DEFAULT_PRESET = "cartoon";
  var DEFAULT_COLOR_MODE = "chain";
  // Presentation selection persists across artifact switches so the viewer
  // never resets to the default when the user moves between structures.
  var activePreset = DEFAULT_PRESET;
  // The color axis is tracked separately from the representation axis, so a
  // representation preset keeps whatever color mode is currently active.
  var activeColorMode = DEFAULT_COLOR_MODE;
  // The frame currently holding a mounted Mol* plugin, if any.
  var activeMolstar = null;

  function presetIsAvailable(preset, artifact) {
    if (preset.backends.indexOf(structureViewer) === -1) return false;
    if (!preset.requiresConfidence) return true;
    // A .cif is not evidence that the B-factor column holds pLDDT: only the
    // Runner's explicit result metadata may offer confidence coloring.
    return Boolean(artifact && artifact.confidence_encoding === "plddt_bfactor");
  }

  function applyPresetSelection(presetId, artifact) {
    var preset = STRUCTURE_PRESETS.find(function (item) { return item.id === presetId; });
    if (!preset || !presetIsAvailable(preset, artifact)) {
      preset = STRUCTURE_PRESETS.filter(function (item) { return presetIsAvailable(item, artifact); })[0];
    }
    return preset || STRUCTURE_PRESETS[0];
  }

  // Downloaded structure texts, held as promises so concurrent requests for
  // the same identity share one fetch. Bounded: at most 3 files and 60 MB,
  // least-recently-used evicted first. `pendingStructures` tracks which of
  // those promises have not settled yet, so a prefetch in flight still counts
  // as progress worth showing.
  var structureTextCache = new Map();
  var pendingStructures = new Set();
  var structureTextCacheBytes = 0;
  var STRUCTURE_CACHE_MAX_FILES = 3;
  var STRUCTURE_CACHE_MAX_BYTES = 60 * 1024 * 1024;
  var MOLSTAR_THEME_COOKIE = "revodesign-molstar-theme";
  // Mol* runs inside the isolated /compute/viewer-shell iframe (its bundle
  // needs new Function, which only that shell's CSP permits). All constants
  // and the asset loader live in viewer-shell.js.

  function formatBytes(value) {
    var bytes = Number(value || 0);
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KiB";
    if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + " MiB";
    return (bytes / (1024 * 1024 * 1024)).toFixed(2) + " GiB";
  }

  function showToast(message, type) {
    var node = document.createElement("div");
    node.className = "toast " + (type || "info");
    node.setAttribute("role", type === "error" ? "alert" : "status");
    node.textContent = message;
    document.getElementById("toastWrap").appendChild(node);
    setTimeout(function () { node.remove(); }, 3600);
  }

  // The shell iframe is sandboxed without allow-same-origin, so its origin
  // is opaque ("null") — postMessages must target the frame's own serialized
  // origin, never the parent's.
  function postToShell(frame, payload, transfer) {
    var targetOrigin = "*";
    try { targetOrigin = frame.contentWindow.origin || "*"; } catch (e) { /* frame gone */ }
    frame.contentWindow.postMessage(payload, targetOrigin, transfer || []);
  }

  function readMolstarTheme() {
    var prefix = MOLSTAR_THEME_COOKIE + "=";
    var value = document.cookie.split(";").map(function (part) { return part.trim(); }).find(function (part) {
      return part.startsWith(prefix);
    });
    return value && value.slice(prefix.length) === "dark" ? "dark" : "light";
  }

  function setMolstarTheme(theme) {
    var resolved = theme === "dark" ? "dark" : "light";
    var secure = location.protocol === "https:" ? "; Secure" : "";
    document.cookie = MOLSTAR_THEME_COOKIE + "=" + resolved + "; Path=/; Max-Age=31536000; SameSite=Lax" + secure;
    var frame = activeMolstar ? activeMolstar.frame : document.querySelector("iframe.artifact-molstar-preview");
    if (frame) postToShell(frame, { type: "theme", theme: resolved });
    document.querySelectorAll(".molstar-theme-toggle").forEach(function (button) {
      button.textContent = resolved === "dark" ? "☾" : "☀";
      button.setAttribute("aria-label", resolved === "dark" ? "Use light Mol* theme" : "Use dark Mol* theme");
      button.title = button.getAttribute("aria-label");
      button.setAttribute("aria-pressed", resolved === "dark" ? "true" : "false");
    });
  }

  function disposeActiveViewer(immediate) {
    var frame = warmMolstar ? warmMolstar.frame : null;
    warmMolstar = null;
    if (activeMolstar) activeMolstar = null;
    Object.keys(warmPending).forEach(function (key) {
      var pending = warmPending[key];
      clearTimeout(pending.timer);
      if (pending.reject) { try { pending.reject(new Error("Viewer disposed")); } catch (e) { /* already settled */ } }
      delete warmPending[key];
    });
    if (!frame) return Promise.resolve();
    if (immediate) {
      try { postToShell(frame, { type: "dispose" }); } catch (e) { /* frame is already unavailable */ }
      frame.remove();
      return Promise.resolve();
    }
    // Give the shell a moment to run its own teardown (selection unsubscribe
    // + plugin.dispose) before the iframe is detached; the shell acknowledges
    // with a "disposed" message, and a 2s timeout guarantees the frame never
    // lingers when the shell is already gone.
    return new Promise(function (resolve) {
      var removed = false;
      var timer = null;
      var removeFrame = function () {
        if (removed) return;
        removed = true;
        clearTimeout(timer);
        window.removeEventListener("message", onDisposed);
        frame.remove();
        resolve();
      };
      var onDisposed = function (event) {
        if (removed || event.source !== frame.contentWindow || !event.data || event.data.type !== "disposed") return;
        removeFrame();
      };
      timer = setTimeout(removeFrame, 2000);
      window.addEventListener("message", onDisposed);
      try { postToShell(frame, { type: "dispose" }); } catch (e) { removeFrame(); }
    });
  }

  // One shared message listener for the warm shell: resolves the pending
  // handshake for the given requestId, and flushes the first structure
  // message when the shell reports ready.
  function installWarmListener() {
    if (warmListenerInstalled) return;
    warmListenerInstalled = true;
    window.addEventListener("message", function (event) {
      if (!warmMolstar || event.source !== warmMolstar.frame.contentWindow || !event.data) return;
      if (event.data.type === "shell-ready") {
        var ready = warmPending["__shell_ready__"];
        if (ready) { delete warmPending["__shell_ready__"]; clearTimeout(ready.timer); ready.resolve(); }
        return;
      }
      var pending = warmPending[event.data.requestId];
      if (!pending) return;
      delete warmPending[event.data.requestId];
      clearTimeout(pending.timer);
      if (event.data.type === "ready") pending.resolve(warmMolstar.frame);
      else if (event.data.type === "error") pending.reject(new Error(event.data.message));
    });
  }

  function structureFormat(path) {
    var lower = String(path).toLowerCase();
    return lower.endsWith(".cif") || lower.endsWith(".mmcif") ? "mmcif" : "pdb";
  }

  // Single-flight guard: every async render captures the host generation at
  // start and re-checks it after each await. A viewer toggle, artifact
  // switch, or destroy bumps the generation, so a stale Mol*/py2Dmol
  // continuation can never mount or load a file after its surface is gone —
  // the two viewers are never in flight for the same stage simultaneously.
  function isStale(generation) {
    return previewHost && previewHost.generation !== generation;
  }

  async function renderPy2DmolFallback(text, artifact, stage, generation, molstarError) {
    try {
      await window.REvoDesignPy2Dmol.renderAlphaTrace(
        stage,
        text,
        structureFormat(artifact.path),
        artifact.path,
        [Math.max(320, Math.min(stage.clientWidth - 220, 900)), 560],
        function () { return isStale(generation); },
        artifact.confidence_encoding
      );
      if (isStale(generation)) return;
    } catch (error) {
      if (isStale(generation)) return;
      throw molstarError;
    }
  }

  // ponytail: current viewer choice per artifact — kept simple (no global
  // preference store).  Resets when the user selects a different artifact.
  var structureViewer = "molstar";

  // Two independent presentation axes on one toolbar: the representation
  // preset (what the model is drawn as) and, for the color presets, the color
  // mode. Selecting a representation preset keeps the current color mode.
  function setStructurePreset(presetId) {
    var preset = STRUCTURE_PRESETS.find(function (item) { return item.id === presetId; });
    if (!preset) return;
    if (preset.colorMode) setStructureColor(preset.colorMode);
    else if (activeMolstar) {
      try { postToShell(activeMolstar.frame, { type: "preset", preset: preset.id }); } catch (e) { /* frame gone */ }
    }
    activePreset = preset.id;
    document.querySelectorAll(".preset-toggle").forEach(function (btn) {
      var active = btn.dataset.preset === activePreset;
      btn.classList.toggle("active", active);
      btn.setAttribute("aria-pressed", active ? "true" : "false");
    });
  }
  function setStructureColor(mode) {
    activeColorMode = mode;
    // `confidence` is the same Mol* theme as `plddt`, under the shared
    // user-facing vocabulary.
    var molstarMode = mode === "confidence" ? "plddt" : mode;
    if (activeMolstar) {
      try { postToShell(activeMolstar.frame, { type: "color", mode: molstarMode }); } catch (e) { /* frame gone */ }
    }
    // py2Dmol backend — drive the existing color select in its right panel
    var colorSelect = document.querySelector(".py2dmol-fallback #colorSelect");
    if (colorSelect) {
      colorSelect.value = molstarMode;
      colorSelect.dispatchEvent(new Event("change", { bubbles: true }));
    }
    var preset = STRUCTURE_PRESETS.find(function (item) { return item.colorMode === mode; });
    if (preset) activePreset = preset.id;
    document.querySelectorAll(".preset-toggle").forEach(function (btn) {
      var active = btn.dataset.preset === activePreset;
      btn.classList.toggle("active", active);
      btn.setAttribute("aria-pressed", active ? "true" : "false");
    });
  }

  function structureViewerBar(artifact, rerender) {
    var bar = document.createElement("div");
    bar.className = "structure-viewer-bar";
    bar.setAttribute("role", "toolbar");
    bar.setAttribute("aria-label", "Structure viewer controls");
    var makeBtn = function (label, viewer) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "viewer-toggle" + (structureViewer === viewer ? " active" : "");
      btn.textContent = label;
      btn.setAttribute("aria-pressed", structureViewer === viewer ? "true" : "false");
      btn.addEventListener("click", function () { structureViewer = viewer; (rerender || previewArtifact)(artifact); });
      return btn;
    };
    bar.append(makeBtn("Mol* (full)", "molstar"), makeBtn("py2Dmol (alpha)", "py2dmol"));
    var preset = applyPresetSelection(activePreset, artifact);
    activePreset = preset.id;
    var presetBar = document.createElement("div");
    presetBar.className = "structure-preset-bar";
    presetBar.setAttribute("role", "group");
    presetBar.setAttribute("aria-label", "Structure style preset");
    STRUCTURE_PRESETS.filter(function (item) { return presetIsAvailable(item, artifact); }).forEach(function (item) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "preset-toggle";
      btn.textContent = item.label;
      btn.dataset.preset = item.id;
      if (activePreset === item.id) btn.classList.add("active");
      btn.setAttribute("aria-pressed", activePreset === item.id ? "true" : "false");
      btn.addEventListener("click", function () { setStructurePreset(item.id); });
      presetBar.appendChild(btn);
    });
    bar.appendChild(presetBar);
    var themeButton = document.createElement("button");
    themeButton.type = "button";
    themeButton.className = "molstar-theme-toggle";
    themeButton.addEventListener("click", function () {
      setMolstarTheme(readMolstarTheme() === "dark" ? "light" : "dark");
    });
    bar.appendChild(themeButton);
    setTimeout(function () { setMolstarTheme(readMolstarTheme()); }, 0);
    return bar;
  }

  function viewerAbortError() {
    var error = new Error("Viewer render cancelled");
    error.name = "AbortError";
    return error;
  }

  async function renderMolstar(structureText, artifact, stage, generation, fresh, signal) {
    if (signal && signal.aborted) throw viewerAbortError();
    var requestId = "mol-" + Math.random().toString(36).slice(2);
    var message = {
      type: "structure",
      text: structureText,
      format: structureFormat(artifact.path),
      label: artifact.path,
      requestId: requestId,
      theme: readMolstarTheme(),
      preset: activePreset,
      colorMode: activeColorMode
    };
    if (!fresh && warmMolstar) {
      // Warm path: the shell is already booted; post the new structure and
      // await the ready report for this requestId. No iframe work at all.
      await new Promise(function (resolve, reject) {
        var settled = false;
        var removeAbort = function () {};
        function finish(error, frame) {
          if (settled) return;
          settled = true;
          clearTimeout(timer);
          delete warmPending[requestId];
          removeAbort();
          if (error) reject(error); else resolve(frame);
        }
        var timer = setTimeout(function () { finish(new Error("Mol* timed out")); }, 45000);
        warmPending[requestId] = {
          resolve: function (frame) { finish(null, frame); }, reject: finish, timer: timer
        };
        if (signal) {
          var onAbort = function () { finish(viewerAbortError()); disposeActiveViewer(); };
          signal.addEventListener("abort", onAbort, { once: true });
          removeAbort = function () { signal.removeEventListener("abort", onAbort); };
        }
        try { postToShell(warmMolstar.frame, message); } catch (error) { finish(error); }
      });
      if (isStale(generation)) return warmMolstar.frame;
      activeMolstar = warmMolstar;
      return warmMolstar.frame;
    }
    if (fresh) {
      // Cold path for the linked table/structure view: a dedicated frame in
      // the caller's stage with its own one-shot handshake.
      var frame = document.createElement("iframe");
      frame.className = "artifact-molstar-preview";
      frame.sandbox = "allow-scripts";
      frame.title = "Mol* structure viewer";
      var handshake = new Promise(function (resolve, reject) {
        var settled = false;
        function finish(error) {
          if (settled) return;
          settled = true;
          clearTimeout(timer);
          window.removeEventListener("message", onMessage);
          if (signal) signal.removeEventListener("abort", onAbort);
          if (error) reject(error); else resolve(frame);
        }
        var timer = setTimeout(function () { finish(new Error("Mol* timed out")); }, 45000);
        function onAbort() { frame.remove(); finish(viewerAbortError()); }
        function onMessage(event) {
          if ((event.origin !== location.origin && event.origin !== "null") || event.source !== frame.contentWindow || !event.data) return;
          if (event.data.type === "shell-ready") postToShell(frame, message);
          else if (event.data.type === "ready" && event.data.requestId === requestId) {
            finish();
          } else if (event.data.type === "error" && event.data.requestId === requestId) {
            finish(new Error(event.data.message));
          }
        }
        window.addEventListener("message", onMessage);
        if (signal) signal.addEventListener("abort", onAbort, { once: true });
      });
      stage.appendChild(frame);
      frame.src = "/compute/viewer-shell";
      if (isStale(generation)) { frame.remove(); return; }
      await handshake;
      if (isStale(generation)) { frame.remove(); return; }
      return frame;
    }
    // First warm mount: one frame in the persistent holder, never reparented.
    var warmFrame = document.createElement("iframe");
    warmFrame.className = "artifact-molstar-preview";
    warmFrame.sandbox = "allow-scripts";
    warmFrame.title = "Mol* structure viewer";
    warmMolstar = { frame: warmFrame };
    installWarmListener();
    structureHolder.appendChild(warmFrame);
    warmFrame.src = "/compute/viewer-shell";
    await new Promise(function (resolve, reject) {
      var settled = false;
      var removeAbort = function () {};
      function finish(error, frame) {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        delete warmPending["__shell_ready__"];
        delete warmPending[requestId];
        removeAbort();
        if (error) reject(error); else resolve(frame);
      }
      var timer = setTimeout(function () { finish(new Error("Mol* timed out")); }, 45000);
      warmPending["__shell_ready__"] = {
        resolve: function () {
          try { postToShell(warmFrame, message); } catch (error) { finish(error); return; }
          timer = setTimeout(function () { finish(new Error("Mol* timed out")); }, 45000);
          warmPending[requestId] = {
            resolve: function (frame) { finish(null, frame); }, reject: finish, timer: timer
          };
        },
        reject: finish,
        timer: timer
      };
      if (signal) {
        var onAbort = function () { finish(viewerAbortError()); disposeActiveViewer(); };
        signal.addEventListener("abort", onAbort, { once: true });
        removeAbort = function () { signal.removeEventListener("abort", onAbort); };
      }
    });
    if (isStale(generation)) return warmFrame;
    activeMolstar = warmMolstar;
    return warmFrame;
  }

  // The host clears its stage between renders and, when `preserve` returns an
  // element, keeps it in place at the bottom. The structure renderer owns that
  // element while it is preserved, so it must not be cleared here.
  // The warm Mol* iframe lives inside the holder and must survive surface
  // clears: clearing it detaches the frame, whose contentWindow then reads
  // null on the next postMessage ("Cannot read properties of null").
  function clearSurfacePreservingWarm(surface) {
    if (!warmMolstar || warmMolstar.frame.parentNode !== surface) {
      surface.replaceChildren();
      return;
    }
    Array.from(surface.children).forEach(function (child) {
      if (child !== warmMolstar.frame) child.remove();
    });
  }

  function showLoading(surface, label) {
    var box = document.createElement("div");
    box.className = "preview-loading";
    // Self-clearing, and only from the DOM: a structure switch may keep this
    // surface, so a stale spinner must never be able to outlive its load.
    box.timer = setTimeout(function () { box.remove(); }, 60000);
    box.setAttribute("role", "status");
    box.setAttribute("aria-live", "polite");
    var bars = document.createElement("div");
    bars.className = "preview-loading-bars";
    for (var index = 0; index < 3; index += 1) bars.appendChild(document.createElement("span"));
    var text = document.createElement("p");
    text.className = "preview-loading-label";
    text.textContent = label || "Loading preview…";
    box.append(bars, text);
    box.done = function () { clearTimeout(box.timer); box.remove(); };
    if (warmMolstar && warmMolstar.frame.parentNode === surface) surface.insertBefore(box, warmMolstar.frame);
    else surface.appendChild(box);
    return box;
  }

  // A cached entry is a promise, so two viewers asking for the same identity
  // share one download. Entries are evicted least-recently-used first, and an
  // entry still in flight is never treated as a cache hit for eviction.
  function structureCacheKey(artifact) {
    return task.md5 + ":" + artifact.path + ":" + String(artifact.sha256 || "");
  }

  function structureCacheEvict() {
    while (structureTextCache.size > STRUCTURE_CACHE_MAX_FILES || structureTextCacheBytes > STRUCTURE_CACHE_MAX_BYTES) {
      var oldest = null;
      structureTextCache.forEach(function (entry, key) {
        if (oldest === null) oldest = key;
      });
      if (oldest === null) return;
      var evicted = structureTextCache.get(oldest);
      structureTextCache.delete(oldest);
      structureTextCacheBytes -= Number(evicted.bytes || 0);
    }
  }

  function structureCacheGet(key) {
    if (!structureTextCache.has(key)) return null;
    var entry = structureTextCache.get(key);
    // Re-insert to mark most-recently-used.
    structureTextCache.delete(key);
    structureTextCache.set(key, entry);
    return entry;
  }

  async function structureText(artifact, generation, signal) {
    var key = structureCacheKey(artifact);
    var entry = structureCacheGet(key);
    if (entry) {
      var cachedText = await entry.promise;
      if (isStale(generation)) return null;
      return cachedText;
    }
    entry = { bytes: 0, promise: null };
    pendingStructures.add(key);
    entry.promise = (async function () {
      var response = await A.authFetch(artifact.url, signal ? { signal: signal } : undefined);
      if (!response.ok) throw new Error("Structure download failed (HTTP " + response.status + ")");
      var text = await response.text();
      entry.bytes = text.length;
      structureTextCacheBytes += entry.bytes;
      return text;
    })();
    // A failed download must not stay cached: drop it so the next pick retries.
    entry.promise.catch(function () {
      if (structureTextCache.get(key) === entry) {
        structureTextCache.delete(key);
        structureTextCacheBytes -= entry.bytes;
      }
    });
    // Settle the bookkeeping once, whichever way the fetch went, and evict only
    // then — an in-flight prefetch must never be dropped mid-download, and
    // `pendingStructures` must not leak an identity that has already resolved.
    entry.promise.then(
      function () { pendingStructures.delete(key); structureCacheEvict(); },
      function () { pendingStructures.delete(key); structureCacheEvict(); }
    );
    structureTextCache.set(key, entry);
    var text = await entry.promise;
    if (isStale(generation)) return null;
    return text;
  }

  // Prefetch the neighbouring structures so an adjacent pick resolves from
  // cache. Bounded to the declared neighbour list, never the whole result.
  function prefetchStructures(artifact, neighbours) {
    (neighbours || []).slice(0, 2).forEach(function (neighbour) {
      if (!neighbour || neighbour === artifact) return;
      if (structureTextCache.has(structureCacheKey(neighbour))) return;
      structureText(neighbour, previewHost.generation, null).catch(function () { /* best-effort */ });
    });
  }

  // The structures the user is most likely to pick next: the selected model's
  // immediate siblings in the declared result order.
  function structureNeighbours(artifact) {
    var structures = artifacts.filter(function (item) { return item.preview === "structure"; });
    var index = structures.indexOf(artifact);
    if (index < 0) return [];
    return [structures[index + 1], structures[index - 1]].filter(Boolean);
  }

  // The structure viewer owns the host stage and hands back the nodes that
  // must survive a structure-to-structure switch, so the booted Mol* iframe
  // is never detached and later switches only load new structure data.
  function preserveStructureStage(stage, plugin) {
    if (plugin.id !== "structure") {
      // Any other result replaces the viewer entirely: a booted WebGL context
      // left behind would keep rendering under the new surface.
      disposeActiveViewer(true);
      return [];
    }
    return Array.prototype.slice.call(stage.children).filter(function (child) {
      return child === warmMolstar?.frame || /structure-(viewer|preset)-bar/.test(child.className);
    });
  }

  // Visual identity for the shared banner over the viewer: changing it must
  // not restart anything, so it is a one-time DOM check.
  var bannerShown = false;
  function announceViewerOnce(message) {
    if (bannerShown || !previewHost) return;
    bannerShown = true;
    var note = document.createElement("p");
    note.className = "preview-message py2dmol-note";
    note.textContent = message;
    previewHost.stage.appendChild(note);
  }

  async function previewStructure(artifact, stage, signal) {
    structureHolder = stage;
    var generation = previewHost.generation;
    // The structure viewer owns the host stage, so it renders directly into it
    // and keeps the booted Mol* iframe and toolbar alive across switches.
    var surface = stage;

    if (structureViewer === "py2dmol") {
      disposeActiveViewer(true);
      surface.replaceChildren();
      var text0 = await structureText(artifact, generation, signal);
      if (!text0 || isStale(generation)) return;
      surface.appendChild(structureViewerBar(artifact));
      try {
        await renderPy2DmolFallback(text0, artifact, surface, generation, new Error("User selected alpha-trace viewer"));
        if (isStale(generation)) return;
        announceViewerOnce("Mol* was unavailable; showing the interactive py2Dmol alpha-trace fallback.");
        setTimeout(function () { if (!isStale(generation)) setStructureColor(activeColorMode); }, 100);
      } catch (e) {
        if (isStale(generation)) return;
        var unavailable = document.createElement("p");
        unavailable.className = "preview-message";
        unavailable.textContent = "py2Dmol unavailable. Download the structure file to inspect it locally.";
        surface.appendChild(unavailable);
      }
      return;
    }

    var text = await structureText(artifact, generation, signal);
    if (!text || isStale(generation)) return;
    var carried = warmMolstar && warmMolstar.frame.parentNode === surface ? warmMolstar.frame : null;
    if (!carried) clearSurfacePreservingWarm(surface);
    // The toolbar is rebuilt for the new artifact (preset availability depends
    // on its declared confidence metadata) and replaces the preserved one; any
    // spinner left by the previous load is cleared with it.
    var stale = surface.querySelectorAll(".structure-viewer-bar, .preview-loading");
    Array.prototype.forEach.call(stale, function (node) { node.done ? node.done() : node.remove(); });
    var bar = structureViewerBar(artifact);
    if (carried) surface.insertBefore(bar, carried);
    else surface.appendChild(bar);

    // "Cached" means the text is already in hand, not that a fetch was started;
    // an in-flight prefetch still has to show progress.
    var loading = pendingStructures.has(structureCacheKey(artifact)) ? showLoading(surface, "Loading structure…") : null;
    try {
      await renderMolstar(text, artifact, surface, generation, false, signal);
      if (loading) loading.done();
      if (!isStale(generation)) prefetchStructures(artifact, structureNeighbours(artifact));
    } catch (error) {
      if (loading) loading.done();
      if (isStale(generation)) return;
      // The viewer is already known dead, so tear it down immediately rather
      // than waiting on a shell handshake that will not come: a fresh shell is
      // built on the next pick.
      disposeActiveViewer(true);
      surface.replaceChildren();
      surface.appendChild(structureViewerBar(artifact));
      var msg = document.createElement("p");
      msg.className = "preview-message";
      msg.textContent = "Mol* could not be loaded: " + (error.message || error);
      var br = document.createElement("br");
      var retry = document.createElement("button");
      retry.type = "button";
      retry.className = "btn btn-soft btn-small";
      retry.textContent = "Open with py2Dmol (alpha-trace)";
      retry.addEventListener("click", function () { structureViewer = "py2dmol"; previewArtifact(artifact); });
      msg.append(br, retry);
      surface.appendChild(msg);
      console.warn("Mol* error:", error);
    }
  }

  function renderTable(page, stage) {
    var rows = [page.columns].concat(page.rows || []);
    if (!page.columns || !page.columns.length) { stage.innerHTML = '<p class="preview-message">This table is empty.</p>'; return; }
    var wrap = document.createElement("div");
    wrap.className = "artifact-table-wrap";
    var table = document.createElement("table");
    table.className = "artifact-table-preview";
    rows.forEach(function (row, rowIndex) {
      var tr = document.createElement("tr");
      row.forEach(function (value) {
        var cell = document.createElement(rowIndex === 0 ? "th" : "td");
        cell.textContent = value;
        tr.appendChild(cell);
      });
      table.appendChild(tr);
    });
    wrap.appendChild(table);
    stage.appendChild(wrap);
  }

  async function previewImage(artifact, stage, services) {
    var response = await A.authFetch(artifact.url, { signal: services.signal });
    if (!response.ok) throw new Error("Image download failed");
    var objectUrl = URL.createObjectURL(await response.blob());
    var image = document.createElement("img");
    image.className = "artifact-image-preview";
    image.alt = artifact.path;
    image.src = objectUrl;
    image.addEventListener("load", function () { URL.revokeObjectURL(objectUrl); }, { once: true });
    image.addEventListener("error", function () { URL.revokeObjectURL(objectUrl); }, { once: true });
    stage.appendChild(image);
  }

  function isMsaFile(path) {
    var ext = String(path || "").toLowerCase();
    return /\.(a3m|aln|fa|faa|fasta|sto)$/.test(ext);
  }

  // Zappo/Clustal residue color scheme
  var RESIDUE_COLORS = {
    A: "#80a0f0", I: "#80a0f0", L: "#80a0f0", M: "#80a0f0", F: "#80a0f0", W: "#80a0f0", V: "#80a0f0", // hydrophobic
    K: "#f01505", R: "#f01505",                                                                         // positive
    D: "#c048c0", E: "#c048c0",                                                                         // negative
    N: "#15c015", Q: "#15c015", S: "#15c015", T: "#15c015",                                             // polar
    C: "#f08080",                                                                                       // cysteine
    G: "#f09048",                                                                                       // glycine
    P: "#c0c000",                                                                                       // proline
    H: "#15a4a4", Y: "#15a4a4",                                                                         // aromatic
    "-": "#c0c0c0", ".": "#c0c0c0"                                                                      // gap
  };

  function renderMsa(text, stage) {
    var wrapper = document.createElement("div");
    wrapper.className = "msa-viewer";
    var lines = String(text).split(/\r?\n/);
    var block = document.createElement("div");
    block.className = "msa-block";
    var lineCount = 0;
    lines.forEach(function (line) {
      if (lineCount >= 5000) return;
      var trimmed = line.trimEnd();
      if (trimmed.startsWith(">") || trimmed.startsWith("#")) {
        var headerSpan = document.createElement("span");
        headerSpan.className = "msa-header";
        headerSpan.textContent = trimmed;
        block.appendChild(headerSpan);
      } else if (trimmed) {
        var seqSpan = document.createElement("span");
        seqSpan.className = "msa-sequence";
        for (var i = 0; i < trimmed.length; i++) {
          var char = trimmed[i].toUpperCase();
          var span = document.createElement("span");
          span.textContent = trimmed[i];
          span.style.color = RESIDUE_COLORS[char] || "inherit";
          seqSpan.appendChild(span);
        }
        block.appendChild(seqSpan);
      } else {
        block.appendChild(document.createElement("br"));
      }
      lineCount += 1;
    });
    if (lines.length > 5000) block.appendChild(document.createTextNode("\n\n[Preview truncated at 5000 lines]"));
    wrapper.appendChild(block);
    stage.appendChild(wrapper);
  }

  async function previewText(artifact, stage, services) {
    var response = await A.authFetch(artifact.url, { headers: { Range: "bytes=0-262143" }, signal: services.signal });
    if (!response.ok && response.status !== 206) throw new Error("Text preview download failed");
    var text = await response.text();
    if (isMsaFile(artifact.path)) {
      renderMsa(text, stage);
      return;
    }
    var pre = document.createElement("pre");
    pre.textContent = text + (artifact.size > 262144 ? "\n\n[Preview truncated at 256 KiB]" : "");
    stage.appendChild(pre);
  }

  async function previewTable(artifact, stage, services) {
    var encoded = artifact.path.split("/").map(encodeURIComponent).join("/");
    var response = await A.authFetch("/compute/api/results/" + encodeURIComponent(task.md5) + "/tables/" + encoded + "?limit=100", { signal: services.signal });
    if (!response.ok) throw new Error("Table preview download failed");
    var page = await response.json();
    renderTable(page, stage);
    if (page.has_more) {
      var note = document.createElement("p");
      note.className = "preview-message";
      note.textContent = "Showing the first 100 rows. Download the file for the complete table.";
      stage.appendChild(note);
    }
  }

  function artifactFor(path) {
    return artifacts.find(function (artifact) { return artifact.path === path; }) || null;
  }

  function artifactPaths(view, source) {
    return (view.sources && Array.isArray(view.sources[source]) ? view.sources[source] : [])
      .map(artifactFor).filter(Boolean);
  }

  function exceedsPreviewLimit(artifact, plugin, stage) {
    if (!plugin || !plugin.maxBytes || Number(artifact.size || 0) <= plugin.maxBytes) return false;
    var message = document.createElement("p"); message.className = "preview-message";
    message.textContent = "This file exceeds the safe inline preview limit. Download it instead.";
    stage.appendChild(message); return true;
  }

  function valueAtPath(value, path) {
    String(path || "").split(".").filter(Boolean).forEach(function (part) {
      if (value == null || !(part in value)) throw new Error("The declared data field is unavailable.");
      value = value[part];
    });
    return value;
  }

  async function loadJson(artifact, signal) {
    if (Number(artifact.size || 0) > 8 * 1024 * 1024) throw new Error("This scientific data file exceeds the 8 MiB preview limit.");
    var response = await A.authFetch(artifact.url, { headers: { Range: "bytes=0-8388607" }, signal: signal });
    if (!response.ok && response.status !== 206) throw new Error("Scientific data could not be loaded.");
    return response.json();
  }

  async function loadCsv(artifact, signal, matrix) {
    var rows = [], columns = null, offset = 0;
    do {
      var url = tableUrl(artifact.path, offset).replace("limit=100", "limit=500") + (matrix ? "&matrix=1" : "");
      var response = await A.authFetch(url, { signal: signal });
      if (!response.ok) throw new Error("Scientific table could not be loaded.");
      var page = await response.json();
      if (!Array.isArray(page.rows)) throw new Error("Scientific table returned invalid rows.");
      columns = columns || page.columns;
      rows = rows.concat(page.rows);
      var previousOffset = offset;
      offset += page.rows.length;
      if (!page.has_more || !page.rows.length || offset === previousOffset) break;
    } while (rows.length < 10000);
    return { columns: columns || [], rows: rows, truncated: rows.length >= 10000 };
  }

  function directionLabel(direction) {
    return { higher: "Higher is favourable", lower: "Lower is favourable", neutral: "No ranking direction" }[direction] || "";
  }

  async function renderAlignment(view, stage, services) {
    var source = artifactPaths(view, "alignment")[0];
    if (!source) throw new Error("The configured alignment is unavailable.");
    var response = await A.authFetch(source.url, { headers: { Range: "bytes=0-262143" }, signal: services.signal });
    if (!response.ok && response.status !== 206) throw new Error("Alignment download failed.");
    var note = document.createElement("p"); note.className = "scientific-note";
    note.textContent = "Columns use " + view.mapping.numbering + " numbering. Preview is bounded to 256 KiB and 5,000 lines.";
    stage.appendChild(note); renderMsa(await response.text(), stage);
  }

  function scientificPicker(items, label, open) {
    var bar = document.createElement("div"); bar.className = "scientific-toolbar";
    var caption = document.createElement("label"); caption.textContent = label + " ";
    var select = document.createElement("select"); select.setAttribute("aria-label", label);
    items.forEach(function (artifact, index) {
      var option = document.createElement("option"); option.value = String(index); option.textContent = artifact.path; select.appendChild(option);
    });
    select.addEventListener("change", function () { open(items[Number(select.value)]).catch(showPreviewError); });
    caption.appendChild(select); bar.appendChild(caption); return bar;
  }

  async function renderMetricSeries(view, stage, services) {
    var sources = artifactPaths(view, "series");
    if (!sources.length) throw new Error("The configured metric series is unavailable.");
    var chart = document.createElement("div"); chart.className = "metric-chart";
    var generation = 0;
    async function open(artifact) {
      var current = ++generation, mapping = view.mapping, series = [], xValues = [];
      if (mapping.format === "json") {
        var values = valueAtPath(await loadJson(artifact, services.signal), mapping.value_path);
        series = [{ name: mapping.y_label || "Value", values: values.map(Number) }];
        xValues = values.map(function (_value, index) { return index + 1; });
      } else {
        var page = await loadCsv(artifact, services.signal);
        var indexes = {}; page.columns.forEach(function (column, index) { indexes[column] = index; });
        xValues = page.rows.map(function (row, index) {
          var value = Number(row[indexes[mapping.x_column]]); return Number.isFinite(value) ? value : index + 1;
        });
        series = mapping.value_columns.map(function (column) {
          return { name: column, values: page.rows.map(function (row) { return Number(row[indexes[column]]); }) };
        });
      }
      if (current !== generation || services.signal.aborted) return;
      var points = series.flatMap(function (item) { return item.values.filter(Number.isFinite); });
      if (!points.length) throw new Error("The metric series contains no numeric values.");
      var yMin = mapping.y_min == null ? Math.min.apply(null, points) : Number(mapping.y_min);
      var yMax = mapping.y_max == null ? Math.max.apply(null, points) : Number(mapping.y_max);
      if (yMin === yMax) yMax = yMin + 1;
      var width = 760, height = 360, pad = 48;
      var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      svg.setAttribute("viewBox", "0 0 " + width + " " + height); svg.setAttribute("role", "img");
      svg.setAttribute("aria-label", (mapping.y_label || "Metric") + " by " + (mapping.x_label || "index"));
      var colors = ["#087f8c", "#c44536", "#6a4c93", "#2f7d32", "#b26a00"];
      var xMin = Math.min.apply(null, xValues), xMax = Math.max.apply(null, xValues);
      series.forEach(function (item, seriesIndex) {
        var path = document.createElementNS(svg.namespaceURI, "path");
        var drawing = false;
        var commands = item.values.map(function (value, index) {
          if (!Number.isFinite(value)) { drawing = false; return null; }
          var xValue = Number(xValues[index]);
          var x = pad + (width - 2 * pad) * ((xValue - xMin) / Math.max(xMax - xMin, 1));
          var y = height - pad - (height - 2 * pad) * ((value - yMin) / (yMax - yMin));
          var command = drawing ? "L" : "M"; drawing = true;
          return command + x.toFixed(1) + " " + y.toFixed(1);
        }).filter(Boolean).join(" ");
        path.setAttribute("d", commands); path.setAttribute("fill", "none");
        path.setAttribute("stroke", colors[seriesIndex % colors.length]); path.setAttribute("stroke-width", "2"); svg.appendChild(path);
      });
      var summary = document.createElement("p"); summary.className = "scientific-note";
      summary.textContent = (mapping.x_label || "Index") + ": " + xValues.length + " points · " +
        (mapping.y_label || "Value") + ": " + yMin.toFixed(3) + "–" + yMax.toFixed(3) +
        (mapping.unit ? " " + mapping.unit : "") + " · " + directionLabel(mapping.direction);
      chart.replaceChildren(svg, summary);
    }
    if (sources.length > 1) stage.appendChild(scientificPicker(sources, "Metric source", open));
    stage.appendChild(chart); await open(sources[0]);
  }

  async function renderMatrix(view, stage, services) {
    var sources = artifactPaths(view, "matrices");
    if (!sources.length) throw new Error("The configured matrix is unavailable.");
    var region = document.createElement("div"); region.className = "matrix-view";
    var generation = 0;
    async function open(artifact) {
      var current = ++generation, mapping = view.mapping, values, xLabels, yLabels;
      if (mapping.format === "json") {
        values = valueAtPath(await loadJson(artifact, services.signal), mapping.value_path);
        xLabels = (values[0] || []).map(function (_value, index) { return String(index + 1); });
        yLabels = values.map(function (_value, index) { return String(index + 1); });
      } else {
        var page = await loadCsv(artifact, services.signal, true); var labelIndex = page.columns.indexOf(mapping.row_labels_column);
        xLabels = labelIndex < 0 ? page.columns : page.columns.filter(function (_column, index) { return index !== labelIndex; });
        yLabels = page.rows.map(function (row, index) { return labelIndex < 0 ? String(index + 1) : row[labelIndex]; });
        values = page.rows.map(function (row) { return (labelIndex < 0 ? row : row.filter(function (_value, index) { return index !== labelIndex; })).map(Number); });
      }
      if (current !== generation || services.signal.aborted) return;
      if (!Array.isArray(values) || !values.length || !Array.isArray(values[0])) throw new Error("The matrix is empty.");
      var numeric = values.flat().map(Number).filter(Number.isFinite);
      var minimum = mapping.scale_min == null ? Math.min.apply(null, numeric) : Number(mapping.scale_min);
      var maximum = mapping.scale_max == null ? Math.max.apply(null, numeric) : Number(mapping.scale_max);
      var center = mapping.center == null ? 0 : Number(mapping.center);
      var canvas = document.createElement("canvas"); canvas.width = 720; canvas.height = 540; canvas.tabIndex = 0;
      canvas.setAttribute("role", "grid"); canvas.setAttribute("aria-label", view.title + "; use arrow keys to inspect cells");
      var context = canvas.getContext("2d"), rows = values.length, columns = values[0].length;
      function color(value) {
        var ratio;
        if (mapping.scale === "diverging") {
          ratio = value <= center ? 0.5 * (value - minimum) / Math.max(center - minimum, 1e-12) :
            0.5 + 0.5 * (value - center) / Math.max(maximum - center, 1e-12);
          return "hsl(" + (220 - 220 * Math.max(0, Math.min(1, ratio))) + " 68% " + (42 + 38 * (1 - Math.abs(ratio - 0.5) * 2)) + "%)";
        }
        ratio = (value - minimum) / Math.max(maximum - minimum, 1e-12);
        return "hsl(" + (205 - 165 * ratio) + " 68% " + (94 - 54 * ratio) + "%)";
      }
      values.forEach(function (row, y) { row.forEach(function (raw, x) {
        context.fillStyle = Number.isFinite(Number(raw)) ? color(Number(raw)) : "#777";
        context.fillRect(x * canvas.width / columns, y * canvas.height / rows, canvas.width / columns + 0.5, canvas.height / rows + 0.5);
      }); });
      var readout = document.createElement("p"); readout.className = "matrix-readout"; readout.setAttribute("role", "status");
      var selected = { x: 0, y: 0 };
      function report() {
        readout.textContent = (mapping.x_label || "Column") + " " + xLabels[selected.x] + " · " +
          (mapping.y_label || "Row") + " " + yLabels[selected.y] + " · value " + values[selected.y][selected.x] +
          (mapping.unit ? " " + mapping.unit : "");
      }
      canvas.addEventListener("click", function (event) {
        var box = canvas.getBoundingClientRect();
        selected.x = Math.min(columns - 1, Math.max(0, Math.floor((event.clientX - box.left) / box.width * columns)));
        selected.y = Math.min(rows - 1, Math.max(0, Math.floor((event.clientY - box.top) / box.height * rows))); report();
      });
      canvas.addEventListener("keydown", function (event) {
        var moves = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
        if (!moves[event.key]) return; event.preventDefault();
        selected.x = Math.min(columns - 1, Math.max(0, selected.x + moves[event.key][0]));
        selected.y = Math.min(rows - 1, Math.max(0, selected.y + moves[event.key][1])); report();
      });
      var legend = document.createElement("p"); legend.className = "scientific-note";
      legend.textContent = "Scale " + minimum + " to " + maximum + (mapping.unit ? " " + mapping.unit : "") +
        " · " + directionLabel(mapping.direction) + " · grey marks missing values.";
      report(); region.replaceChildren(canvas, readout, legend);
    }
    if (sources.length > 1) stage.appendChild(scientificPicker(sources, "Matrix source", open));
    stage.appendChild(region); await open(sources[0]);
  }

  async function renderScalarSummary(view, stage, services) {
    var artifacts = artifactPaths(view, "data");
    if (!artifacts.length) throw new Error("The configured summary data is unavailable.");
    var list = document.createElement("dl"); list.className = "scalar-grid";
    async function open(artifact) {
      var payload = await loadJson(artifact, services.signal); list.replaceChildren();
      view.mapping.fields.forEach(function (field) {
        var term = document.createElement("dt"); term.textContent = field.label;
        var resolved = valueAtPath(payload, field.path);
        var value = document.createElement("dd"); value.textContent = resolved === null && field.nullable ? "N/A" :
          String(resolved) + (field.unit ? " " + field.unit : "");
        var meaning = document.createElement("span"); meaning.textContent = directionLabel(field.direction); value.appendChild(meaning);
        list.append(term, value);
      });
    }
    if (artifacts.length > 1) stage.appendChild(scientificPicker(artifacts, "Summary source", open));
    stage.appendChild(list); await open(artifacts[0]);
  }

  async function renderTrajectory(view, stage, services) {
    var topologies = artifactPaths(view, "topology"), coordinatesList = artifactPaths(view, "coordinates");
    var coordinates = coordinatesList[0];
    if (!coordinates) {
      var empty = document.createElement("p"); empty.className = "preview-message";
      empty.textContent = "No trajectory coordinates were produced for this run. Declared artifacts remain downloadable below.";
      stage.appendChild(empty); return;
    }
    var coordinateName = coordinates && coordinates.path.split("/").pop();
    var topology = view.mapping.association === "stem-prefix" ? topologies.find(function (artifact) {
      return coordinateName.startsWith(artifact.path.split("/").pop().replace(/\.[^.]+$/, "") + "_");
    }) : topologies[0];
    if (!topology || !coordinates) throw new Error("The declared topology and coordinates are required.");
    if (Number(topology.size) + Number(coordinates.size) > 64 * 1024 * 1024) {
      throw new Error("This trajectory exceeds the 64 MiB inline limit. Download it instead.");
    }
    var topologyResponse = await A.authFetch(topology.url, { signal: services.signal });
    var coordinatesResponse = await A.authFetch(coordinates.url, { signal: services.signal });
    if (!topologyResponse.ok || !coordinatesResponse.ok) throw new Error("Trajectory data could not be loaded.");
    var topologyText = await topologyResponse.text();
    var format = view.mapping.coordinate_format;
    var coordinateData = format === "pdb" ? await coordinatesResponse.text() : await coordinatesResponse.arrayBuffer();
    if (services.signal.aborted) return;
    var controls = document.createElement("div"); controls.className = "trajectory-controls";
    var previous = document.createElement("button"); previous.type = "button"; previous.textContent = "Previous";
    var play = document.createElement("button"); play.type = "button"; play.textContent = "Play"; play.setAttribute("aria-pressed", "false");
    var next = document.createElement("button"); next.type = "button"; next.textContent = "Next";
    var scrub = document.createElement("input"); scrub.type = "range"; scrub.min = "0"; scrub.max = "0"; scrub.value = "0";
    scrub.setAttribute("aria-label", "Trajectory frame");
    var speed = document.createElement("select"); speed.setAttribute("aria-label", "Playback speed");
    [0.5, 1, 2].forEach(function (value) { var option = document.createElement("option"); option.value = value; option.textContent = value + "×"; if (value === 1) option.selected = true; speed.appendChild(option); });
    var readout = document.createElement("span"); readout.setAttribute("role", "status"); readout.textContent = "Loading frames…";
    controls.append(previous, play, next, scrub, speed, readout);
    if (coordinatesList.length > 1) {
      var bounded = document.createElement("p"); bounded.className = "scientific-note";
      bounded.textContent = "Showing the first declared trajectory; " + (coordinatesList.length - 1) + " additional coordinate files remain downloadable below.";
      stage.appendChild(bounded);
    }
    var frame = document.createElement("iframe"); frame.className = "artifact-molstar-preview"; frame.sandbox = "allow-scripts";
    frame.title = "Mol* trajectory viewer"; stage.append(controls, frame);
    var timer = null, frameCount = 1, current = 0, settled = false, onMessage = null, abortHandler = null;
    function showFrame(index) {
      current = Math.min(frameCount - 1, Math.max(0, Number(index) || 0)); scrub.value = String(current);
      readout.textContent = (current + 1) + " / " + frameCount + " · " +
        (current * Number(view.mapping.timestep)) + " " + view.mapping.frame_unit;
    }
    function command(action, value) { postToShell(frame, { type: "trajectory-control", action: action, value: value }); }
    function stop() { clearInterval(timer); timer = null; play.textContent = "Play"; play.setAttribute("aria-pressed", "false"); }
    function start() {
      stop(); play.textContent = "Pause"; play.setAttribute("aria-pressed", "true");
      timer = setInterval(function () { command("advance", 1); }, 1000 / Number(speed.value));
    }
    previous.addEventListener("click", function () { command("advance", -1); }); next.addEventListener("click", function () { command("advance", 1); });
    scrub.addEventListener("input", function () { command("set", Number(scrub.value)); });
    play.addEventListener("click", function () { if (timer) stop(); else start(); }); speed.addEventListener("change", function () { if (timer) start(); });
    var ready = new Promise(function (resolve, reject) {
      var timeout = setTimeout(function () {
        window.removeEventListener("message", onMessage); reject(new Error("Trajectory viewer timed out"));
      }, 45000);
      onMessage = function (event) {
        if (event.source !== frame.contentWindow || !event.data) return;
        if (event.data.type === "shell-ready") {
          var payload = {
            type: "trajectory", requestId: "trajectory", topology: topologyText,
            coordinateFormat: format, label: coordinates.path, theme: readMolstarTheme()
          };
          if (format === "pdb") payload.coordinates = coordinateData;
          else payload.coordinateBytes = new Uint8Array(coordinateData);
          postToShell(frame, payload, format === "pdb" ? [] : [coordinateData]);
        } else if (event.data.type === "trajectory-ready") {
          settled = true; clearTimeout(timeout); frameCount = Math.max(1, Number(event.data.frameCount) || 1); scrub.max = String(frameCount - 1); showFrame(0); resolve();
        } else if (event.data.type === "trajectory-frame") showFrame(event.data.frame);
        else if (event.data.type === "error" && !settled) {
          clearTimeout(timeout); window.removeEventListener("message", onMessage); reject(new Error(event.data.message));
        }
      };
      window.addEventListener("message", onMessage);
      abortHandler = function () { clearTimeout(timeout); stop(); window.removeEventListener("message", onMessage); frame.remove(); resolve(); };
      services.signal.addEventListener("abort", abortHandler, { once: true });
    });
    frame.src = "/compute/viewer-shell"; await ready;
    return { destroy: function () {
      stop(); window.removeEventListener("message", onMessage);
      services.signal.removeEventListener("abort", abortHandler); frame.remove();
    } };
  }

  async function renderCandidateCollection(view, stage, services) {
    var candidates = artifactPaths(view, "candidates");
    if (!candidates.length) {
      var empty = document.createElement("p"); empty.className = "preview-message";
      empty.textContent = "No candidates passed the configured filters."; stage.appendChild(empty); return;
    }
    var layout = document.createElement("div"); layout.className = "candidate-layout";
    var list = document.createElement("div"); list.className = "candidate-list";
    var preview = document.createElement("div"); preview.className = "candidate-preview";
    var candidateGeneration = 0;
    // One stage for the whole view, so a booted Mol* shell lives in it and
    // picking the next candidate only loads new structure data. Recreating the
    // stage per candidate is what rebooted the viewer on every pick.
    var candidateStage = document.createElement("div"); candidateStage.className = "candidate-preview-stage";
    preview.appendChild(candidateStage);
    layout.append(list, preview); stage.appendChild(layout);
    async function openCandidate(artifact) {
      var generation = ++candidateGeneration;
      list.querySelectorAll(".candidate-card").forEach(function (node) {
        node.setAttribute("aria-current", node.dataset.path === artifact.path ? "true" : "false");
      });
      try {
        if (artifact.preview === "structure") {
          var structurePlugin = previewRegistry.resolve(artifact);
          if (exceedsPreviewLimit(artifact, structurePlugin, candidateStage)) return;
          // The shared structure path owns the persistent stage: the warm
          // viewer, the toolbar, caching, and prefetch are identical to the
          // artifact rail's.
          await previewStructure(artifact, candidateStage, services.signal);
          return;
        }
        // A non-structure candidate replaces the viewer entirely: a booted
        // WebGL context left behind would keep rendering under the new surface.
        disposeActiveViewer(true);
        candidateStage.replaceChildren();
        var plugin = previewRegistry.resolve(artifact);
        if (!plugin) {
          var message = document.createElement("p"); message.className = "preview-message";
          message.textContent = "No inline preview is available. Download this candidate instead."; candidateStage.appendChild(message); return;
        }
        var surface = document.createElement("div"); surface.className = "result-plugin-surface"; candidateStage.appendChild(surface);
        await plugin.render(artifact, surface, services);
      } catch (error) {
        if (generation !== candidateGeneration || (error && error.name === "AbortError")) return;
        candidateStage.replaceChildren(); var errorMessage = document.createElement("p"); errorMessage.className = "preview-message";
        errorMessage.textContent = error.message || "Preview unavailable"; candidateStage.appendChild(errorMessage);
      }
    }
    candidates.forEach(function (artifact) {
      var card = document.createElement("div"); card.className = "candidate-card"; card.dataset.path = artifact.path;
      var open = document.createElement("button"); open.type = "button"; open.className = "candidate-open";
      var name = document.createElement("strong"); name.textContent = artifact.path;
      var meta = document.createElement("span"); meta.textContent = formatBytes(artifact.size) + " · sha256 " + artifact.sha256.slice(0, 10);
      open.append(name, meta); open.addEventListener("click", function () { openCandidate(artifact); });
      card.appendChild(open); list.appendChild(card);
    });
    await openCandidate(candidates[0]);
  }

  function tableUrl(path, offset) {
    return "/compute/api/results/" + encodeURIComponent(task.md5) + "/tables/" +
      path.split("/").map(encodeURIComponent).join("/") + "?offset=" + offset + "&limit=100";
  }

  async function renderEntityTable(view, stage, services) {
    var tableArtifacts = artifactPaths(view, "table");
    if (tableArtifacts.length !== 1) throw new Error("The configured result table is unavailable.");
    var tableArtifact = tableArtifacts[0]; var structures = artifactPaths(view, "structure");
    var structureArtifact = structures[0] || null; var viewerFrame = null; var pendingSelection = null; var offset = 0;
    var layout = document.createElement("div"); layout.className = structureArtifact ? "linked-result-layout" : "linked-result-layout table-only";
    var tableRegion = document.createElement("div"); tableRegion.className = "linked-result-table";
    var viewerStage = document.createElement("div"); viewerStage.className = "linked-result-structure";
    layout.append(tableRegion); if (structureArtifact) layout.append(viewerStage); stage.appendChild(layout);

    async function loadPage() {
      var requestedOffset = offset;
      var page;
      try {
        var response = await A.authFetch(tableUrl(tableArtifact.path, requestedOffset), { signal: services.signal });
        if (!response.ok) throw new Error("Result table could not be loaded.");
        page = await response.json();
      } catch (error) {
        if (requestedOffset !== offset) return;
        throw error;
      }
      if (requestedOffset !== offset) return;
      tableRegion.replaceChildren();
      var wrap = document.createElement("div"); wrap.className = "artifact-table-wrap";
      var table = document.createElement("table"); table.className = "artifact-table-preview entity-result-table";
      var heading = document.createElement("tr");
      page.columns.forEach(function (column) { var th = document.createElement("th"); th.scope = "col"; th.textContent = column; heading.appendChild(th); });
      table.appendChild(heading);
      var indexes = {}; page.columns.forEach(function (column, index) { indexes[column] = index; });
      page.rows.forEach(function (row) {
        var tr = document.createElement("tr"); tr.tabIndex = 0; tr.setAttribute("aria-selected", "false");
        row.forEach(function (value) { var td = document.createElement("td"); td.textContent = value; tr.appendChild(td); });
        function follow() {
          table.querySelectorAll("tr[aria-selected=true]").forEach(function (node) { node.setAttribute("aria-selected", "false"); });
          tr.setAttribute("aria-selected", "true");
          if (!view.mapping.residue_column) return;
          pendingSelection = {
            type: "select-residue", chain: view.mapping.chain_column ? row[indexes[view.mapping.chain_column]] : "",
            residue: Number(row[indexes[view.mapping.residue_column]]), numbering: view.mapping.numbering
          };
          if (viewerFrame) postToShell(viewerFrame, pendingSelection);
        }
        tr.addEventListener("click", follow); tr.addEventListener("keydown", function (event) {
          if (event.key === "Enter") { event.preventDefault(); follow(); }
        }); table.appendChild(tr);
      });
      wrap.appendChild(table); tableRegion.appendChild(wrap);
      var pager = document.createElement("div"); pager.className = "table-pager";
      var previous = document.createElement("button"); previous.type = "button"; previous.className = "btn btn-soft btn-small";
      previous.textContent = "Previous"; previous.disabled = requestedOffset === 0;
      previous.addEventListener("click", function () { offset = Math.max(0, offset - 100); loadPage().catch(showPreviewError); });
      var next = document.createElement("button"); next.type = "button"; next.className = "btn btn-soft btn-small";
      next.textContent = "Next"; next.disabled = !page.has_more;
      next.addEventListener("click", function () { offset += 100; loadPage().catch(showPreviewError); });
      var pageLabel = document.createElement("span"); pageLabel.textContent = "Rows " + (requestedOffset + 1) + "–" + (requestedOffset + page.rows.length);
      pager.append(previous, pageLabel, next); tableRegion.appendChild(pager);
    }
    await loadPage();
    if (structureArtifact) {
      if (exceedsPreviewLimit(structureArtifact, previewRegistry.resolve(structureArtifact), viewerStage)) return;
      try {
        var response = await A.authFetch(structureArtifact.url, { signal: services.signal });
        if (!response.ok) throw new Error("Structure download failed");
        viewerFrame = await renderMolstar(
          await response.text(), structureArtifact, viewerStage, previewHost.generation, true, services.signal
        );
        if (viewerFrame && pendingSelection) postToShell(viewerFrame, pendingSelection);
      } catch (error) {
        if (services.signal.aborted) return;
        var message = document.createElement("p"); message.className = "preview-message";
        message.textContent = "Structure linking unavailable; the result table remains usable."; viewerStage.appendChild(message);
      }
    }
  }

  async function renderEvidenceBundle(view, stage, services) {
    var items = artifactPaths(view, "items"); var list = document.createElement("div"); list.className = "evidence-list";
    var preview = document.createElement("div"); preview.className = "evidence-preview"; stage.append(list, preview);
    var evidenceGeneration = 0;
    async function openEvidence(artifact) {
      var generation = ++evidenceGeneration; var plugin = previewRegistry.resolve(artifact);
      var surface = document.createElement("div"); surface.className = "result-plugin-surface"; preview.replaceChildren(surface);
      if (!plugin) { surface.textContent = "This evidence is available as a download."; return; }
      if (exceedsPreviewLimit(artifact, plugin, surface)) return;
      try { await plugin.render(artifact, surface, services); }
      catch (error) {
        if (generation !== evidenceGeneration || error.name === "AbortError") return;
        surface.replaceChildren(); var message = document.createElement("p"); message.className = "preview-message";
        message.textContent = error.message || "Preview unavailable"; surface.appendChild(message);
      }
    }
    items.forEach(function (artifact) {
      var button = document.createElement("button"); button.type = "button"; button.className = "evidence-item";
      button.textContent = artifact.path; button.addEventListener("click", function () { openEvidence(artifact); }); list.appendChild(button);
    });
    if (items[0]) await openEvidence(items[0]);
    else preview.textContent = "No evidence artifacts are available.";
  }

  function showPreviewError(error) {
    if (error && error.name === "AbortError") return;
    var stage = document.getElementById("artifactPreview");
    stage.innerHTML = '<p class="preview-message"></p>'; stage.firstChild.textContent = error.message || "Preview unavailable";
  }

  previewRegistry = window.REvoComputeResultPreviews.createRegistry({
    structure: async function (artifact, stage, services) {
      try {
        await previewStructure(artifact, stage, services.signal);
      } catch (error) {
        throw error;
      }
    },
    image: previewImage,
    table: previewTable,
    text: previewText,
    "candidate-collection": renderCandidateCollection,
    "entity-table": renderEntityTable,
    "evidence-bundle": renderEvidenceBundle,
    alignment: renderAlignment,
    trajectory: renderTrajectory,
    "metric-series": renderMetricSeries,
    matrix: renderMatrix,
    "scalar-summary": renderScalarSummary
  });
  previewHost = new window.REvoComputeResultPreviews.ResultPreviewHost(
    previewRegistry,
    document.getElementById("artifactPreview"),
    {
      statusNode: document.getElementById("previewStatus"),
      preserve: preserveStructureStage,
      beforeClear: function () {
        document.getElementById("previewStatus").textContent = "";
      }
    }
  );

  async function previewArtifact(artifact) {
    if (!artifact.path) artifact = Object.assign({}, artifact, { path: artifact.name || artifact.id });
    document.getElementById("previewTitle").textContent = artifact.path;
    document.getElementById("previewDescription").textContent = artifact.role + " artifact · " + formatBytes(artifact.size);
    var download = document.getElementById("artifactDownload"); download.hidden = false;
    download.href = artifact.url + (artifact.url.indexOf("?") === -1 ? "?" : "&") + "download=1"; download.download = "";
    document.querySelectorAll(".artifact-row").forEach(function (node) {
      var active = node.dataset.path === artifact.path; node.classList.toggle("active", active);
      node.setAttribute("aria-current", active ? "true" : "false");
    });
    var stage = document.getElementById("artifactPreview");
    stage.hidden = false;
    try { await previewHost.render(artifact); } catch (error) { showPreviewError(error); }
  }

  async function mountStoryboard(declaration, result) {
    if (!declaration || !declaration.entrypoint_url) return false;
    if (activeStoryboard && typeof activeStoryboard.destroy === "function") activeStoryboard.destroy();
    activeStoryboard = null;
    var files = new Map();
    Object.keys((result && result.files) || {}).forEach(function (id) {
      var values = result.files[id] || [];
      if (!values.length) files.set(id, null);
      else files.set(id, values.length === 1 && values[0].cardinality !== "many" ? values[0] : values);
    });
    if (declaration.requires.some(function (id) { return !files.get(id) || (Array.isArray(files.get(id)) && !files.get(id).length); })) {
      throw new Error("The required scientific result files are unavailable.");
    }
    var module = await import(declaration.entrypoint_url);
    var storyboard = module.default;
    if (!storyboard || typeof storyboard.mount !== "function") throw new Error("Storyboard entrypoint is invalid.");
    var stage = document.getElementById("artifactPreview");
    previewHost.destroy();
    document.getElementById("previewTitle").textContent = "Scientific result";
    document.getElementById("previewDescription").textContent = "Runner-provided scientific interpretation";
    document.getElementById("artifactDownload").hidden = true;
    var context = Object.freeze({ files: Object.freeze({ get: function (id) { return files.get(id) || null; } }),
      metadata: Object.freeze({ taskType: task.task_type }), services: Object.freeze({ openFile: previewArtifact }) });
    var instance = storyboard.mount(stage, context);
    activeStoryboard = instance && typeof instance.then === "function" ? await instance : (instance || storyboard);
    return true;
  }

  async function previewView(view, focusHeading) {
    document.getElementById("previewTitle").textContent = view.title;
    document.getElementById("artifactDownload").hidden = true;
    document.getElementById("previewDescription").textContent = view.description || "";
    document.querySelectorAll(".result-view-tab").forEach(function (node) {
      var active = node.dataset.viewId === view.id; node.setAttribute("aria-pressed", active ? "true" : "false");
    });
    document.getElementById("artifactPreview").hidden = false;
    try {
      await previewHost.render(view);
      if (focusHeading) document.getElementById("previewTitle").focus();
    } catch (error) { showPreviewError(error); }
  }

  function artifactButton(artifact, showParent) {
    var button = document.createElement("button"); button.type = "button"; button.className = "artifact-row"; button.dataset.path = artifact.path;
    var segments = artifact.path.split("/");
    var name = document.createElement("span"); name.className = "artifact-row-name"; name.textContent = segments[segments.length - 1];
    if (showParent && segments.length > 1) {
      var directory = document.createElement("small"); directory.className = "artifact-row-dir";
      directory.textContent = segments.slice(0, -1).join("/") + "/"; name.appendChild(directory);
    }
    button.title = artifact.path;
    var size = document.createElement("span"); size.className = "artifact-row-size";
    size.textContent = (artifact.role === "diagnostic" ? "Execution log · " : artifact.role + " · ") + formatBytes(artifact.size);
    button.append(name, size); button.addEventListener("click", function () { previewArtifact(artifact); }); return button;
  }

  function artifactFolder(directory, children) {
    var folder = document.createElement("details"); folder.className = "artifact-folder"; folder.open = true;
    var summary = document.createElement("summary"); summary.className = "artifact-folder-name"; summary.textContent = directory + "/";
    var inner = document.createElement("div"); inner.className = "artifact-folder-children";
    children.forEach(function (child) { inner.appendChild(child); }); folder.append(summary, inner); return folder;
  }

  function buildArtifactTree() {
    var root = { folders: {}, files: [] };
    artifacts.forEach(function (artifact) {
      var node = root; artifact.path.split("/").slice(0, -1).forEach(function (segment) {
        node.folders[segment] = node.folders[segment] || { folders: {}, files: [] }; node = node.folders[segment];
      }); node.files.push(artifact);
    });
    function renderNode(node) {
      var entries = [];
      Object.keys(node.folders).sort().forEach(function (name) { entries.push(artifactFolder(name, renderNode(node.folders[name]))); });
      node.files.slice().sort(function (a, b) { return a.path.localeCompare(b.path); })
        .forEach(function (artifact) { entries.push(artifactButton(artifact)); }); return entries;
    }
    return renderNode(root);
  }

  function renderArtifacts(query) {
    var normalized = String(query || "").trim().toLowerCase(); var list = document.getElementById("artifactList"); list.replaceChildren();
    if (normalized) {
      artifacts.filter(function (artifact) { return artifact.path.toLowerCase().includes(normalized); })
        .forEach(function (artifact) { list.appendChild(artifactButton(artifact, true)); }); return;
    }
    buildArtifactTree().forEach(function (node) { list.appendChild(node); });
  }

  function renderViewTabs() {
    var tabs = document.getElementById("resultViews"); tabs.replaceChildren();
    resultViews.forEach(function (view) {
      var button = document.createElement("button"); button.type = "button"; button.className = "result-view-tab";
      button.dataset.viewId = view.id; button.textContent = view.title;
      button.addEventListener("click", function () { previewView(view, true); }); tabs.appendChild(button);
    });
  }

  function appendDefinitionList(root, items) {
    items.forEach(function (item) {
      var term = document.createElement("dt"); term.textContent = item[0]; var value = document.createElement("dd"); value.textContent = item[1];
      root.append(term, value);
    });
  }

  function renderScientificRecord(payload) {
    var run = payload.run || {}; var method = run.method || {}; var check = payload.output_check || { state: "not_configured", problems: [] };
    document.getElementById("methodName").textContent = method.name || payload.task_type;
    document.getElementById("resultStatus").textContent = payload.status || task.status;
    var checkText = { passed: "Expected outputs found", failed: "Output mapping incomplete", not_configured: "No principal result mapping", not_assessed: "Outputs were not assessed" };
    document.getElementById("outputCheck").textContent = checkText[check.state] || check.state;
    document.getElementById("outputSummary").textContent = method.output_summary || "Inspect the published artifacts below.";
    var problems = document.getElementById("outputProblems"); problems.replaceChildren();
    (check.problems || []).forEach(function (problem) { var li = document.createElement("li"); li.textContent = problem; problems.appendChild(li); });
    var limitations = document.getElementById("limitationList"); limitations.replaceChildren();
    (payload.limitations || []).forEach(function (text) { var li = document.createElement("li"); li.textContent = text; limitations.appendChild(li); });
    var setup = document.getElementById("runSetup"); setup.replaceChildren();
    appendDefinitionList(setup, [
      ["Submitted", run.submitted_at || "—"], ["Started", run.started_at || "—"], ["Finished", run.finished_at || "—"],
      ["Wall time", run.walltime_seconds == null ? "—" : Math.round(run.walltime_seconds) + " s"]
    ]);
    (run.inputs || []).forEach(function (input) { appendDefinitionList(setup, [["Input", input.path + " · sha256 " + input.sha256]]); });
    (run.parameters || []).forEach(function (parameter) {
      appendDefinitionList(setup, [[parameter.label, String(parameter.value) + (parameter.unit ? " " + parameter.unit : "")]]);
    });
    var citations = document.getElementById("citationList"); citations.replaceChildren();
    (run.citations || []).forEach(function (citation) {
      var li = document.createElement("li"); var link = document.createElement("a"); link.href = citation.url || ("https://doi.org/" + citation.doi);
      link.target = "_blank"; link.rel = "noopener noreferrer"; link.textContent = citation.title + " · " + citation.doi; li.appendChild(link); citations.appendChild(li);
    });
  }

  async function loadResults() {
    await disposeActiveViewer(); structureTextCache.clear(); structureTextCacheBytes = 0;
    if (activeStoryboard && typeof activeStoryboard.destroy === "function") activeStoryboard.destroy();
    activeStoryboard = null;
    structureHolder = null;
    var response = await A.authFetch("/compute/api/results/" + encodeURIComponent(task.md5));
    var payload = await response.json().catch(function () { return {}; });
    if (window.__revocomputeStatusPoll) clearInterval(window.__revocomputeStatusPoll);
    var statusPollInFlight = false;
    // Terminality is decided by the server's `terminal` flag on the polling
    // response, not by a client-side copy of the status vocabulary.
    var initialTerminal = payload.terminal === true || task.terminal === true;
    if (!initialTerminal) {
      window.__revocomputeStatusPoll = setInterval(async function () {
        if (statusPollInFlight) return; statusPollInFlight = true;
        try {
          var pollResponse = await A.authFetch("/compute/api/running/" + encodeURIComponent(task.md5));
          var pollPayload = await pollResponse.json().catch(function () { return {}; });
          var isTerminal = pollPayload.terminal === true;
          if (!pollResponse.ok && !isTerminal) return;
          if (pollPayload.status) document.getElementById("resultStatus").textContent = pollPayload.status;
          if (isTerminal) { clearInterval(window.__revocomputeStatusPoll); window.location.reload(); }
        } catch (error) { /* retry transient failures */ } finally { statusPollInFlight = false; }
      }, 15000);
    }
    if (!response.ok || !Array.isArray(payload.artifacts)) {
      if (response.ok && !initialTerminal) return;
      throw new Error(payload.message || "Results are not available yet");
    }
    if (payload.schema_version !== 3) throw new Error("This result record uses an unsupported schema version.");
    artifacts = payload.artifacts; resultViews = Array.isArray(payload.views) ? payload.views : [];
    renderScientificRecord(payload); renderArtifacts(""); renderViewTabs();
    document.getElementById("artifactSummary").textContent = artifacts.length + " files · " + formatBytes(payload.total_size);
    var archiveButton = document.getElementById("archiveButton");
    delete archiveButton.dataset.downloadUrl;
    archiveButton.textContent = "Create ZIP";
    document.getElementById("archiveState").textContent = "Individual manifest-approved files are available now.";
    if (payload.archive && payload.archive.ready) {
      archiveButton.textContent = "Download ZIP"; archiveButton.dataset.downloadUrl = payload.archive.download_url;
      document.getElementById("archiveState").textContent = "The manifest-approved ZIP is ready.";
    }
    var storyboardLoaded = false;
    try { storyboardLoaded = await mountStoryboard(payload.storyboard, payload.result); }
    catch (error) { showToast(error.message || "Scientific result view unavailable; showing files.", "error"); }
    var first = resultViews.find(function (view) { return view.role === "primary"; });
    if (!storyboardLoaded && first) await previewView(first, false);
    else if (!storyboardLoaded) {
      document.getElementById("previewTitle").textContent = "No principal result view";
      document.getElementById("previewDescription").textContent = "This method has not yet declared a scientific result composition. All published artifacts remain available below.";
      var stage = document.getElementById("artifactPreview"); stage.replaceChildren();
      var empty = document.createElement("p"); empty.className = "preview-message";
      empty.textContent = "Open Files & diagnostics to inspect or download this run."; stage.appendChild(empty);
      var artifactsSection = document.querySelector(".artifact-section");
      if (artifactsSection) artifactsSection.open = true;
    }
  }

  async function archiveAction() {
    var button = document.getElementById("archiveButton");
    if (button.dataset.downloadUrl) { window.location.assign(button.dataset.downloadUrl); return; }
    button.disabled = true;
    try {
      var response = await A.authFetch("/compute/api/results/" + encodeURIComponent(task.md5) + "/archive", { method: "POST" });
      var payload = await response.json().catch(function () { return {}; });
      if (!response.ok && response.status !== 202) throw new Error(payload.error || "Archive request failed");
      document.getElementById("archiveState").textContent = "Archive generation requested. Refresh shortly to download it.";
      showToast("Archive generation requested.", "info");
    } catch (error) { showToast(error.message || "Archive request failed", "error"); }
    finally { button.disabled = false; }
  }

  document.addEventListener("DOMContentLoaded", function () {
    T.initToggle(document.getElementById("themeToggle"));
    var artifactSection = document.getElementById("artifactSection");
    // Mobile: keep the file rail a controlled disclosure instead of a long section.
    if (artifactSection && window.matchMedia && window.matchMedia("(max-width: 760px)").matches) {
      artifactSection.open = false;
    }
    document.getElementById("refreshResults").addEventListener("click", function () { window.location.reload(); });
    document.getElementById("artifactSearch").addEventListener("input", function (event) { renderArtifacts(event.target.value); });
    document.getElementById("archiveButton").addEventListener("click", archiveAction);

    loadResults().catch(function (error) {
      document.getElementById("artifactPreview").innerHTML = '<p class="preview-message"></p>';
      document.getElementById("artifactPreview").firstChild.textContent = error.message || "Results unavailable";
    });
  });
  window.addEventListener("pagehide", function () {
    previewHost.destroy();
  });
})();
