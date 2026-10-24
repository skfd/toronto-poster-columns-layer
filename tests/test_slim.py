"""Tests for the slim step (run: python tests\\test_slim.py).

Nothing is matched on an ID in this layer, so slim has no key to guard: what
matters is that every point survives, with or without the City's asset number,
and that the identifying fields come through for a reviewer to read. The input
is download's merged file: the two CKAN datasets' features, each carrying the
``kind`` download injected, each point a one-point MultiPoint.
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import config
import src.slim as slim_mod
from src.slim import slim

LON, LAT = -79.39612345678901, 43.65098765432101   # the City hands back 12+ decimals


def _feature(kind="column", fid="PO-00022", status="Existing", **extra):
    """A merged feature as download writes it; ``extra`` overrides properties."""
    props = {
        "kind": kind,
        "_id": 1,
        config.ID_KEY: fid,
        config.SITE_ID_KEY: "S-1022",
        config.ASSET_TYPE_KEY: "PPC" if kind == "column" else "Astral 4-panel",
        config.STATUS_KEYS.get(kind, "STATUS"): status,
        config.FRONTING_KEY: "Queen St W",
        config.FROM_KEY: "John St",
        "ADDRESSNUMBERTEXT": "100",
        "ADDRESSSTREET": "Queen St W",
        "BARCODE": "000123",
    }
    props.update(extra)
    return {
        "type": "Feature",
        "geometry": {"type": "MultiPoint", "coordinates": [[LON, LAT]]},
        "properties": props,
    }


def _slim(features):
    """Run slim over ``features`` in a temp dir; return the kept rows.

    The fixture is far below slim's own MIN_EXPECTED, so that bound is relaxed
    for the duration -- it guards a real extract, not a four-row fixture.
    """
    tmp = tempfile.mkdtemp()
    src_path = os.path.join(tmp, "posters-2026-10-24.geojson")
    with open(src_path, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f)

    saved = (config.DATA_DIR, config.SLIM_PATH, config.COUNT_PATH,
             slim_mod.MIN_EXPECTED)
    config.DATA_DIR = tmp
    config.SLIM_PATH = os.path.join(tmp, "posters-slim.geojsonl")
    config.COUNT_PATH = os.path.join(tmp, "posters.count")
    slim_mod.MIN_EXPECTED = 1
    try:
        slim(src_path)
        with open(config.SLIM_PATH, encoding="utf-8") as f:
            kept = [json.loads(line) for line in f]
        with open(config.COUNT_PATH, encoding="utf-8") as f:
            count = int(f.read())
    finally:
        (config.DATA_DIR, config.SLIM_PATH, config.COUNT_PATH,
         slim_mod.MIN_EXPECTED) = saved
    return kept, count


def test_slim_keeps_every_point():
    column = _feature()
    removed = _feature(fid="PO-00023", status="Temporarily Removed")
    as_point = _feature(fid="PO-00024")
    as_point["geometry"] = {"type": "Point", "coordinates": [LON, LAT]}
    bare = _feature(fid=None, **{config.SITE_ID_KEY: None})
    no_geom = _feature(fid="PO-00025")
    no_geom["geometry"] = None

    kept, count = _slim([column, removed, as_point, bare, no_geom])
    assert count == len(kept) == 4
    assert kept[0]["properties"] == {
        "kind": "column", "id": "PO-00022", "site_id": "S-1022",
        "asset_type": "PPC", "city_status": "Existing",
        "fronting": "Queen St W", "from_street": "John St",
        "address": "100 Queen St W",
    }, kept[0]["properties"]
    # No status filter: a temporarily removed column is still the City's.
    assert kept[1]["properties"]["city_status"] == "Temporarily Removed"
    # A plain Point is as good as a one-point MultiPoint.
    assert kept[2]["properties"]["id"] == "PO-00024"
    # A row without the City's asset numbers is still a postering spot.
    assert "id" not in kept[3]["properties"]
    assert "site_id" not in kept[3]["properties"]
    # Written as a Point, rounded to ~0.1 m.
    assert kept[0]["geometry"] == {"type": "Point",
                                   "coordinates": [-79.396123, 43.650988]}
    print("test_slim_keeps_every_point: OK")


def test_the_citys_none_is_blank():
    # The City writes the string "None" where it has nothing; carried through,
    # it would read as a street called None on the gap page.
    kept, _count = _slim([_feature(**{config.FROM_KEY: "None",
                                      "ADDRESSNUMBERTEXT": "None",
                                      config.SITE_ID_KEY: " None "})])
    props = kept[0]["properties"]
    assert "from_street" not in props and "site_id" not in props
    assert props["address"] == "Queen St W"
    print("test_the_citys_none_is_blank: OK")


def test_a_shelter_board_takes_its_own_status():
    # On a shelter board, STATUS is the shelter's; the board's is
    # POSTERBOARDSTATUS, and that is the one a mapper needs.
    board = _feature(kind="shelter_board", fid="SH-03579",
                     status="Temporarily Removed", STATUS="Existing")
    kept, _count = _slim([board])
    assert kept[0]["properties"]["kind"] == "shelter_board"
    assert kept[0]["properties"]["city_status"] == "Temporarily Removed"
    print("test_a_shelter_board_takes_its_own_status: OK")


def test_unknown_kinds_and_multi_points_are_skipped():
    no_kind = _feature(fid="PO-1")
    del no_kind["properties"]["kind"]
    odd_kind = _feature(kind="bench", fid="PO-2")
    multi = _feature(fid="PO-3")
    multi["geometry"]["coordinates"] = [[LON, LAT], [LON + 0.001, LAT]]
    kept, count = _slim([no_kind, odd_kind, multi, _feature(fid="PO-4")])
    assert count == 1
    assert [k["properties"]["id"] for k in kept] == ["PO-4"]
    print("test_unknown_kinds_and_multi_points_are_skipped: OK")


def test_slim_refuses_an_implausible_count():
    saved = slim_mod.MAX_EXPECTED
    slim_mod.MAX_EXPECTED = 1
    try:
        _slim([_feature(fid="PO-1"), _feature(fid="PO-2")])
    except RuntimeError as e:
        assert "expected range" in str(e)
    else:
        raise AssertionError("an implausible count reached the slim file")
    finally:
        slim_mod.MAX_EXPECTED = saved
    print("test_slim_refuses_an_implausible_count: OK")


if __name__ == "__main__":
    test_slim_keeps_every_point()
    test_the_citys_none_is_blank()
    test_a_shelter_board_takes_its_own_status()
    test_unknown_kinds_and_multi_points_are_skipped()
    test_slim_refuses_an_implausible_count()
