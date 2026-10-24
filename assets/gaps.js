// Gap-review page: City raster layer + gap markers, driven by a side table.

(function () {
  "use strict";

  var COLORS = {
    missing: "#7048e8", far: "#c92a2a", duplicate: "#d6336c",
    notype: "#2b8a3e", nocolour: "#e8590c", noposition: "#1c7ed6",
    osm_only: "#495057",
  };
  // What a mapper does about each status; shown in the popup.
  var ACTIONS = {
    missing: "No OSM hydrant here. Add it once you have seen it.",
    far: "The nearest OSM hydrant is some metres off. Check which point is right.",
    duplicate: "Two OSM hydrants for one City hydrant. One is probably surplus.",
    notype: "The OSM hydrant has no fire_hydrant:type (pillar, underground...).",
    nocolour: "The OSM hydrant has no colour.",
    noposition: "The OSM hydrant has no fire_hydrant:position (green, sidewalk...).",
    osm_only: "No City hydrant nearby. Probably private (the City layer is " +
      "municipal only): worth a look, not a fix.",
  };
  var map;
  var features = [];
  var markers = [];      // CircleMarker per feature, indexed like features
  var highlight = null;  // ring + link line of the currently selected gap
  var selectedRow = null;
  var selectedIndex = null;  // feature index of the current selection

  function init() {
    var el = document.getElementById("gap-map");
    if (!el || typeof L === "undefined" || !el.dataset.geojson) {
      return;
    }
    // Canvas, not SVG: there are thousands of markers.
    map = L.map(el, { preferCanvas: true }).setView([43.5448, -80.2482], 13);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">' +
        "OpenStreetMap</a> contributors",
    }).addTo(map);
    if (el.dataset.raster) {
      L.tileLayer(el.dataset.raster, {
        minZoom: 15, maxNativeZoom: 17, maxZoom: 19, opacity: 0.85,
      }).addTo(map);
    }

    fetch(el.dataset.geojson)
      .then(function (r) { return r.json(); })
      .then(render)
      .catch(function (e) {
        el.innerHTML = '<p style="padding:1rem">Could not load gaps.geojson.</p>';
        console.error(e);
      });
  }

  function render(data) {
    features = data.features || [];

    features.forEach(function (f, i) {
      f.properties._i = i;
      var c = f.geometry.coordinates;
      f._center = [c[1], c[0]];
      // "missing" is nearly every City hydrant; smaller, so the rest show.
      var m = L.circleMarker(f._center, {
        radius: f.properties.status === "missing" ? 4 : 7,
        color: "#fff",
        weight: 2,
        fillColor: COLORS[f.properties.status] || "#888",
        fillOpacity: 0.95,
      });
      m.bindPopup(popupHtml(f));
      m.on("click", function () { select(i, false); });
      markers[i] = m;
    });
    // Canvas draws in the order added: "missing" first, so it never covers
    // the rarer statuses.
    features.forEach(function (f, i) {
      if (f.properties.status === "missing") { markers[i].addTo(map); }
    });
    features.forEach(function (f, i) {
      if (f.properties.status !== "missing") { markers[i].addTo(map); }
    });

    buildTable();
    wireControls();
  }

  // Where to send the user for a feature: the openstreetmap.org view and the
  // iD editor. Points at the existing OSM hydrant when there is one, else at
  // the City's point.
  function osmTargets(f) {
    var p = f.properties;
    var m = p.osm_url && p.osm_url.match(/(node|way|relation)\/(\d+)/);
    if (m) {
      return {
        osm: p.osm_url,
        id: "https://www.openstreetmap.org/edit?" + m[1] + "=" + m[2],
      };
    }
    var c = f._center;
    var ll = c[0].toFixed(5) + "/" + c[1].toFixed(5);
    return {
      osm: "https://www.openstreetmap.org/#map=19/" + ll,
      id: "https://www.openstreetmap.org/edit#map=19/" + ll,
    };
  }

  // "OSM · iD" link pair shared by the table and the popups.
  function osmPairHtml(f) {
    var t = osmTargets(f);
    return '<a href="' + t.osm + '" target="_blank" rel="noopener" ' +
      'title="View on openstreetmap.org (hotkey: O)">OSM</a> &middot; ' +
      '<a href="' + t.id + '" target="_blank" rel="noopener" ' +
      'title="Open in the iD editor (hotkey: I)">iD</a>';
  }

  // What names the row: the City's hydrant number, else its ArcGIS row.
  function label(p) {
    if (p.hydrant_id != null) { return String(p.hydrant_id); }
    if (p.objectid != null) { return "row " + p.objectid; }
    return "(OSM)";
  }

  function popupHtml(f) {
    var p = f.properties;
    var h = "<strong>Hydrant " + esc(label(p)) + "</strong>" +
      (p.location_id ? " &middot; " + esc(p.location_id) : "") +
      "<br>" + p.status + ": " + esc(ACTIONS[p.status] || "");
    (p.lacks || []).forEach(function (s) {
      if (s !== p.status) { h += "<br>also " + s + ": " + esc(ACTIONS[s]); }
    });
    if (p.distance_m != null) {
      h += "<br>City &harr; OSM: " + p.distance_m + " m";
    }
    if (p.nearest_city_m != null) {
      h += "<br>Nearest City hydrant: " + p.nearest_city_m + " m";
    }
    var tags = p.osm_tags || {};
    var have = Object.keys(tags).map(function (k) { return k + "=" + tags[k]; });
    if (have.length) { h += "<br>OSM: " + esc(have.join(", ")); }
    h += "<br>" + osmPairHtml(f);
    if (p.other_url) {
      h += ' &middot; <a href="' + p.other_url +
        '" target="_blank" rel="noopener">the other OSM hydrant</a> (' +
        p.other_distance_m + " m)";
    }
    return h;
  }

  // Every status a row answers to: its own, plus each tag it lacks.
  function statusesOf(p) {
    var all = [p.status];
    (p.lacks || []).forEach(function (s) {
      if (all.indexOf(s) < 0) { all.push(s); }
    });
    return all;
  }

  function sortKey(p) {
    if (p.hydrant_id != null) { return p.hydrant_id; }
    return p.objectid != null ? 1e9 + p.objectid : Infinity;
  }

  function buildTable() {
    var tbody = document.querySelector("#gap-table tbody");
    var rows = features.slice().sort(function (a, b) {
      return sortKey(a.properties) - sortKey(b.properties);
    });
    tbody.innerHTML = rows.map(function (f) {
      var p = f.properties;
      var statuses = statusesOf(p);
      var more = statuses.slice(1).map(function (s) {
        return ' <span class="also status-' + s + '">+' + s + "</span>";
      }).join("");
      var dist = p.status === "far" || p.status === "duplicate"
        ? p.distance_m : (p.status === "osm_only" ? p.nearest_city_m : null);
      var search = (label(p) + " " + (p.location_id || "")).toLowerCase();
      return '<tr data-i="' + p._i + '" data-status="' + statuses.join(" ") +
        '" data-search="' + esc(search) + '">' +
        '<td class="ref">' + esc(label(p)) + "</td>" +
        "<td>" + esc(p.location_id || "") + "</td>" +
        '<td class="status-' + p.status + '">' + p.status +
        (dist != null ? ' <span class="dist">' + dist + "&nbsp;m</span>" : "") +
        more + "</td>" +
        '<td><span class="osm-links">' + osmPairHtml(f) + "</span></td></tr>";
    }).join("");

    tbody.addEventListener("click", function (ev) {
      if (ev.target.closest("a")) { return; }  // let OSM links work
      var tr = ev.target.closest("tr");
      if (tr) { select(parseInt(tr.dataset.i, 10), true); }
    });
  }

  // Select a gap: ring it, join it to its OSM hydrant, fit the map, open its
  // popup, mark its row.
  function select(i, fromTable) {
    var f = features[i];
    if (!f) { return; }
    selectedIndex = i;
    var p = f.properties;

    if (highlight) { map.removeLayer(highlight); }
    var layers = [L.circleMarker(f._center, {
      radius: 13, color: "#0a7", weight: 3, fill: false,
    })];
    if (p.osm_lat != null && p.osm_lon != null) {
      var osm = [p.osm_lat, p.osm_lon];
      layers.push(L.polyline([f._center, osm], {
        color: "#0a7", weight: 2, dashArray: "4 4",
      }));
      layers.push(L.circleMarker(osm, {
        radius: 5, color: "#0a7", weight: 2, fillColor: "#fff", fillOpacity: 1,
      }));
    }
    highlight = L.featureGroup(layers).addTo(map);
    var bounds = highlight.getBounds();
    if (bounds.getNorthEast().equals(bounds.getSouthWest())) {
      map.setView(f._center, 18);
    } else {
      map.fitBounds(bounds, { maxZoom: 18, padding: [60, 60] });
    }
    if (markers[i]) { markers[i].openPopup(); }

    if (selectedRow) { selectedRow.classList.remove("selected"); }
    var tr = document.querySelector('#gap-table tr[data-i="' + i + '"]');
    if (tr) {
      tr.classList.add("selected");
      selectedRow = tr;
      if (!fromTable) { tr.scrollIntoView({ block: "center" }); }
    }
  }

  function wireControls() {
    var boxes = {};
    Array.prototype.forEach.call(
      document.querySelectorAll(".controls input[data-status]"),
      function (b) { boxes[b.dataset.status] = b; }
    );
    var filter = document.getElementById("filter");

    function statusOn(status) {
      var b = boxes[status];
      return b ? b.checked : true;
    }

    function apply() {
      var q = filter.value.trim().toLowerCase();

      var rows = document.querySelectorAll("#gap-table tbody tr");
      Array.prototype.forEach.call(rows, function (tr) {
        var hit = tr.dataset.status.split(" ").some(statusOn) &&
          (!q || tr.dataset.search.indexOf(q) > -1);
        tr.style.display = hit ? "" : "none";
        var m = markers[parseInt(tr.dataset.i, 10)];
        if (hit && !map.hasLayer(m)) { map.addLayer(m); }
        else if (!hit && map.hasLayer(m)) { map.removeLayer(m); }
      });
    }

    Object.keys(boxes).forEach(function (k) {
      boxes[k].addEventListener("change", apply);
    });
    filter.addEventListener("input", apply);
    apply();

    // O / I open the selected gap on openstreetmap.org / in the iD editor.
    document.addEventListener("keydown", function (ev) {
      if (ev.ctrlKey || ev.metaKey || ev.altKey) { return; }
      if (/^(input|textarea|select)$/i.test(ev.target.tagName)) { return; }
      var key = ev.key.toLowerCase();
      if (key !== "o" && key !== "i") { return; }
      if (selectedIndex == null) { return; }
      var t = osmTargets(features[selectedIndex]);
      ev.preventDefault();
      window.open(key === "o" ? t.osm : t.id, "_blank", "noopener");
    });
  }

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  document.addEventListener("DOMContentLoaded", init);
})();
