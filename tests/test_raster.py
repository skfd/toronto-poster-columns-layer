"""Tests for the raster dots (run: python tests\\test_raster.py)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import config
from src.raster import DOT_COLOR, DOT_RADIUS, _render_tile, _tiles_touching
from src.tilemath import TILE_SIZE


def test_every_raster_zoom_has_a_dot_size():
    assert set(config.RASTER_ZOOMS) <= set(DOT_RADIUS)
    # Readable at the editing zoom: wider than a hairline, smaller than a house.
    assert DOT_RADIUS[max(config.RASTER_ZOOMS)] >= 4
    print("test_every_raster_zoom_has_a_dot_size: OK")


def test_a_dot_on_a_seam_is_drawn_on_both_tiles():
    x, y, r = TILE_SIZE, 100, DOT_RADIUS[17]
    tiles = set(_tiles_touching((x - r, y - r, x + r, y + r)))
    assert {(0, 0), (1, 0)} <= tiles
    left = _render_tile(0, 0, [(x, y)], r)
    right = _render_tile(1, 0, [(x, y)], r)
    assert left.getpixel((TILE_SIZE - 2, y)) == DOT_COLOR
    assert right.getpixel((1, y)) == DOT_COLOR
    print("test_a_dot_on_a_seam_is_drawn_on_both_tiles: OK")


def test_a_tile_is_transparent_away_from_the_dots():
    img = _render_tile(0, 0, [(50, 50)], DOT_RADIUS[17])
    assert img.getpixel((50, 50)) == DOT_COLOR
    assert img.getpixel((200, 200))[3] == 0
    print("test_a_tile_is_transparent_away_from_the_dots: OK")


if __name__ == "__main__":
    test_every_raster_zoom_has_a_dot_size()
    test_a_dot_on_a_seam_is_drawn_on_both_tiles()
    test_a_tile_is_transparent_away_from_the_dots()
