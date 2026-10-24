"""Render the postering spots into raster (PNG) map tiles using Pillow.

Pure Python -- no native dependencies, runs the same on Windows and Linux.

One dot per City point, coloured by ``kind``: orange for a poster column, blue
for a board on a transit shelter. Each dot has a white edge, so it reads over
imagery and over OSM's own map. A point the City lists as "Temporarily
Removed" is drawn as a ring rather than a dot: the City says it belongs there,
but a mapper standing at the spot may well find nothing. There are no labels:
the City's asset numbers are not on the structures and do not belong in OSM,
so a label would only be something to copy that should not be copied. The dot
grows with the zoom, and at z17 -- the zoom a mapper edits at, overzoomed
beyond -- it is big enough to place a node on.
"""

import json
import os
from collections import defaultdict

from PIL import Image, ImageDraw

from src import config
from src.tilemath import TILE_SIZE, lonlat_to_pixel

KIND_COLORS = {
    "column": (232, 89, 12, 255),          # orange
    "shelter_board": (28, 126, 214, 255),  # blue
}
EDGE_COLOR = (255, 255, 255, 255)
# Columns are drawn last, on top: they are the layer's main subject, and a
# column and a shelter a few metres apart should not hide the column.
DRAW_ORDER = ("shelter_board", "column")
REMOVED = "Temporarily Removed"

# Dot radius per zoom, in pixels (white edge included).
DOT_RADIUS = {15: 2, 16: 3, 17: 5}


def build_raster(slim_path=None):
    """Render PNG tiles for every zoom in config.RASTER_ZOOMS.

    Returns a dict {zoom: tile_count}.
    """
    slim_path = slim_path or config.SLIM_PATH
    return {z: _render_zoom(slim_path, z) for z in config.RASTER_ZOOMS}


def _render_zoom(slim_path, zoom):
    points = _read_points(slim_path, zoom)
    radius = DOT_RADIUS.get(zoom, DOT_RADIUS[max(DOT_RADIUS)])
    print(f"Raster z{zoom}: {len(points):,} points")

    tiles = defaultdict(list)
    for p in points:
        x, y = p[0], p[1]
        for key in _tiles_touching((x - radius, y - radius, x + radius, y + radius)):
            tiles[key].append(p)

    out_dir = os.path.join(config.RASTER_TILE_DIR, str(zoom))
    made_dirs = set()
    written = 0
    for (tx, ty), pts in tiles.items():
        img = _render_tile(tx, ty, pts, radius)
        if img.getbbox() is None:
            continue
        tdir = os.path.join(out_dir, str(tx))
        if tdir not in made_dirs:
            os.makedirs(tdir, exist_ok=True)
            made_dirs.add(tdir)
        img.save(os.path.join(tdir, f"{ty}.png"), optimize=True)
        written += 1
    return written


def _read_points(slim_path, zoom):
    """[(x, y, kind, removed), ...] in global pixels at ``zoom``, in draw order."""
    points = []
    with open(slim_path, encoding="utf-8") as f:
        for line in f:
            feat = json.loads(line)
            props = feat.get("properties") or {}
            lon, lat = feat["geometry"]["coordinates"][:2]
            x, y = lonlat_to_pixel(lon, lat, zoom)
            points.append((x, y, props.get("kind"),
                           props.get("city_status") == REMOVED))
    order = {k: i for i, k in enumerate(DRAW_ORDER)}
    points.sort(key=lambda p: order.get(p[2], -1))
    return points


def _tiles_touching(bbox, pad=1):
    x0, y0, x1, y1 = bbox
    for tx in range(int((x0 - pad) // TILE_SIZE), int((x1 + pad) // TILE_SIZE) + 1):
        for ty in range(int((y0 - pad) // TILE_SIZE), int((y1 + pad) // TILE_SIZE) + 1):
            yield (tx, ty)


def _render_tile(tx, ty, points, radius):
    img = Image.new("RGBA", (TILE_SIZE, TILE_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    ox, oy = tx * TILE_SIZE, ty * TILE_SIZE
    for x, y, kind, removed in points:
        x, y = x - ox, y - oy
        color = KIND_COLORS.get(kind, KIND_COLORS["column"])
        box = (x - radius, y - radius, x + radius, y + radius)
        if removed:
            # A ring: white halo, then the colour, hollow in the middle.
            draw.ellipse(box, fill=None, outline=EDGE_COLOR, width=1)
            inner = (box[0] + 1, box[1] + 1, box[2] - 1, box[3] - 1)
            draw.ellipse(inner, fill=None, outline=color, width=max(1, radius // 2))
        else:
            draw.ellipse(box, fill=color, outline=EDGE_COLOR, width=1)
    return img
