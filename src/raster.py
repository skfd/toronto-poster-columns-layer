"""Render hydrant points into raster (PNG) map tiles using Pillow.

Pure Python -- no native dependencies, runs the same on Windows and Linux.

Each hydrant is a small red dot with a white edge, so it reads over imagery
and over OSM's own map. There are no labels: the City's hydrant numbers are
not painted on the hydrants and do not belong in OSM, so a label would only be
something to copy that should not be copied. The dot grows with the zoom, and
at z17 -- the zoom a mapper edits at, overzoomed beyond -- it is big enough to
place a node on.
"""

import json
import os
from collections import defaultdict

from PIL import Image, ImageDraw

from src import config
from src.tilemath import TILE_SIZE, lonlat_to_pixel

DOT_COLOR = (211, 47, 47, 255)         # red, a hydrant's colour in most legends
EDGE_COLOR = (255, 255, 255, 255)

# Dot radius per zoom, in pixels (white edge included).
DOT_RADIUS = {15: 2, 16: 3, 17: 4}


def build_raster(slim_path=None):
    """Render PNG tiles for every zoom in config.RASTER_ZOOMS.

    Returns a dict {zoom: tile_count}.
    """
    slim_path = slim_path or config.SLIM_PATH
    return {z: _render_zoom(slim_path, z) for z in config.RASTER_ZOOMS}


def _render_zoom(slim_path, zoom):
    points = _read_points(slim_path, zoom)
    radius = DOT_RADIUS.get(zoom, DOT_RADIUS[max(DOT_RADIUS)])
    print(f"Raster z{zoom}: {len(points):,} hydrants")

    tiles = defaultdict(list)
    for x, y in points:
        for key in _tiles_touching((x - radius, y - radius, x + radius, y + radius)):
            tiles[key].append((x, y))

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
    """[(x, y), ...] in global pixels at ``zoom``."""
    points = []
    with open(slim_path, encoding="utf-8") as f:
        for line in f:
            lon, lat = json.loads(line)["geometry"]["coordinates"][:2]
            points.append(lonlat_to_pixel(lon, lat, zoom))
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
    for x, y in points:
        x, y = x - ox, y - oy
        draw.ellipse((x - radius, y - radius, x + radius, y + radius),
                     fill=DOT_COLOR, outline=EDGE_COLOR, width=1)
    return img
