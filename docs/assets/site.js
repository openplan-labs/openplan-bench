/* openplan-bench dashboard behaviour. Vanilla, no dependencies, no network.
   Every table is sortable and filterable; the theme toggle covers all three
   viewer states (system, explicit light, explicit dark). */
(function () {
  "use strict";

  /* ---- theme --------------------------------------------------------- */
  var KEY = "openplan-bench-theme";
  var root = document.documentElement;

  function stored() {
    try { return localStorage.getItem(KEY); } catch (e) { return null; }
  }
  function persist(value) {
    try {
      if (value) { localStorage.setItem(KEY, value); } else { localStorage.removeItem(KEY); }
    } catch (e) { /* private mode: the toggle still works for this page view */ }
  }
  function apply(value) {
    if (value === "light" || value === "dark") {
      root.setAttribute("data-theme", value);
    } else {
      root.removeAttribute("data-theme");
    }
  }

  var initial = stored();
  if (initial) { apply(initial); }

  function label(value) {
    return value === "dark" ? "Dark" : value === "light" ? "Light" : "System";
  }

  function mountToggle() {
    var button = document.createElement("button");
    button.className = "themetoggle";
    button.type = "button";
    var state = stored() || "system";
    button.textContent = label(state);
    button.setAttribute("aria-label", "Colour theme: " + label(state));
    button.addEventListener("click", function () {
      state = state === "system" ? "light" : state === "light" ? "dark" : "system";
      apply(state === "system" ? null : state);
      persist(state === "system" ? null : state);
      button.textContent = label(state);
      button.setAttribute("aria-label", "Colour theme: " + label(state));
      swapFigures();
    });
    document.body.appendChild(button);
  }

  /* Figures are baked PNGs, so the dark variants are swapped in by hand.
     <picture> handles prefers-color-scheme but not an explicit data-theme. */
  function darkNow() {
    var explicit = root.getAttribute("data-theme");
    if (explicit) { return explicit === "dark"; }
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  }

  function swapFigures() {
    var dark = darkNow();
    var images = document.querySelectorAll("img[data-light]");
    for (var i = 0; i < images.length; i++) {
      var img = images[i];
      var next = dark ? img.getAttribute("data-dark") : img.getAttribute("data-light");
      if (next && img.getAttribute("src") !== next) { img.setAttribute("src", next); }
    }
  }

  if (window.matchMedia) {
    var query = window.matchMedia("(prefers-color-scheme: dark)");
    var listener = function () { swapFigures(); };
    if (query.addEventListener) { query.addEventListener("change", listener); }
    else if (query.addListener) { query.addListener(listener); }
  }

  /* ---- sortable tables ------------------------------------------------ */
  function cellValue(row, index) {
    var cell = row.cells[index];
    if (!cell) { return ""; }
    var raw = cell.getAttribute("data-sort");
    return raw === null ? cell.textContent.trim() : raw;
  }

  function comparator(index, ascending) {
    return function (a, b) {
      var x = cellValue(a, index);
      var y = cellValue(b, index);
      var nx = parseFloat(x);
      var ny = parseFloat(y);
      var bothNumeric = !isNaN(nx) && !isNaN(ny) && x !== "" && y !== "";
      var result;
      if (bothNumeric) {
        result = nx - ny;
      } else {
        result = String(x).localeCompare(String(y), undefined, { numeric: true });
      }
      return ascending ? result : -result;
    };
  }

  function makeSortable(table) {
    var headers = table.tHead ? table.tHead.rows[0].cells : [];
    var body = table.tBodies[0];
    if (!body) { return; }
    for (var i = 0; i < headers.length; i++) {
      (function (header, index) {
        header.setAttribute("role", "columnheader");
        header.setAttribute("tabindex", "0");
        function sort() {
          var ascending = header.getAttribute("aria-sort") !== "ascending";
          for (var j = 0; j < headers.length; j++) { headers[j].removeAttribute("aria-sort"); }
          header.setAttribute("aria-sort", ascending ? "ascending" : "descending");
          var rows = Array.prototype.slice.call(body.rows);
          rows.sort(comparator(index, ascending));
          for (var k = 0; k < rows.length; k++) { body.appendChild(rows[k]); }
        }
        header.addEventListener("click", sort);
        header.addEventListener("keydown", function (event) {
          if (event.key === "Enter" || event.key === " ") { event.preventDefault(); sort(); }
        });
      })(headers[i], i);
    }
  }

  /* ---- filtering ------------------------------------------------------ */
  function wireControls(scope) {
    var table = scope.querySelector("table");
    if (!table || !table.tBodies[0]) { return; }
    var body = table.tBodies[0];
    var text = scope.querySelector("input[data-filter]");
    var select = scope.querySelector("select[data-filter-outcome]");
    var count = scope.querySelector(".count");
    var total = body.rows.length;

    function refresh() {
      var needle = text && text.value ? text.value.toLowerCase() : "";
      var outcome = select && select.value ? select.value : "";
      var shown = 0;
      for (var i = 0; i < body.rows.length; i++) {
        var row = body.rows[i];
        var haystack = row.textContent.toLowerCase();
        var rowOutcome = row.getAttribute("data-outcome") || "";
        var ok = (!needle || haystack.indexOf(needle) !== -1) &&
                 (!outcome || rowOutcome === outcome);
        row.style.display = ok ? "" : "none";
        if (ok) { shown++; }
      }
      if (count) {
        count.textContent = shown === total
          ? total + " row" + (total === 1 ? "" : "s")
          : shown + " of " + total + " rows";
      }
    }

    if (text) { text.addEventListener("input", refresh); }
    if (select) { select.addEventListener("change", refresh); }
    refresh();
  }

  /* ---- boot ----------------------------------------------------------- */
  function boot() {
    mountToggle();
    swapFigures();
    var tables = document.querySelectorAll("table[data-sortable]");
    for (var i = 0; i < tables.length; i++) { makeSortable(tables[i]); }
    var scopes = document.querySelectorAll("[data-tablescope]");
    for (var j = 0; j < scopes.length; j++) { wireControls(scopes[j]); }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
