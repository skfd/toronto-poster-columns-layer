"""Render the GitHub Pages landing page into the build output."""

import json
import math
import os
import re
import shutil
from datetime import date
from html import escape as html_escape
from urllib.parse import quote

from PIL import Image

from src import chunks, compare, config, history

# Screenshots shown on the landing page, copied from the project root when
# present (they are added manually after the first publish).
SCREENSHOTS = ["iD.png", "JOSM.png"]
SCREENSHOT_MAX_WIDTH = 1500


def build_site():
    """Render index.html, copy assets and screenshots into build/site/."""
    os.makedirs(config.SITE_DIR, exist_ok=True)

    point_count = "2,400+"
    if os.path.isfile(config.COUNT_PATH):
        with open(config.COUNT_PATH, encoding="utf-8") as f:
            point_count = f"{int(f.read().strip()):,}"
    kind_counts = _kind_counts()

    build_date = date.today().isoformat()

    with open(os.path.join(config.ASSETS_DIR, "index.html.tmpl"),
              encoding="utf-8") as f:
        html = f.read()

    replacements = {
        "{{PAGES_URL}}": config.PAGES_URL,
        "{{VECTOR_URL}}": f"{config.PAGES_URL}/tiles/vector/{{z}}/{{x}}/{{y}}.pbf",
        "{{RASTER_URL}}": f"{config.PAGES_URL}/tiles/raster/{{z}}/{{x}}/{{y}}.png",
        "{{RASTER_URL_JOSM}}": (
            f"{config.PAGES_URL}/tiles/raster/{{zoom}}/{{x}}/{{y}}.png"
        ),
        "{{VECTOR_URL_JOSM}}": (
            f"{config.PAGES_URL}/tiles/vector/{{zoom}}/{{x}}/{{y}}.pbf"
        ),
        "{{BUILD_DATE}}": build_date,
        "{{DATA_DATE}}": _data_date(build_date),
        "{{POINT_COUNT}}": point_count,
        "{{COLUMN_COUNT}}": kind_counts.get("column", "830+"),
        "{{BOARD_COUNT}}": kind_counts.get("shelter_board", "1,600+"),
        "{{GITHUB_REPO}}": config.GITHUB_REPO,
        "{{COLUMN_DATASET}}": config.DATASET_PAGES["column"],
        "{{BOARD_DATASET}}": config.DATASET_PAGES["shelter_board"],
        "{{LICENSE_URL}}": config.LICENSE_URL,
        "{{LICENSE_NOTICE}}": config.LICENSE_NOTICE,
    }
    for key, value in replacements.items():
        html = html.replace(key, value)

    with open(os.path.join(config.SITE_DIR, "index.html"), "w",
              encoding="utf-8") as f:
        f.write(html)
    for name in ("index.css", "index.js"):
        shutil.copy(
            os.path.join(config.ASSETS_DIR, name),
            os.path.join(config.SITE_DIR, name),
        )
    for name in SCREENSHOTS:
        src = os.path.join(config.PROJECT_DIR, name)
        if os.path.isfile(src):
            _copy_image(src, os.path.join(config.SITE_DIR, name),
                        SCREENSHOT_MAX_WIDTH)
    _build_gaps_page(build_date)
    # .nojekyll stops GitHub Pages running Jekyll over the tile directories.
    open(os.path.join(config.SITE_DIR, ".nojekyll"), "w").close()
    print(f"Site rendered: {config.SITE_DIR}")


def _build_gaps_page(build_date):
    """Render gaps/ (map + table) when a comparison has produced gaps.geojson."""
    if not os.path.isfile(config.GAPS_GEOJSON_PATH):
        print("  (no gaps.geojson -- run 'compare'; skipping gap page)")
        return

    gaps_dir = os.path.join(config.SITE_DIR, "gaps")
    os.makedirs(gaps_dir, exist_ok=True)

    summary = {}
    if os.path.isfile(config.GAPS_COUNT_PATH):
        with open(config.GAPS_COUNT_PATH, encoding="utf-8") as f:
            summary = json.load(f)

    with open(os.path.join(config.ASSETS_DIR, "gaps.html.tmpl"),
              encoding="utf-8") as f:
        html = f.read()
    replacements = {
        "{{PAGES_URL}}": config.PAGES_URL,
        "{{BUILD_DATE}}": build_date,
        "{{DATA_DATE}}": _data_date(build_date),
        **{f"{{{{{k.upper()}_COUNT}}}}": f"{summary.get(k, 0):,}"
           for k in compare.STATUSES},
        **_by_kind_keys(summary),
        "{{CITY_COUNT}}": f"{summary.get('city', 0):,}",
        "{{OSM_COUNT}}": f"{summary.get('osm_features', 0):,}",
        "{{MATCHED_COUNT}}": f"{summary.get('matched', 0):,}",
        "{{NEAR_M}}": str(config.NEAR_M),
        "{{FAR_M}}": str(config.FAR_M),
        "{{OSM_DATE}}": summary.get("osm_date", build_date),
        "{{OSM_NOTE}}": _osm_note(summary),
        "{{GITHUB_REPO}}": config.GITHUB_REPO,
        # The gap page is published separately from the landing page and is
        # often the only page a mapper opens, so it carries the City licence
        # notice in its own right. Both pages must show it: publishing these
        # tiles is a redistribution, and the notice is the licence condition
        # attached to that, not a footer nicety.
        "{{LICENSE_URL}}": config.LICENSE_URL,
        "{{LICENSE_NOTICE}}": config.LICENSE_NOTICE,
        "{{COLUMN_DATASET}}": config.DATASET_PAGES["column"],
        "{{BOARD_DATASET}}": config.DATASET_PAGES["shelter_board"],
    }
    for key, value in replacements.items():
        html = html.replace(key, value)

    with open(os.path.join(gaps_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    shutil.copy(config.GAPS_GEOJSON_PATH, os.path.join(gaps_dir, "gaps.geojson"))
    for name in ("gaps.css", "gaps.js"):
        shutil.copy(os.path.join(config.ASSETS_DIR, name),
                    os.path.join(gaps_dir, name))
    print(f"Gap page rendered: {gaps_dir}")
    _build_history_page(gaps_dir, build_date)
    _build_import_page(build_date, summary)


def _build_import_page(build_date, summary):
    """Render import/: the missing points cut into chunks, a .osm file and
    JOSM links per chunk, and chunks.geojson with every point's chunk."""
    with open(config.GAPS_GEOJSON_PATH, encoding="utf-8") as f:
        features = json.load(f)["features"]
    import_dir = os.path.join(config.SITE_DIR, "import")
    os.makedirs(import_dir, exist_ok=True)

    rows, points, nodes = [], [], {}
    for kind, prefix in (("column", "C"), ("shelter_board", "B")):
        groups = chunks.split(chunks.import_rows(features)[kind],
                              config.IMPORT_MAX_PER_CHUNK)
        nodes[kind] = sum(len(g) for g in groups)
        for n, group in enumerate(groups, 1):
            name = f"{prefix}{n}"
            filename = f"chunk-{name.lower()}.osm"
            with open(os.path.join(import_dir, filename), "w",
                      encoding="utf-8") as f:
                f.write(chunks.osm_xml(group, kind))
            rows.append(_import_row(name, kind, n, len(groups), group, filename))
            for g in group:
                points.append({"type": "Feature", "geometry": g["geometry"],
                               "properties": {"chunk": name, "kind": kind}})

    removed = sum(1 for f in features
                  if f["properties"].get("status") == "missing"
                  and f["properties"].get("city_status") != "Existing")
    with open(os.path.join(import_dir, "chunks.geojson"), "w",
              encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": points}, f)

    with open(os.path.join(config.ASSETS_DIR, "import.html.tmpl"),
              encoding="utf-8") as f:
        html = f.read()
    replacements = {
        "{{BUILD_DATE}}": build_date,
        "{{DATA_DATE}}": _data_date(build_date),
        "{{OSM_DATE}}": summary.get("osm_date", build_date),
        "{{OSM_NOTE}}": _osm_note(summary),
        "{{CHUNK_COUNT}}": str(len(rows)),
        "{{NODE_COUNT}}": f"{sum(nodes.values()):,}",
        "{{COLUMN_NODES}}": f"{nodes['column']:,}",
        "{{BOARD_NODES}}": f"{nodes['shelter_board']:,}",
        "{{REMOVED_COUNT}}": f"{removed:,}",
        "{{MAX_PER_CHUNK}}": str(config.IMPORT_MAX_PER_CHUNK),
        "{{FAR_M}}": str(config.FAR_M),
        "{{COLUMN_TAGS}}": _tag_list(config.IMPORT_TAGS["column"]),
        "{{BOARD_TAGS}}": _tag_list(config.IMPORT_TAGS["shelter_board"]),
        "{{CHANGESET_TAGS}}": _tag_list(
            {"comment": config.IMPORT_COMMENT.format(
                what="poster columns", name="C1", total="N"),
             **config.IMPORT_CHANGESET_TAGS}),
        "{{CHUNK_ROWS}}": "\n".join(rows),
        "{{GITHUB_REPO}}": config.GITHUB_REPO,
        # The .osm files are the City's data, republished: the notice goes
        # with them, as on every other page.
        "{{LICENSE_URL}}": config.LICENSE_URL,
        "{{LICENSE_NOTICE}}": config.LICENSE_NOTICE,
        "{{COLUMN_DATASET}}": config.DATASET_PAGES["column"],
        "{{BOARD_DATASET}}": config.DATASET_PAGES["shelter_board"],
    }
    for key, value in replacements.items():
        html = html.replace(key, value)
    with open(os.path.join(import_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    shutil.copy(os.path.join(config.ASSETS_DIR, "import.js"),
                os.path.join(import_dir, "import.js"))
    print(f"Import page rendered: {len(rows)} chunks, "
          f"{sum(nodes.values()):,} nodes")


JOSM = "http://127.0.0.1:8111"
# Existing OSM around a chunk, for its reviewer: what the gap check counts as
# a postering spot, plus shelters, where a shelter board goes. Only these, not
# everything: a chunk spans kilometres, and the OSM API refuses a bbox download
# over 50,000 nodes, which downtown Toronto reaches in a few hundred metres.
CONTEXT_QUERY = (
    '[out:xml][timeout:120][bbox:{s},{w},{n},{e}];'
    '(nwr["advertising"];nwr["tourism"="information"]["information"="board"];'
    'nwr["board_type"="notice"];nwr["amenity"="shelter"];nwr["shelter"="yes"];);'
    'out meta;>;out meta qt;'
)
KIND_WORDS = {"column": "poster columns", "shelter_board": "shelter poster boards"}


def _import_row(name, kind, n, total, group, filename):
    """One chunk's table row: its size and its JOSM links."""
    s, w, n_, e = chunks.bbox(group)
    width = (e - w) * 111.32 * math.cos(math.radians(s))
    height = (n_ - s) * 111.32
    osm_url = f"{config.PAGES_URL}/import/{filename}"
    tags = {"comment": config.IMPORT_COMMENT.format(
        what=KIND_WORDS[kind], name=name, total=total),
        **config.IMPORT_CHANGESET_TAGS}
    # JOSM URL-decodes the url parameter once and takes everything after
    # "&url=" as it, so it goes last and is quoted whole: the Overpass query
    # inside it is quoted twice.
    load = (f"{JOSM}/import?new_layer=true"
            f"&layer_name={quote(f'Toronto posters {name}', safe='')}"
            f"&changeset_tags={quote('|'.join(f'{k}={v}' for k, v in tags.items()), safe='')}"
            f"&url={quote(osm_url, safe='')}")
    pad_lat = config.FAR_M / 111320
    pad_lon = pad_lat / math.cos(math.radians(s))
    query = CONTEXT_QUERY.format(s=f"{s - pad_lat:.6f}", w=f"{w - pad_lon:.6f}",
                                 n=f"{n_ + pad_lat:.6f}", e=f"{e + pad_lon:.6f}")
    overpass = f"{config.OVERPASS_URLS[0]}?data={quote(query, safe='')}"
    context = f"{JOSM}/import?new_layer=false&url={quote(overpass, safe='')}"
    return (
        f'<tr data-chunk="{name}" data-kind="{kind}">'
        f'<td class="ref"><span class="kind {kind}"></span>{name}</td>'
        f'<td class="num">{len(group)}</td>'
        f'<td class="num">{width:.1f}&nbsp;&times;&nbsp;{height:.1f}&nbsp;km</td>'
        f'<td class="osm-links">'
        f'<a href="{html_escape(load)}" class="josm" target="josm" '
        f'title="Load the chunk into a new JOSM layer, changeset tags set">1&nbsp;load</a> &middot; '
        f'<a href="{html_escape(context)}" class="josm" target="josm" '
        f'title="Add existing OSM boards, advertising and shelters around it, from Overpass">2&nbsp;context</a> &middot; '
        f'<a href="{filename}" download title="The chunk as an .osm file">.osm</a>'
        f"</td></tr>"
    )


def _tag_list(tags):
    return "".join(f"<code>{html_escape(k)}={html_escape(v)}</code><br>"
                   for k, v in tags.items())


def _build_history_page(gaps_dir, build_date):
    """Render gaps/history.html: every recorded run's gap counts, charted.

    The rows are inlined into the page (the chart needs no second request) and
    published beside it as history.jsonl, which is both the raw data for anyone
    who wants it and what re-seeds a checkout without a history file.
    """
    rows = history.load()
    with open(os.path.join(config.ASSETS_DIR, "history.html.tmpl"),
              encoding="utf-8") as f:
        html = f.read()
    replacements = {
        "{{PAGES_URL}}": config.PAGES_URL,
        "{{BUILD_DATE}}": build_date,
        "{{GITHUB_REPO}}": config.GITHUB_REPO,
        "{{RUN_COUNT}}": f"{len(rows):,}",
        "{{FIRST_DATE}}": rows[0]["date"] if rows else build_date,
        "{{HISTORY_JSON}}": json.dumps(rows),
        "{{HISTORY_ROWS}}": "\n".join(_history_row(r) for r in reversed(rows)),
        # Only counts, but counts of the City's points, and like the gap page
        # this can be the one page a reader opens: it carries the notice too.
        "{{LICENSE_URL}}": config.LICENSE_URL,
        "{{LICENSE_NOTICE}}": config.LICENSE_NOTICE,
    }
    for key, value in replacements.items():
        html = html.replace(key, value)
    with open(os.path.join(gaps_dir, "history.html"), "w", encoding="utf-8") as f:
        f.write(html)
    shutil.copy(os.path.join(config.ASSETS_DIR, "history.js"),
                os.path.join(gaps_dir, "history.js"))
    if os.path.isfile(config.HISTORY_PATH):
        shutil.copy(config.HISTORY_PATH, os.path.join(gaps_dir, "history.jsonl"))
    print(f"History page rendered: {len(rows):,} runs")


def _history_row(r):
    source = "reconstructed" if r.get("source") == "attic" else "live"
    cells = [r["date"]] + [f"{r.get(k, 0):,}" for k in history.FIELDS] + [source]
    return "<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"


def _osm_note(summary):
    """Warn on the page itself when the OSM half of the diff is not current.

    The gap list is only worth acting on if both sides are fresh, and the OSM
    side is the one that moves daily. A page dated today whose OSM data is two
    weeks old sends a mapper to add a board somebody else already added.
    """
    if not summary.get("osm_stale"):
        return ""
    when = summary.get("osm_date", "an earlier run")
    return (
        '<p class="stale">Overpass could not be reached for this build, so '
        f'these gaps were computed against OSM data from <strong>{when}</strong>. '
        'Anything mapped since then still shows as a gap.</p>'
    )


def _kind_counts():
    """{kind: "1,234"} from the slim file, for the landing page."""
    counts = {}
    if os.path.isfile(config.SLIM_PATH):
        with open(config.SLIM_PATH, encoding="utf-8") as f:
            for line in f:
                kind = json.loads(line)["properties"].get("kind")
                counts[kind] = counts.get(kind, 0) + 1
    return {k: f"{n:,}" for k, n in counts.items()}


def _by_kind_keys(summary):
    """{{COLUMN_MISSING}}-style placeholders: each kind's share of a count."""
    prefixes = {"column": "COLUMN", "shelter_board": "BOARD"}
    out = {}
    for kind, prefix in prefixes.items():
        row = (summary.get("by_kind") or {}).get(kind) or {}
        for key in ("city", "missing", "far", "duplicate", "matched"):
            out[f"{{{{{prefix}_{key.upper()}}}}}"] = f"{row.get(key, 0):,}"
    return out


def _data_date(fallback):
    """Return the City data's date (YYYY-MM-DD) from the download sidecar."""
    if os.path.isfile(config.LAST_DOWNLOAD_PATH):
        with open(config.LAST_DOWNLOAD_PATH, encoding="utf-8") as f:
            sidecar = json.load(f)
        match = re.search(r"\d{4}-\d{2}-\d{2}", sidecar.get("filename", ""))
        if match:
            return match.group(0)
    return fallback


def _copy_image(src, dst, max_width):
    """Copy an image into the site, downscaling it if wider than max_width."""
    with Image.open(src) as img:
        if img.width > max_width:
            height = round(img.height * max_width / img.width)
            resized = img.resize((max_width, height), Image.LANCZOS)
            resized.save(dst, optimize=True)
            print(f"  {os.path.basename(src)}: {img.width}px -> {max_width}px")
        else:
            shutil.copy(src, dst)
