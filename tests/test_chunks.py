"""Import chunks: which gap rows go in, how they are cut, what a .osm holds.

The properties that matter: every point lands in exactly one chunk, no chunk
is over the cap and there are as few chunks as the cap allows, the cut is
the same for the same input, and no City asset number reaches a node tag.
"""

import math
import os
import random
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import chunks, config  # noqa: E402


def point(i, lon, lat, status="missing", kind="column", city_status="Existing"):
    return {"type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {"id": f"PO-{i:05d}", "kind": kind, "status": status,
                           "city_status": city_status}}


def scatter(n, seed=1):
    rnd = random.Random(seed)
    return [point(i, -79.6 + rnd.random() * 0.4, 43.6 + rnd.random() * 0.2)
            for i in range(n)]


def test_only_existing_missing_points_are_imported():
    rows = chunks.import_rows([
        point(1, -79.4, 43.65),
        point(2, -79.4, 43.65, status="far"),
        point(3, -79.4, 43.65, status="duplicate"),
        point(4, -79.4, 43.65, city_status="Temporarily Removed"),
        point(5, -79.4, 43.65, kind="shelter_board"),
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [0, 0]},
         "properties": {"status": "osm_only"}},
    ])
    assert [f["properties"]["id"] for f in rows["column"]] == ["PO-00001"]
    assert [f["properties"]["id"] for f in rows["shelter_board"]] == ["PO-00005"]


def test_every_point_lands_in_exactly_one_chunk_and_none_is_over_the_cap():
    features = scatter(1593)
    groups = chunks.split(features, 250)
    assert len(groups) == math.ceil(1593 / 250)
    assert all(len(g) <= 250 for g in groups)
    ids = [f["properties"]["id"] for g in groups for f in g]
    assert sorted(ids) == sorted(f["properties"]["id"] for f in features)


def test_chunks_are_near_equal_rather_than_one_full_and_a_remainder():
    sizes = [len(g) for g in chunks.split(scatter(496), 250)]
    assert sizes == [248, 248]


def test_chunk_boxes_do_not_overlap():
    boxes = [chunks.bbox(g) for g in chunks.split(scatter(1000), 150)]
    for i, (s1, w1, n1, e1) in enumerate(boxes):
        for s2, w2, n2, e2 in boxes[i + 1:]:
            assert n1 < s2 or n2 < s1 or e1 < w2 or e2 < w1


def test_the_cut_does_not_depend_on_input_order():
    features = scatter(700)
    shuffled = features[:]
    random.Random(7).shuffle(shuffled)
    ids = lambda gs: [[f["properties"]["id"] for f in g] for g in gs]  # noqa: E731
    assert ids(chunks.split(features, 200)) == ids(chunks.split(shuffled, 200))


def test_no_points_no_chunks():
    assert chunks.split([], 250) == []


def test_osm_file_has_new_nodes_with_the_import_tags_and_no_city_ids():
    root = ET.fromstring(chunks.osm_xml(scatter(3), "column"))
    nodes = root.findall("node")
    assert [n.get("id") for n in nodes] == ["-1", "-2", "-3"]
    for n in nodes:
        tags = {t.get("k"): t.get("v") for t in n.findall("tag")}
        assert tags == config.IMPORT_TAGS["column"]
        assert "ref" not in tags
    assert "PO-" not in chunks.osm_xml(scatter(3), "column")
