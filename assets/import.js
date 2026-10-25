// Import-chunks page: every chunk's points and box on a map, driven by the table.

(function () {
  "use strict";

  // Neighbouring chunks get different colours; there are only a handful.
  var PALETTE = ["#7048e8", "#e8590c", "#0ca678", "#c2255c", "#1c7ed6",
                 "#f59f00", "#495057", "#9c36b5", "#2f9e44", "#e03131",
                 "#0b7285", "#a61e4d"];
  var map;
  var chunks = {};       // name -> {kind, layer, bounds}

  function init() {
    var el = document.getElementById("gap-map");
    if (!el || typeof L === "undefined") { return; }
    map = L.map(el, { preferCanvas: true }).setView([43.70, -79.40], 11);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">' +
        "OpenStreetMap</a> contributors",
    }).addTo(map);
    fetch(el.dataset.geojson)
      .then(function (r) { return r.json(); })
      .then(render)
      .catch(function (e) {
        el.innerHTML = '<p style="padding:1rem">Could not load chunks.geojson.</p>';
        console.error(e);
      });
  }

  function render(data) {
    var byName = {};
    data.features.forEach(function (f) {
      var p = f.properties;
      (byName[p.chunk] = byName[p.chunk] || { kind: p.kind, points: [] })
        .points.push([f.geometry.coordinates[1], f.geometry.coordinates[0]]);
    });
    var rows = document.querySelectorAll("#gap-table tbody tr");
    Array.prototype.forEach.call(rows, function (tr, i) {
      var c = byName[tr.dataset.chunk];
      if (!c) { return; }
      var color = PALETTE[i % PALETTE.length];
      var bounds = L.latLngBounds(c.points);
      var layers = [L.rectangle(bounds, {
        color: color, weight: 1.5, fill: false, dashArray: "5 4",
      }).bindTooltip(tr.dataset.chunk, { sticky: true })];
      c.points.forEach(function (ll) {
        layers.push(L.circleMarker(ll, {
          radius: 3, stroke: false, fillColor: color, fillOpacity: 0.9,
        }));
      });
      chunks[tr.dataset.chunk] = {
        kind: c.kind, bounds: bounds, layer: L.featureGroup(layers).addTo(map),
      };
      tr.querySelector(".kind").style.background = color;
    });

    document.querySelector("#gap-table tbody").addEventListener("click",
      function (ev) {
        if (ev.target.closest("a")) { return; }  // let the links work
        var tr = ev.target.closest("tr");
        if (tr) { select(tr.dataset.chunk); }
      });
    Array.prototype.forEach.call(
      document.querySelectorAll(".controls input[data-kind]"),
      function (b) { b.addEventListener("change", apply); }
    );
    apply();
  }

  function select(name) {
    var c = chunks[name];
    if (!c) { return; }
    map.fitBounds(c.bounds, { padding: [30, 30] });
    Array.prototype.forEach.call(
      document.querySelectorAll("#gap-table tbody tr"),
      function (tr) { tr.classList.toggle("selected", tr.dataset.chunk === name); }
    );
    Object.keys(chunks).forEach(function (k) {
      chunks[k].layer.eachLayer(function (l) {
        if (l instanceof L.Rectangle) { l.setStyle({ weight: k === name ? 3 : 1.5 }); }
      });
    });
  }

  function apply() {
    var on = {};
    Array.prototype.forEach.call(
      document.querySelectorAll(".controls input[data-kind]"),
      function (b) { on[b.dataset.kind] = b.checked; }
    );
    Array.prototype.forEach.call(
      document.querySelectorAll("#gap-table tbody tr"),
      function (tr) {
        var hit = on[tr.dataset.kind] !== false;
        tr.style.display = hit ? "" : "none";
        var c = chunks[tr.dataset.chunk];
        if (!c) { return; }
        if (hit && !map.hasLayer(c.layer)) { map.addLayer(c.layer); }
        else if (!hit && map.hasLayer(c.layer)) { map.removeLayer(c.layer); }
      }
    );
  }

  document.addEventListener("DOMContentLoaded", init);
})();
