// Gap-review page: City raster layer + gap markers, driven by a side table.

(function () {
  "use strict";

  var COLORS = {
    missing: "#7048e8", far: "#c92a2a", duplicate: "#d6336c",
    osm_only: "#495057",
  };
  var KINDS = { column: "Poster column", shelter_board: "Shelter poster board" };
  var JOSM = "http://127.0.0.1:8111/load_and_zoom";
  var PAD_M = 30;  // JOSM box: this much around the City and OSM points

  // A circle marker drawn as a square, for shelter boards: the same shapes as
  // the raster layer (round column, flat board). Canvas renderer only, which
  // is what this page uses; clicks still hit-test as the circle it extends.
  var SquareMarker = L.CircleMarker.extend({
    _updatePath: function () {
      var r = this._renderer;
      if (!r._drawing || this._empty()) { return; }
      var p = this._point, s = this._radius, ctx = r._ctx;
      ctx.beginPath();
      ctx.rect(p.x - s, p.y - s, 2 * s, 2 * s);
      r._fillStroke(ctx, this);
    },
  });
  // What a mapper does about each status; shown in the popup.
  var ACTIONS = {
    missing: "Nothing in OSM here. Add it once you have seen it.",
    far: "The nearest OSM board or advertising is some metres off. Check " +
      "which point is right.",
    duplicate: "Two OSM features for one City point. One may be surplus " +
      "(or a column mapped once per face).",
    osm_only: "No City point nearby. Probably a private board (the City's " +
      "lists are its own street furniture): worth a look, not a fix.",
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
    map = L.map(el, { preferCanvas: true }).setView([43.6510, -79.3960], 14);
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
      // "missing" is most City points; smaller, so the rest show.
      var Marker = f.properties.kind === "shelter_board"
        ? SquareMarker : L.CircleMarker;
      var m = new Marker(f._center, {
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

  // Where to send the user for a feature: the openstreetmap.org view, the
  // iD editor, and JOSM remote control (the point(s) padded PAD_M, downloaded).
  // Points at the existing OSM feature when there is one, else at the City's
  // point.
  function osmTargets(f) {
    var p = f.properties;
    var m = p.osm_url && p.osm_url.match(/(node|way|relation)\/(\d+)/);
    var josm = josmUrl(f, m ? m[1] + m[2] : null);
    if (m) {
      return {
        osm: p.osm_url,
        id: "https://www.openstreetmap.org/edit?" + m[1] + "=" + m[2],
        josm: josm,
      };
    }
    var c = f._center;
    var ll = c[0].toFixed(5) + "/" + c[1].toFixed(5);
    return {
      osm: "https://www.openstreetmap.org/#map=19/" + ll,
      id: "https://www.openstreetmap.org/edit#map=19/" + ll,
      josm: josm,
    };
  }

  // load_and_zoom over the City point and its OSM feature (when there is
  // one), padded PAD_M, with that OSM object selected.
  function josmUrl(f, select) {
    var p = f.properties, c = f._center;
    var s = c[0], n = c[0], w = c[1], e = c[1];
    if (p.osm_lat != null && p.osm_lon != null) {
      s = Math.min(s, p.osm_lat); n = Math.max(n, p.osm_lat);
      w = Math.min(w, p.osm_lon); e = Math.max(e, p.osm_lon);
    }
    var dLat = PAD_M / 111320;
    var dLon = PAD_M / (111320 * Math.cos((s + n) / 2 * Math.PI / 180));
    return JOSM + "?left=" + (w - dLon).toFixed(6) +
      "&right=" + (e + dLon).toFixed(6) + "&top=" + (n + dLat).toFixed(6) +
      "&bottom=" + (s - dLat).toFixed(6) +
      (select ? "&select=" + select : "") +
      "&changeset_source=" + encodeURIComponent("City of Toronto Poster Columns");
  }

  // "OSM · iD · JOSM" links shared by the table and the popups. JOSM is a
  // plain navigation in one reused tab named "josm", not a fetch: browsers
  // gate background requests from a public page to localhost, not a link the
  // mapper clicks. That tab shows JOSM's "OK", or a connection error when
  // JOSM or its remote control is off.
  function osmPairHtml(f) {
    var t = osmTargets(f);
    return '<a href="' + t.osm + '" target="_blank" rel="noopener" ' +
      'title="View on openstreetmap.org (hotkey: O)">OSM</a> &middot; ' +
      '<a href="' + t.id + '" target="_blank" rel="noopener" ' +
      'title="Open in the iD editor (hotkey: I)">iD</a> &middot; ' +
      '<a href="' + esc(t.josm) + '" class="josm" target="josm" ' +
      'title="Load this area into JOSM via remote control (hotkey: J)">JOSM</a>';
  }

  // What names the row: the City's asset ID (shown, never for ref).
  function label(p) {
    return p.id != null ? String(p.id) : "(OSM)";
  }

  function popupHtml(f) {
    var p = f.properties;
    var h = "<strong>" + esc(KINDS[p.kind] || "OSM feature") + "</strong>" +
      (p.id ? " &middot; " + esc(p.id) : "") +
      (p.address ? "<br>" + esc(p.address) : "") +
      (p.city_status && p.city_status !== "Existing"
        ? "<br>City status: " + esc(p.city_status) : "") +
      "<br>" + p.status + ": " + esc(ACTIONS[p.status] || "");
    if (p.distance_m != null) {
      h += "<br>City &harr; OSM: " + p.distance_m + " m";
    }
    if (p.nearest_city_m != null) {
      h += "<br>Nearest City point: " + p.nearest_city_m + " m";
    }
    var tags = p.osm_tags || {};
    var have = Object.keys(tags).map(function (k) { return k + "=" + tags[k]; });
    if (have.length) { h += "<br>OSM: " + esc(have.join(", ")); }
    h += "<br>" + osmPairHtml(f);
    if (p.other_url) {
      h += ' &middot; <a href="' + p.other_url +
        '" target="_blank" rel="noopener">the other OSM feature</a> (' +
        p.other_distance_m + " m)";
    }
    return h;
  }

  // Columns first (the layer's main subject), then by ID; OSM-only rows last.
  function sortKey(p) {
    var k = p.kind === "column" ? "0" : (p.kind ? "1" : "2");
    return k + (p.id || p.osm_url || "");
  }

  // The second column: the City's address, or what the OSM feature is.
  function where(p) {
    if (p.address) { return p.address; }
    var t = p.osm_tags || {};
    if (t.advertising) { return "advertising=" + t.advertising; }
    return t.board_type ? "board_type=" + t.board_type : "";
  }

  function buildTable() {
    var tbody = document.querySelector("#gap-table tbody");
    var rows = features.slice().sort(function (a, b) {
      var ka = sortKey(a.properties), kb = sortKey(b.properties);
      return ka < kb ? -1 : (ka > kb ? 1 : 0);
    });
    tbody.innerHTML = rows.map(function (f) {
      var p = f.properties;
      var dist = p.status === "far" || p.status === "duplicate"
        ? p.distance_m : (p.status === "osm_only" ? p.nearest_city_m : null);
      var search = (label(p) + " " + where(p)).toLowerCase();
      // Hollow, as on the raster layer, when the City lists it as removed;
      // the popup says so in words.
      var removed = p.city_status && p.city_status !== "Existing";
      var kind = p.kind ? '<span class="kind ' + p.kind +
        (removed ? " removed" : "") + '" title="' + esc(KINDS[p.kind]) +
        (removed ? " (" + esc(p.city_status.toLowerCase()) + ")" : "") +
        '"></span>' : "";
      return '<tr data-i="' + p._i + '" data-status="' + p.status +
        '" data-kind="' + (p.kind || "osm") +
        '" data-search="' + esc(search) + '">' +
        '<td class="ref">' + kind + esc(label(p)) + "</td>" +
        '<td class="addr" title="' + esc(where(p)) + '">' + esc(where(p)) + "</td>" +
        '<td class="status-' + p.status + '">' + p.status +
        (dist != null ? ' <span class="dist">' + dist + "&nbsp;m</span>" : "") +
        "</td>" +
        '<td><span class="osm-links">' + osmPairHtml(f) + "</span></td></tr>";
    }).join("");

    tbody.addEventListener("click", function (ev) {
      if (ev.target.closest("a")) { return; }  // let OSM links work
      var tr = ev.target.closest("tr");
      if (tr) { select(parseInt(tr.dataset.i, 10), true); }
    });
  }

  // Select a gap: ring it, join it to its OSM feature, fit the map, open its
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
    var kinds = {};
    Array.prototype.forEach.call(
      document.querySelectorAll(".controls input[data-kind]"),
      function (b) { kinds[b.dataset.kind] = b; }
    );
    var filter = document.getElementById("filter");

    function statusOn(status) {
      var b = boxes[status];
      return b ? b.checked : true;
    }

    function kindOn(kind) {
      var b = kinds[kind];
      return b ? b.checked : true;  // OSM-only rows have no City kind
    }

    function apply() {
      var q = filter.value.trim().toLowerCase();

      var rows = document.querySelectorAll("#gap-table tbody tr");
      Array.prototype.forEach.call(rows, function (tr) {
        var hit = statusOn(tr.dataset.status) && kindOn(tr.dataset.kind) &&
          (!q || tr.dataset.search.indexOf(q) > -1);
        tr.style.display = hit ? "" : "none";
        var m = markers[parseInt(tr.dataset.i, 10)];
        if (hit && !map.hasLayer(m)) { map.addLayer(m); }
        else if (!hit && map.hasLayer(m)) { map.removeLayer(m); }
      });
    }

    Object.keys(boxes).concat(Object.keys(kinds)).forEach(function (k) {
      (boxes[k] || kinds[k]).addEventListener("change", apply);
    });
    filter.addEventListener("input", apply);
    apply();

    // O / I / J open the selected gap on openstreetmap.org, in iD or JOSM.
    document.addEventListener("keydown", function (ev) {
      if (ev.ctrlKey || ev.metaKey || ev.altKey) { return; }
      if (/^(input|textarea|select)$/i.test(ev.target.tagName)) { return; }
      var key = ev.key.toLowerCase();
      if (["o", "i", "j"].indexOf(key) < 0) { return; }
      if (selectedIndex == null) { return; }
      var t = osmTargets(features[selectedIndex]);
      ev.preventDefault();
      if (key === "j") {
        window.open(t.josm, "josm");
      } else {
        window.open(key === "o" ? t.osm : t.id, "_blank", "noopener");
      }
    });
  }

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  document.addEventListener("DOMContentLoaded", init);
})();
