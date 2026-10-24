"""Tests for the slim step (run: python tests\\test_slim.py).

Nothing is matched on an ID in this layer, so slim has no key to guard: what
matters is that every point survives, with or without the City's asset number,
and that the identifying fields come through for a reviewer to read.
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import config
import src.slim as slim_mod
from src.slim import slim


def _feature(hydrant_id=1234, location_id="H40-053", model=None, oid=1):
    return {
        "type": "Feature",
        "geometry": {"type": "Point",
                     "coordinates": [-80.26173418027994, 43.573469141377835]},
        "properties": {
            config.OBJECT_ID_KEY: oid,
            config.HYDRANT_ID_KEY: hydrant_id,
            config.LOCATION_ID_KEY: location_id,
            config.MODEL_KEY: model,
            "GlobalID": "{5E26556C-89CE-461A-93EA-BCEB37D67AA1}",
        },
    }


def _slim(features):
    """Run slim over ``features`` in a temp dir; return the kept rows.

    The fixture is far below slim's own MIN_EXPECTED, so that bound is relaxed
    for the duration -- it guards a real extract, not a four-row fixture.
    """
    tmp = tempfile.mkdtemp()
    src_path = os.path.join(tmp, "hydrants-2026-10-09.geojson")
    with open(src_path, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f)

    saved = (config.DATA_DIR, config.SLIM_PATH, config.COUNT_PATH,
             slim_mod.MIN_EXPECTED)
    config.DATA_DIR = tmp
    config.SLIM_PATH = os.path.join(tmp, "hydrants-slim.geojsonl")
    config.COUNT_PATH = os.path.join(tmp, "hydrants.count")
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
    features = [_feature(oid=1, model="Post Hydrant - Series 67"),
                _feature(hydrant_id=None, location_id=None, oid=2)]
    no_geom = _feature(oid=3)
    no_geom["geometry"] = None
    features.append(no_geom)

    kept, count = _slim(features)
    assert count == len(kept) == 2
    assert kept[0]["properties"] == {
        "hydrant_id": 1234, "location_id": "H40-053",
        "model": "Post Hydrant - Series 67", "objectid": 1,
    }, kept[0]["properties"]
    # Seven City rows have no HYDRANTID. They are still hydrants.
    assert kept[1]["properties"] == {"objectid": 2}
    # Rounded to ~0.1 m; the service hands back 14 decimals.
    assert kept[0]["geometry"]["coordinates"] == [-80.261734, 43.573469]
    print("test_slim_keeps_every_point: OK")


def test_slim_refuses_an_implausible_count():
    saved = slim_mod.MAX_EXPECTED
    slim_mod.MAX_EXPECTED = 1
    try:
        _slim([_feature(oid=1), _feature(oid=2)])
    except RuntimeError as e:
        assert "expected range" in str(e)
    else:
        raise AssertionError("an implausible count reached the slim file")
    finally:
        slim_mod.MAX_EXPECTED = saved
    print("test_slim_refuses_an_implausible_count: OK")


if __name__ == "__main__":
    test_slim_keeps_every_point()
    test_slim_refuses_an_implausible_count()
