/* REvoCompute — public Runner catalog filtering */
/* SPDX-License-Identifier: GPL-3.0-only */

(function () {
  "use strict";
  var UI = window.REvoComputeUI;
  var catalog = document.getElementById("runnerCatalog");
  var search = document.getElementById("runnerSearch");
  var category = document.getElementById("runnerCategory");
  var count = document.getElementById("runnerCatalogCount");
  var empty = document.getElementById("runnerCatalogEmpty");
  if (!catalog) return;

  function render() {
    var query = search.value.trim().toLowerCase();
    var selectedCategory = category.value;
    var shown = 0;
    catalog.querySelectorAll(".runner-category").forEach(function (section) {
      var categoryMatches = !selectedCategory || section.dataset.category === selectedCategory;
      var sectionCount = 0;
      section.querySelectorAll(".runner-card").forEach(function (card) {
        var visible = categoryMatches && (!query || card.dataset.search.toLowerCase().includes(query));
        card.hidden = !visible;
        if (visible) { shown += 1; sectionCount += 1; }
      });
      section.hidden = sectionCount === 0;
    });
    count.textContent = shown + " " + (shown === 1 ? "method" : "methods");
    empty.hidden = shown !== 0;
  }

  search.addEventListener("input", render);
  category.addEventListener("change", render);
  UI.bindSegmented(document.getElementById("catalogDensity"), "catalogDensity", function (value) { catalog.dataset.density = value; });
  render();
})();
