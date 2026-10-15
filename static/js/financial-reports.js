/* Financial reports: live totals, add/remove lines, thousands separators, Enter-to-move-down. */
(function () {
  "use strict";
  var MAX_ROWS = 60;

  function parse(text) {
    var s = String(text == null ? "" : text).replace(/[₱,\s]/g, "");
    if (!s || s === "-") return 0;
    var neg = /^\(.*\)$/.test(s);
    if (neg) s = s.slice(1, -1);
    var n = parseFloat(s);
    if (!isFinite(n) || !/^-?\d*\.?\d*$/.test(s)) return 0;
    return neg ? -n : n;
  }
  function valid(text) {
    var s = String(text == null ? "" : text).replace(/[₱,\s]/g, "");
    return s === "" || s === "-" || /^-?\d*\.?\d+$|^-?\d+\.?$/.test(s) || /^\(\d*\.?\d+\)$/.test(s);
  }
  function round2(n) { return Math.round(n * 100) / 100; }
  function body(n) {
    var a = Math.abs(n);
    return a % 1 === 0 ? a.toLocaleString("en-US", { maximumFractionDigits: 0 })
                       : a.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  function fmt(n) { n = round2(n); if (n === 0) return "-"; return n < 0 ? "(" + body(n) + ")" : body(n); }
  function fmtIn(n) { n = round2(n); if (n === 0) return ""; return (n < 0 ? "-" : "") + body(n); }

  function init(table) {
    var ncols = parseInt(table.dataset.ncols, 10);
    var extra = table.dataset.extra ? JSON.parse(table.dataset.extra) : null;
    var form = table.closest("form");
    var check = document.getElementById("frCheck");
    var dirty = false;

    function rowExtra(vals) {
      if (!extra) return null;
      if (extra.kind === "rowsum") return vals.reduce(function (a, b) { return a + b; }, 0);
      return vals[extra.a] - vals[extra.b];
    }
    function isBad(good, d) {
      if (!good || d === null) return false;
      return good === "high" ? d < -0.004 : d > 0.004;
    }
    function setExtra(tr, ex, paren, good) {
      var cell = tr.querySelector("[data-extra-cell]");
      if (!cell || ex === null) return;
      cell.textContent = fmt(paren ? -ex : ex);
      cell.classList.toggle("fr-bad", isBad(good, ex));
    }
    function setCells(tr, vals, paren) {
      Array.prototype.forEach.call(tr.querySelectorAll("[data-cell]"), function (cell) {
        var v = vals[parseInt(cell.dataset.cell, 10)] || 0;
        cell.textContent = fmt(paren ? -v : v);
      });
    }

    function recalc() {
      var totals = {};
      Array.prototype.forEach.call(table.querySelectorAll("tbody.fr-sec, tr[data-calc]"), function (node) {
        if (node.matches("tbody.fr-sec")) {
          var paren = node.dataset.paren === "1", good = node.dataset.good, sums = [];
          for (var c = 0; c < ncols; c++) sums.push(0);
          Array.prototype.forEach.call(node.querySelectorAll("tr.fr-line"), function (tr) {
            var vals = Array.prototype.map.call(tr.querySelectorAll("input.fr-in"), function (i) { return parse(i.value); });
            vals.forEach(function (v, i) { sums[i] += v; });
            setExtra(tr, rowExtra(vals), paren, good);
          });
          totals[node.dataset.sec] = sums;
          var tot = node.querySelector("tr.fr-total");
          if (tot) { setCells(tot, sums, paren); setExtra(tot, rowExtra(sums), paren, good); }
        } else {
          var vals2 = [];
          for (var k = 0; k < ncols; k++) vals2.push(0);
          JSON.parse(node.dataset.calc).forEach(function (term) {
            var ref = totals[term[1]] || [];
            for (var j = 0; j < ncols; j++) vals2[j] += (term[0] === "+" ? 1 : -1) * (ref[j] || 0);
          });
          totals[node.dataset.id] = vals2;
          setCells(node, vals2, false);
          setExtra(node, rowExtra(vals2), false, node.dataset.good);
        }
      });
      if (check) {
        var a = totals[check.dataset.a], b = totals[check.dataset.b];
        if (a && b) {
          var gap = round2(a[0] - b[0]);
          check.className = "fr-check no-print " + (gap === 0 ? "ok" : "off");
          check.textContent = gap === 0 ? "✓ Balanced: " + check.dataset.label
            : "Out of balance by ₱" + body(gap) + ": " + check.dataset.label;
        }
      }
    }

    table.addEventListener("input", function (e) {
      if (!e.target.matches("input")) return;
      dirty = true;
      if (e.target.classList.contains("fr-in")) e.target.classList.toggle("fr-invalid", !valid(e.target.value));
      recalc();
    });
    table.addEventListener("focusin", function (e) {
      if (e.target.classList.contains("fr-in") && !e.target.readOnly) e.target.select();
    });
    table.addEventListener("focusout", function (e) {
      var i = e.target;
      if (i.classList && i.classList.contains("fr-in") && valid(i.value)) { i.value = fmtIn(parse(i.value)); i.classList.remove("fr-invalid"); recalc(); }
    });
    table.addEventListener("keydown", function (e) {
      if (e.key !== "Enter" || !e.target.matches("input")) return;
      e.preventDefault();  // Enter moves down a row instead of submitting the form
      var col = e.target.dataset.col, same = Array.prototype.filter.call(
        table.querySelectorAll("input" + (col !== undefined ? '[data-col="' + col + '"]' : ".fr-lab")), function (i) { return !i.readOnly; });
      var next = same[same.indexOf(e.target) + 1];
      if (next) next.focus();
    });
    table.addEventListener("click", function (e) {
      var add = e.target.closest(".fr-add"), del = e.target.closest(".fr-del");
      if (add) {
        var tbody = add.closest("tbody"), tpl = tbody.querySelector("template.fr-tpl");
        if (tbody.querySelectorAll("tr.fr-line").length >= MAX_ROWS) return;
        var row = tpl.content.querySelector("tr").cloneNode(true);
        tbody.insertBefore(row, tbody.querySelector("tr.fr-addrow"));
        var lab = row.querySelector("input.fr-lab"); if (lab) lab.focus();
        dirty = true; recalc();
      } else if (del) {
        del.closest("tr").remove(); dirty = true; recalc();
      }
    });
    if (form) {
      form.addEventListener("submit", function (e) {
        var bad = table.querySelector("input.fr-invalid");
        if (bad) { e.preventDefault(); bad.focus(); alert("One of the amounts is not a valid number."); return; }
        dirty = false;
      });
      window.addEventListener("beforeunload", function (e) { if (dirty) { e.preventDefault(); e.returnValue = ""; } });
    }
    recalc();
  }

  document.addEventListener("DOMContentLoaded", function () {
    Array.prototype.forEach.call(document.querySelectorAll("table.fr-table"), init);

    // Billing statement: add / remove charge rows.
    var list = document.getElementById("stCharges"), tpl = document.getElementById("stChargeTpl");
    if (list && tpl) {
      document.getElementById("stAddCharge").addEventListener("click", function () {
        if (list.children.length >= MAX_ROWS) return;
        list.appendChild(tpl.content.firstElementChild.cloneNode(true));
        list.lastElementChild.querySelector("input").focus();
      });
      list.addEventListener("click", function (e) {
        var del = e.target.closest(".st-del");
        if (del) del.closest(".st-charge").remove();
      });
    }
  });
})();
