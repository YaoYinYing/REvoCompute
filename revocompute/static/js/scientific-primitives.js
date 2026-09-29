/* REvoCompute shared scientific result primitives */
/* SPDX-License-Identifier: GPL-3.0-only */

(function () {
  "use strict";

  var MATRIX_LIMIT = 1048576;
  var SERIES_LIMIT = 100000;
  function clamp(value, maximum) { return Math.max(0, Math.min(maximum - 1, value)); }
  function finite(value) { return value != null && Number.isFinite(Number(value)); }
  function svg(name) { return document.createElementNS("http://www.w3.org/2000/svg", name); }
  function same(left, right) {
    var keys = Object.keys(left);
    return keys.length === Object.keys(right).length && keys.every(function (key) { return left[key] === right[key]; });
  }

  function ResultSelectionStore(initial) {
    this.state = Object.assign({ candidate: null, entityA: null, entityB: null, token: null }, initial || {});
    this.listeners = new Set();
  }
  ResultSelectionStore.prototype.get = function () { return Object.freeze(Object.assign({}, this.state)); };
  ResultSelectionStore.prototype.set = function (patch, source) {
    var next = Object.assign({}, this.state, patch || {});
    if (same(next, this.state)) return this.get();
    this.state = next;
    var snapshot = this.get();
    this.listeners.forEach(function (listener) { listener(snapshot, source || null); });
    return snapshot;
  };
  ResultSelectionStore.prototype.subscribe = function (listener) {
    if (typeof listener !== "function") throw new TypeError("Selection listener must be a function.");
    this.listeners.add(listener);
    var listeners = this.listeners;
    return function () { listeners.delete(listener); };
  };
  ResultSelectionStore.prototype.destroy = function () { this.listeners.clear(); };

  function CandidateSelector(host, options) {
    options = options || {};
    this.host = host;
    this.options = options;
    this.items = Array.from(options.items || []);
    this.onSelect = options.onSelect || function () {};
    this.store = options.store || null;
    this.generation = 0;
    this.controller = null;
    this.render();
  }
  CandidateSelector.prototype.render = function () {
    var self = this;
    this.host.replaceChildren();
    this.items.forEach(function (item, index) {
      var button = document.createElement("button");
      button.type = "button";
      button.className = self.options.buttonClass || "candidate-open";
      button.textContent = self.options.label ? self.options.label(item, index) : String(item.label || item.path || index + 1);
      button.dataset.index = String(index);
      button.setAttribute("aria-current", "false");
      button.addEventListener("click", function () { self.select(index); });
      self.host.appendChild(button);
    });
  };
  CandidateSelector.prototype.select = function (index) {
    var self = this;
    var item = this.items[index];
    if (!item) return Promise.resolve(null);
    if (this.controller) this.controller.abort();
    this.controller = typeof AbortController === "function" ? new AbortController() : null;
    var generation = ++this.generation;
    var operation;
    try {
      operation = this.onSelect(item, index, {
        generation: generation,
        signal: this.controller ? this.controller.signal : null,
        current: function () { return generation === self.generation; },
      });
    } catch (error) { operation = Promise.reject(error); }
    return Promise.resolve(operation).then(function (result) {
      if (generation !== self.generation) return null;
      self.host.querySelectorAll("button[data-index]").forEach(function (button) {
        button.setAttribute("aria-current", Number(button.dataset.index) === index ? "true" : "false");
      });
      if (self.store) self.store.set({ candidate: item.id == null ? index : item.id }, self);
      return result;
    });
  };
  CandidateSelector.prototype.destroy = function () {
    this.generation += 1;
    if (this.controller) this.controller.abort();
    this.host.replaceChildren();
  };

  function ScalarMetricGrid(host, metrics) { this.host = host; this.update(metrics); }
  ScalarMetricGrid.prototype.update = function (metrics) {
    var list = document.createElement("dl");
    list.className = "scalar-grid";
    (metrics || []).forEach(function (metric) {
      if (metric.value == null && !metric.nullable) return;
      var term = document.createElement("dt"); term.textContent = metric.label;
      var value = document.createElement("dd");
      value.textContent = metric.value == null ? "N/A" : String(metric.value) + (metric.unit ? " " + metric.unit : "");
      if (metric.meaning) { var meaning = document.createElement("span"); meaning.textContent = metric.meaning; value.appendChild(meaning); }
      list.append(term, value);
    });
    this.host.replaceChildren(list); this.element = list;
  };
  ScalarMetricGrid.prototype.destroy = function () { this.host.replaceChildren(); };

  function StructureViewport(host, options) {
    options = options || {};
    if (!options.viewer && typeof options.createViewer !== "function") throw new TypeError("StructureViewport requires a viewer or createViewer function.");
    this.host = host; this.viewer = options.viewer || null; this.destroyed = false;
    this.root = document.createElement("div"); this.root.className = "structure-viewport";
    this.viewerHost = document.createElement("div"); this.viewerHost.className = "structure-viewport-host";
    if (options.toolbar) this.root.appendChild(options.toolbar);
    this.root.appendChild(this.viewerHost); host.replaceChildren(this.root);
    this.ready = Promise.resolve(this.viewer || options.createViewer()).then(function (viewer) {
      this.viewer = viewer;
      if (viewer && typeof viewer.mount === "function") return Promise.resolve(viewer.mount(this.viewerHost, options.viewerOptions || {})).then(function () { return viewer; });
      return viewer;
    }.bind(this));
    if (window.ResizeObserver) {
      this.observer = new ResizeObserver(function () { if (this.viewer && typeof this.viewer.resize === "function") this.viewer.resize(); }.bind(this));
      this.observer.observe(this.root);
    }
  }
  StructureViewport.prototype.call = function (method, argument) {
    if (this.destroyed) return Promise.reject(new Error("StructureViewport has been destroyed."));
    return this.ready.then(function (viewer) {
      if (!viewer || typeof viewer[method] !== "function") throw new Error("The molecular viewer does not support " + method + ".");
      return viewer[method](argument);
    });
  };
  ["loadStructure", "setRepresentation", "setColor", "select", "focus", "setTheme"].forEach(function (method) {
    StructureViewport.prototype[method] = function (value) { return this.call(method, value); };
  });
  ["clear", "resetCamera", "captureImage"].forEach(function (method) {
    StructureViewport.prototype[method] = function () { return this.call(method); };
  });
  StructureViewport.prototype.destroy = function () {
    if (this.destroyed) return;
    this.destroyed = true;
    if (this.observer) this.observer.disconnect();
    this.ready.then(function (viewer) { if (viewer && typeof viewer.dispose === "function") viewer.dispose(); });
    this.host.replaceChildren();
  };

  function LocalConfidenceSeries(host, options) {
    this.host = host; this.options = {}; this.update(options || {});
    if (window.ResizeObserver) { this.observer = new ResizeObserver(function () { this.render(); }.bind(this)); this.observer.observe(host); }
  }
  LocalConfidenceSeries.prototype.update = function (options) {
    this.options = Object.assign({}, this.options, options || {});
    var count = (this.options.series || []).reduce(function (total, item) { return total + (item.values || []).length; }, 0);
    if (count > (this.options.maxPoints || SERIES_LIMIT)) throw new RangeError("The metric series exceeds the point limit.");
    this.render();
  };
  LocalConfidenceSeries.prototype.render = function () {
    var options = this.options, series = options.series || [];
    var length = series.reduce(function (maximum, item) { return Math.max(maximum, (item.values || []).length); }, 0);
    var xValues = options.xValues || Array.from({ length: length }, function (_, index) { return index + 1; });
    var values = [];
    series.forEach(function (item) { (item.values || []).forEach(function (value) { if (finite(value)) values.push(Number(value)); }); });
    if (!values.length) throw new Error("The metric series contains no numeric values.");
    var width = Math.max(320, Math.min(options.maximumWidth || 760, this.host.clientWidth || options.maximumWidth || 760));
    var height = Math.round(width * 360 / 760), pad = 48;
    var yMin = options.yMin == null ? Math.min.apply(null, values) : Number(options.yMin);
    var yMax = options.yMax == null ? Math.max.apply(null, values) : Number(options.yMax); if (yMin === yMax) yMax += 1;
    var numericX = xValues.map(Number), xMin = Math.min.apply(null, numericX), xMax = Math.max.apply(null, numericX);
    var chart = svg("svg"); chart.setAttribute("viewBox", "0 0 " + width + " " + height); chart.setAttribute("role", "img");
    chart.setAttribute("aria-label", (options.yLabel || "Metric") + " by " + (options.xLabel || "index"));
    var colors = options.colors || ["#087f8c", "#c44536", "#6a4c93", "#2f7d32", "#b26a00"];
    series.forEach(function (item, seriesIndex) {
      var path = svg("path"), drawing = false;
      var commands = (item.values || []).map(function (raw, index) {
        var value = Number(raw); if (!Number.isFinite(value) || !Number.isFinite(numericX[index])) { drawing = false; return null; }
        var x = pad + (width - 2 * pad) * ((numericX[index] - xMin) / Math.max(xMax - xMin, 1));
        var y = height - pad - (height - 2 * pad) * ((value - yMin) / (yMax - yMin));
        var command = drawing ? "L" : "M"; drawing = true; return command + x.toFixed(1) + " " + y.toFixed(1);
      }).filter(Boolean).join(" ");
      path.setAttribute("d", commands); path.setAttribute("fill", "none"); path.setAttribute("stroke", item.color || colors[seriesIndex % colors.length]); path.setAttribute("stroke-width", "2"); chart.appendChild(path);
    });
    var summary = document.createElement("p"); summary.className = "scientific-note";
    summary.textContent = (options.xLabel || "Index") + ": " + xValues.length + " points · " + (options.yLabel || "Value") + ": " + yMin.toFixed(3) + "–" + yMax.toFixed(3) + (options.unit ? " " + options.unit : "") + (options.direction ? " · " + options.direction : "");
    this.host.replaceChildren(chart, summary);
  };
  LocalConfidenceSeries.prototype.destroy = function () { if (this.observer) this.observer.disconnect(); this.host.replaceChildren(); };

  function rampColor(ramp, ratio) {
    if (!Number.isFinite(ratio)) return [119, 119, 119];
    var position = Math.max(0, Math.min(1, ratio)) * (ramp.length - 1), low = Math.min(ramp.length - 2, Math.floor(position)), blend = position - low;
    return [1, 3, 5].map(function (index) {
      var from = parseInt(ramp[low].slice(index, index + 2), 16), to = parseInt(ramp[low + 1].slice(index, index + 2), 16);
      return Math.round(from + (to - from) * blend);
    });
  }

  function loadNumericProjection(artifact, options) {
    options = options || {};
    if (!artifact || !artifact.ndarray_url) return Promise.reject(new TypeError("The artifact has no numeric projection URL."));
    var sliceSize = options.sliceSize == null ? 16384 : Number(options.sliceSize);
    var maximum = options.maxElements == null ? MATRIX_LIMIT : Number(options.maxElements);
    if (!Number.isInteger(sliceSize) || sliceSize < 1 || sliceSize > 16384 || !Number.isInteger(maximum) || maximum < 1 || maximum > MATRIX_LIMIT) {
      return Promise.reject(new RangeError("Numeric projection limits are invalid."));
    }
    var fetcher = options.fetch || function (url, init) {
      return window.REvoDesignAuth
        ? window.REvoDesignAuth.authFetch(url, init)
        : window.fetch(url, Object.assign({ credentials: "same-origin" }, init));
    };
    var values = [], metadata = null, offset = 0;
    function next() {
      var query = new URLSearchParams({ offset: String(offset), limit: String(sliceSize) });
      if (options.key != null) query.set("key", String(options.key));
      var separator = artifact.ndarray_url.indexOf("?") === -1 ? "?" : "&";
      return Promise.resolve(fetcher(artifact.ndarray_url + separator + query, { signal: options.signal })).then(function (response) {
        if (!response.ok) {
          var failure = new Error("The numeric projection could not be loaded.");
          failure.status = response.status;
          throw failure;
        }
        return response.json();
      }).then(function (page) {
        var shape = page.shape;
        var total = page.total_elements;
        var shapeTotal = Array.isArray(shape) && shape.length
          ? shape.reduce(function (product, size) { return Number.isInteger(size) && size >= 0 ? product * size : NaN; }, 1)
          : NaN;
        if (!Number.isInteger(total) || total < 0 || total > maximum || shapeTotal !== total ||
            !Array.isArray(page.data) || page.offset !== offset || page.count !== page.data.length ||
            page.data.some(function (value) { return value !== null && !finite(value); })) {
          throw new Error("The numeric projection is invalid or exceeds browser limits.");
        }
        if (!metadata) metadata = { dtype: page.dtype, shape: shape.slice(), key: page.key, totalElements: total };
        else if (JSON.stringify(shape) !== JSON.stringify(metadata.shape) || total !== metadata.totalElements || page.key !== metadata.key || page.dtype !== metadata.dtype) {
          throw new Error("The numeric projection changed while loading.");
        }
        Array.prototype.push.apply(values, page.data);
        offset += page.count;
        if (page.has_more) {
          if (page.count < 1 || offset >= total) throw new Error("The numeric projection pagination is invalid.");
          return next();
        }
        if (offset !== total) throw new Error("The numeric projection is incomplete.");
        return { dtype: metadata.dtype, shape: metadata.shape, key: metadata.key, totalElements: total, values: values };
      });
    }
    return next();
  }

  function validateMatrix(data, limit) {
    var values = data && data.values;
    if (!Array.isArray(values) || !values.length || !Array.isArray(values[0]) || !values[0].length) throw new TypeError("PairMatrix requires a non-empty two-dimensional values array.");
    var columns = values[0].length;
    if (values.length * columns > limit) throw new RangeError("The pair matrix exceeds the element limit.");
    values.forEach(function (row) { if (!Array.isArray(row) || row.length !== columns) throw new TypeError("PairMatrix rows must have equal length."); });
    return { rows: values.length, columns: columns };
  }

  function PairMatrix(options) {
    options = options || {};
    if (!options.figure || !options.canvas) throw new TypeError("PairMatrix requires figure and canvas elements.");
    this.options = options; this.figure = options.figure; this.canvas = options.canvas; this.readout = options.readout || null;
    this.values = []; this.xLabels = []; this.yLabels = []; this.xGroups = []; this.yGroups = [];
    this.selected = { x: 0, y: 0 }; this.showBorders = false;
    this.maximumWidth = (options.geometry && options.geometry.width) || 800; this.maximumElements = options.maxElements || MATRIX_LIMIT;
    this.observe = options.observe || this.figure.parentElement;
    this.handlers = {
      click: function (event) { this.pick(event, true); }.bind(this),
      pointermove: function (event) { this.pick(event, false); }.bind(this),
      keydown: function (event) {
        var moves = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }, move = moves[event.key];
        if (!move || !this.ready()) return; event.preventDefault(); this.select(this.selected.x + move[0], this.selected.y + move[1]);
      }.bind(this),
    };
    this.canvas.addEventListener("click", this.handlers.click); this.canvas.addEventListener("pointermove", this.handlers.pointermove); this.canvas.addEventListener("keydown", this.handlers.keydown);
    if (window.ResizeObserver) { this.observer = new ResizeObserver(function () { this.draw(); }.bind(this)); this.observer.observe(this.observe); }
    if (window.MutationObserver) { this.themeObserver = new MutationObserver(function () { this.draw(); }.bind(this)); this.themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] }); }
  }
  PairMatrix.prototype.ready = function () { return this.values.length > 0 && Array.isArray(this.values[0]) && this.values[0].length > 0; };
  PairMatrix.prototype.clamp = function (x, y) { return { x: clamp(x, this.values[0].length), y: clamp(y, this.values.length) }; };
  PairMatrix.prototype.geometry = function () {
    var base = this.options.geometry || { width: 800, height: 600, left: 78, top: 30, size: 500, legendX: 604, legendWidth: 24 };
    var available = this.observe ? this.observe.clientWidth : this.maximumWidth;
    var width = Math.max(this.options.minimumWidth || 320, Math.min(this.maximumWidth, available || this.maximumWidth));
    var scale = width / base.width;
    return { width: width, height: Math.round(base.height * scale), left: base.left * scale, top: base.top * scale, size: base.size * scale, legendX: base.legendX * scale, legendWidth: Math.max(12, base.legendWidth * scale), scale: scale };
  };
  PairMatrix.prototype.setData = function (data) {
    var dimensions = validateMatrix(data, this.maximumElements);
    this.values = data.values; this.xLabels = Array.from(data.xLabels || [], String); this.yLabels = Array.from(data.yLabels || [], String);
    this.xGroups = Array.from(data.xGroups || []); this.yGroups = Array.from(data.yGroups || data.xGroups || []);
    while (this.xLabels.length < dimensions.columns) this.xLabels.push(String(this.xLabels.length + 1));
    while (this.yLabels.length < dimensions.rows) this.yLabels.push(String(this.yLabels.length + 1));
    this.selected = { x: 0, y: 0 }; this.draw();
  };
  PairMatrix.prototype.setBorders = function (shown) { this.showBorders = Boolean(shown); this.draw(); };
  PairMatrix.prototype.cellFromEvent = function (event) {
    var box = this.canvas.getBoundingClientRect(), geometry = this.geometry();
    var x = Math.floor((((event.clientX - box.left) * (geometry.width / box.width) - geometry.left) / geometry.size) * this.values[0].length);
    var y = Math.floor((((event.clientY - box.top) * (geometry.height / box.height) - geometry.top) / geometry.size) * this.values.length);
    return this.clamp(x, y);
  };
  PairMatrix.prototype.pick = function (event, selected) {
    if (!this.ready()) return; var cell = this.cellFromEvent(event);
    if (selected) this.select(cell.x, cell.y); else { this.report(cell.x, cell.y); if (this.options.onHover) this.options.onHover(this.cell(cell.x, cell.y)); }
  };
  PairMatrix.prototype.cell = function (x, y) { var raw = (this.values[y] || [])[x]; return { x: x, y: y, value: raw == null ? NaN : Number(raw), xLabel: this.xLabels[x], yLabel: this.yLabels[y], xGroup: this.xGroups[x], yGroup: this.yGroups[y] }; };
  PairMatrix.prototype.select = function (x, y) {
    if (!this.ready()) return; this.selected = this.clamp(x, y); this.draw();
    if (this.options.onSelect) this.options.onSelect(this.cell(this.selected.x, this.selected.y));
  };
  PairMatrix.prototype.report = function (x, y) {
    if (!this.readout) return; var cell = this.cell(x, y), options = this.options;
    this.readout.textContent = options.formatReadout ? options.formatReadout(cell) : (options.xTitle || "Column") + " " + cell.xLabel + " · " + (options.yTitle || "Row") + " " + cell.yLabel + " · value " + cell.value + (options.unit ? " " + options.unit : "");
  };
  PairMatrix.prototype.draw = function () {
    if (!this.ready()) return;
    var options = this.options, geometry = this.geometry(), canvas = this.canvas, context = canvas.getContext("2d"), dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(geometry.width * dpr); canvas.height = Math.round(geometry.height * dpr); canvas.style.width = geometry.width + "px"; canvas.style.height = geometry.height + "px";
    this.figure.style.width = geometry.width + "px"; this.figure.style.height = geometry.height + "px";
    context.setTransform(dpr, 0, 0, dpr, 0, 0); context.clearRect(0, 0, geometry.width, geometry.height); canvas.removeAttribute("aria-disabled");
    var minimum = options.minimum == null ? Infinity : Number(options.minimum), maximum = options.maximum == null ? -Infinity : Number(options.maximum);
    this.values.forEach(function (row) { row.forEach(function (raw) { if (finite(raw)) { var value = Number(raw); minimum = Math.min(minimum, value); maximum = Math.max(maximum, value); } }); });
    if (!Number.isFinite(minimum)) minimum = 0; if (!Number.isFinite(maximum)) maximum = minimum + 1; var span = maximum - minimum || 1;
    var ramp = typeof options.ramp === "function" ? options.ramp() : (options.ramp || ["#eef7fb", "#7db9dc", "#155b8a"]);
    if (!Array.isArray(ramp) || ramp.length < 2) throw new TypeError("PairMatrix requires at least two ramp colours.");
    var columns = this.values[0].length, rows = this.values.length, cells = document.createElement("canvas"); cells.width = columns; cells.height = rows;
    var cellContext = cells.getContext("2d"), image = cellContext.createImageData(columns, rows);
    this.values.forEach(function (row, y) { row.forEach(function (raw, x) { var color = rampColor(ramp, finite(raw) ? (Number(raw) - minimum) / span : NaN), offset = (y * columns + x) * 4; image.data[offset] = color[0]; image.data[offset + 1] = color[1]; image.data[offset + 2] = color[2]; image.data[offset + 3] = 255; }); });
    cellContext.putImageData(image, 0, 0); context.imageSmoothingEnabled = false; context.drawImage(cells, geometry.left, geometry.top, geometry.size, geometry.size);
    var tokens = getComputedStyle(document.body), ink = tokens.getPropertyValue("--ink").trim() || "#1d2a2f", line = tokens.getPropertyValue("--line").trim() || "#d4ddd8";
    if (this.showBorders) {
      context.strokeStyle = ink; context.globalAlpha = 0.9; context.lineWidth = 1.5;
      [this.xGroups, this.yGroups].forEach(function (groups, axis) { for (var index = 1; index < groups.length; index += 1) { if (groups[index] === groups[index - 1]) continue; var offset = geometry.size * index / groups.length; context.beginPath(); if (!axis) { context.moveTo(geometry.left + offset, geometry.top); context.lineTo(geometry.left + offset, geometry.top + geometry.size); } else { context.moveTo(geometry.left, geometry.top + offset); context.lineTo(geometry.left + geometry.size, geometry.top + offset); } context.stroke(); } });
      context.globalAlpha = 1;
    }
    context.strokeStyle = ink; context.lineWidth = 1; context.strokeRect(geometry.left, geometry.top, geometry.size, geometry.size);
    var gradient = context.createLinearGradient(0, geometry.top, 0, geometry.top + geometry.size); ramp.forEach(function (color, index) { gradient.addColorStop(1 - index / (ramp.length - 1), color); });
    context.fillStyle = gradient; context.fillRect(geometry.legendX, geometry.top, geometry.legendWidth, geometry.size); context.strokeStyle = line; context.strokeRect(geometry.legendX + 0.5, geometry.top + 0.5, geometry.legendWidth, geometry.size);
    this.drawTicks(context, geometry, ink);
    var selectedX = geometry.left + geometry.size * (this.selected.x + 0.5) / columns, selectedY = geometry.top + geometry.size * (this.selected.y + 0.5) / rows;
    context.lineWidth = 3; context.strokeStyle = "#fff"; context.strokeRect(selectedX - 6, selectedY - 6, 12, 12); context.lineWidth = 1; context.strokeStyle = ink; context.strokeRect(selectedX - 6, selectedY - 6, 12, 12);
    this.drawLabels(geometry, minimum, maximum); this.report(this.selected.x, this.selected.y);
    if (options.onDraw) options.onDraw({ rows: rows, columns: columns, minimum: minimum, maximum: maximum, geometry: geometry });
  };
  PairMatrix.prototype.drawTicks = function (context, geometry, color) {
    var ticks = this.options.ticks == null ? 5 : this.options.ticks, columns = this.values[0].length, rows = this.values.length;
    context.strokeStyle = color; context.beginPath();
    for (var tick = 0; tick <= ticks; tick += 1) {
      var xIndex = Math.round((columns - 1) * tick / ticks), yIndex = Math.round((rows - 1) * tick / ticks);
      var x = geometry.left + geometry.size * (xIndex + 0.5) / columns, y = geometry.top + geometry.size * (yIndex + 0.5) / rows, legendY = geometry.top + geometry.size - geometry.size * tick / ticks;
      context.moveTo(x, geometry.top + geometry.size); context.lineTo(x, geometry.top + geometry.size + 5 * geometry.scale);
      context.moveTo(geometry.left, y); context.lineTo(geometry.left - 5 * geometry.scale, y);
      context.moveTo(geometry.legendX + geometry.legendWidth, legendY); context.lineTo(geometry.legendX + geometry.legendWidth + 5 * geometry.scale, legendY);
    }
    context.stroke();
  };
  PairMatrix.prototype.drawLabels = function (geometry, minimum, maximum) {
    var self = this, options = this.options, ticks = options.ticks == null ? 5 : options.ticks, span = maximum - minimum || 1;
    var columns = this.values[0].length, rows = this.values.length;
    this.figure.querySelectorAll(".pair-matrix-label").forEach(function (node) { node.remove(); });
    function label(text, styles, classes) { var node = document.createElement("span"); node.className = "pair-matrix-label " + (classes || ""); node.textContent = text; Object.assign(node.style, styles); self.figure.appendChild(node); }
    for (var tick = 0; tick <= ticks; tick += 1) {
      var xIndex = Math.round((columns - 1) * tick / ticks), yIndex = Math.round((rows - 1) * tick / ticks);
      var xCenter = geometry.size * (xIndex + 0.5) / columns, yCenter = geometry.size * (yIndex + 0.5) / rows;
      label(this.xLabels[xIndex], { left: geometry.left + xCenter + "px", top: geometry.top + geometry.size + 8 * geometry.scale + "px" }, "pair-matrix-label-x");
      label(this.yLabels[yIndex], { top: geometry.top + yCenter + "px", left: "0", width: geometry.left - 9 * geometry.scale + "px", textAlign: "right" }, "pair-matrix-label-y pair-matrix-tick-y");
      label((minimum + span * tick / ticks).toFixed(options.decimals == null ? 1 : options.decimals), { left: geometry.legendX + geometry.legendWidth + 8 * geometry.scale + "px", top: geometry.top + geometry.size - geometry.size * tick / ticks + "px" }, "pair-matrix-label-y pair-matrix-tick-legend");
    }
    label((options.legendTitle || "Scale") + " " + maximum.toFixed(options.decimals == null ? 1 : options.decimals), { left: geometry.legendX + "px", top: geometry.top - 18 * geometry.scale + "px" }, "pair-matrix-title");
    label(options.xTitle || "Column", { left: geometry.left + geometry.size / 2 + "px", top: geometry.top + geometry.size + 26 * geometry.scale + "px" }, "pair-matrix-title pair-matrix-label-x");
    label(options.yTitle || "Row", { left: 20 * geometry.scale + "px", top: geometry.top + geometry.size / 2 + "px" }, "pair-matrix-title pair-matrix-title-y");
  };
  PairMatrix.prototype.destroy = function () {
    if (this.observer) this.observer.disconnect(); if (this.themeObserver) this.themeObserver.disconnect();
    this.canvas.removeEventListener("click", this.handlers.click); this.canvas.removeEventListener("pointermove", this.handlers.pointermove); this.canvas.removeEventListener("keydown", this.handlers.keydown);
    this.figure.querySelectorAll(".pair-matrix-label").forEach(function (node) { node.remove(); });
  };

  function AlignmentCoverage(host, text, options) {
    options = options || {}; var rows = String(text || "").split(/\r?\n/), sequences = [], current = null, maximum = options.maxRows || 5000;
    rows.forEach(function (line) { if (line.startsWith(">")) { if (sequences.length >= maximum) { current = null; return; } current = { name: line.slice(1).trim(), sequence: "" }; sequences.push(current); } else if (current) current.sequence += line.trim(); });
    var pre = document.createElement("pre"); pre.className = "msa-block"; pre.setAttribute("role", "img"); pre.setAttribute("aria-label", options.title || "Alignment coverage");
    sequences.forEach(function (item) { var heading = document.createElement("span"); heading.className = "msa-header"; heading.textContent = ">" + item.name; var sequence = document.createElement("span"); sequence.className = "msa-sequence"; sequence.textContent = item.sequence; pre.append(heading, sequence); });
    host.replaceChildren(pre); this.host = host; this.element = pre; this.rowCount = sequences.length;
  }
  AlignmentCoverage.prototype.destroy = function () { this.host.replaceChildren(); };

  function EntitySummaryTable(host, options) { this.host = host; this.options = options || {}; this.render(); }
  EntitySummaryTable.prototype.render = function () {
    var options = this.options, table = document.createElement("table"); table.className = "artifact-table-preview entity-result-table";
    var heading = document.createElement("tr"); (options.columns || []).forEach(function (column) { var th = document.createElement("th"); th.scope = "col"; th.textContent = column; heading.appendChild(th); }); table.appendChild(heading);
    (options.rows || []).forEach(function (row, index) { var tr = document.createElement("tr"); tr.tabIndex = 0; tr.setAttribute("aria-selected", "false"); row.forEach(function (value) { var td = document.createElement("td"); td.textContent = value; tr.appendChild(td); }); function select() { table.querySelectorAll("tr[aria-selected=true]").forEach(function (node) { node.setAttribute("aria-selected", "false"); }); tr.setAttribute("aria-selected", "true"); if (options.store) options.store.set(options.selection ? options.selection(row, index) : { entityA: row[0] }, table); if (options.onSelect) options.onSelect(row, index); } tr.addEventListener("click", select); tr.addEventListener("keydown", function (event) { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); select(); } }); table.appendChild(tr); });
    this.host.replaceChildren(table); this.element = table;
  };
  EntitySummaryTable.prototype.update = function (options) { this.options = Object.assign({}, this.options, options || {}); this.render(); };
  EntitySummaryTable.prototype.destroy = function () { this.host.replaceChildren(); };

  window.REvoComputeScientific = Object.freeze({ ResultSelectionStore: ResultSelectionStore, CandidateSelector: CandidateSelector, ScalarMetricGrid: ScalarMetricGrid, StructureViewport: StructureViewport, LocalConfidenceSeries: LocalConfidenceSeries, loadNumericProjection: loadNumericProjection, PairMatrix: PairMatrix, AlignmentCoverage: AlignmentCoverage, EntitySummaryTable: EntitySummaryTable });
})();
