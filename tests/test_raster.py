"""Tests for the raster dots (run: python tests\\test_raster.py)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import config
from src.raster import DOT_RADIUS, KIND_COLORS, _render_tile, _tiles_touching
from src.tilemath import TILE_SIZE

COLUMN = KIND_COLORS["column"]


def test_every_raster_zoom_has_a_dot_size():
    assert set(config.RASTER_ZOOMS) <= set(DOT_RADIUS)
    # Readable at the editing zoom: wider than a hairline, smaller than a house.
    assert DOT_RADIUS[max(config.RASTER_ZOOMS)] >= 4
    print("test_every_raster_zoom_has_a_dot_size: OK")


def test_every_kind_has_a_colour():
    assert set(KIND_COLORS) == set(config.SOURCES)
    print("test_every_kind_has_a_colour: OK")


def test_a_dot_on_a_seam_is_drawn_on_both_tiles():
    x, y, r = TILE_SIZE, 100, DOT_RADIUS[17]
    tiles = set(_tiles_touching((x - r, y - r, x + r, y + r)))
    assert {(0, 0), (1, 0)} <= tiles
    left = _render_tile(0, 0, [(x, y, "column", False)], r)
    right = _render_tile(1, 0, [(x, y, "column", False)], r)
    assert left.getpixel((TILE_SIZE - 2, y)) == COLUMN
    assert right.getpixel((1, y)) == COLUMN
    print("test_a_dot_on_a_seam_is_drawn_on_both_tiles: OK")


def test_a_tile_is_transparent_away_from_the_dots():
    img = _render_tile(0, 0, [(50, 50, "column", False)], DOT_RADIUS[17])
    assert img.getpixel((50, 50)) == COLUMN
    assert img.getpixel((200, 200))[3] == 0
    print("test_a_tile_is_transparent_away_from_the_dots: OK")


def test_a_shelter_board_gets_its_own_colour():
    img = _render_tile(0, 0, [(50, 50, "shelter_board", False)], DOT_RADIUS[17])
    assert img.getpixel((50, 50)) == KIND_COLORS["shelter_board"]
    assert KIND_COLORS["shelter_board"] != COLUMN
    print("test_a_shelter_board_gets_its_own_colour: OK")


def test_columns_are_round_and_shelter_boards_square():
    # Shape, not only colour, tells the kinds apart: the corner of the
    # marker's box is filled for a square and left empty by a circle.
    r = DOT_RADIUS[17]
    corner = (50 + r - 1, 50 + r - 1)
    board = _render_tile(0, 0, [(50, 50, "shelter_board", False)], r)
    column = _render_tile(0, 0, [(50, 50, "column", False)], r)
    assert board.getpixel(corner)[3] == 255
    assert column.getpixel(corner)[3] == 0
    print("test_columns_are_round_and_shelter_boards_square: OK")


def test_a_removed_point_is_a_ring():
    # "Temporarily Removed": the City says it belongs here, but a mapper may
    # find nothing. Hollow in the middle, coloured round the edge.
    r = DOT_RADIUS[17]
    img = _render_tile(0, 0, [(50, 50, "column", True)], r)
    assert img.getpixel((50, 50))[3] == 0
    ring = [img.getpixel((50 + dx, 50)) for dx in range(-r, r + 1)]
    assert COLUMN in ring, ring
    print("test_a_removed_point_is_a_ring: OK")


if __name__ == "__main__":
    test_every_raster_zoom_has_a_dot_size()
    test_every_kind_has_a_colour()
    test_a_dot_on_a_seam_is_drawn_on_both_tiles()
    test_a_tile_is_transparent_away_from_the_dots()
    test_a_shelter_board_gets_its_own_colour()
    test_columns_are_round_and_shelter_boards_square()
    test_a_removed_point_is_a_ring()
