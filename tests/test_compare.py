"""Unit tests for the OSM comparison: the Overpass fetch, and the matching.

The Overpass half is carried over from the parks sibling, where it pins the
failure that actually happened: on 2026-08-10 and again on 2026-08-17
overpass-api.de answered 504, the single attempt gave up, the run silently
compared against a fortnight-old cache and reported success. The matching half
is this layer's own: by distance alone, nearest pair first, one to one.
"""

import json
import os
import sys

import pytest
import requests
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from addressvault import net  # noqa: E402
from src import compare, config, site  # noqa: E402

# Minutes old, as a healthy instance's reply is; a fixed date would age past
# OSM_MAX_AGE_DAYS and be refused.
OSM_BASE = (datetime.now(timezone.utc) - timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
GOOD = {"osm3s": {"timestamp_osm_base": OSM_BASE},
        "elements": [{"type": "node", "id": i, "lat": 43.5, "lon": -80.2,
                      "tags": {"emergency": "fire_hydrant"}}
                     for i in range(config.OSM_MIN_ELEMENTS + 1)]}


class FakeResponse:
    def __init__(self, payload=None, status=200):
        self.payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Server Error")

    def json(self):
        return self.payload


def _post(by_host):
    """A requests.post that answers per hostname from ``by_host``."""
    calls = []

    def post(url, data=None, headers=None, timeout=None):
        calls.append(url)
        for host, reply in by_host.items():
            if host in url:
                if isinstance(reply, Exception):
                    raise reply
                return reply
        raise requests.ConnectionError("no route")

    post.calls = calls
    return post


@pytest.fixture
def paths(tmp_path, monkeypatch):
    """Point the cache + sidecar at a temp dir, and never really sleep."""
    monkeypatch.setattr(config, "OSM_CACHE_PATH", str(tmp_path / "osm-hydrants.json"))
    monkeypatch.setattr(config, "OSM_FETCH_PATH", str(tmp_path / ".osm-fetch.json"))
    monkeypatch.setattr(compare.time, "sleep", lambda _s: None)
    return tmp_path


def test_a_dead_primary_falls_through_to_the_next_mirror(paths, monkeypatch):
    # The whole point: one sick instance is not an outage.
    monkeypatch.setattr(config, "OVERPASS_URLS",
                        ("https://a.example/api", "https://b.example/api"))
    post = _post({"a.example": FakeResponse(status=504),
                  "b.example": FakeResponse(GOOD)})
    monkeypatch.setattr(compare.requests, "post", post)

    data, _date, from_cache = compare._load_osm()
    assert from_cache is False
    assert len(data["elements"]) == len(GOOD["elements"])
    assert [u.split("/")[2] for u in post.calls] == ["a.example", "b.example"]


def test_the_mirror_list_is_retried_before_giving_up(paths, monkeypatch):
    # A 504 is load shedding, and load sheds. Trying the list once was what
    # turned a transient failure into a fortnight of stale data.
    monkeypatch.setattr(config, "OVERPASS_URLS", ("https://a.example/api",))
    monkeypatch.setattr(config, "OVERPASS_ROUNDS", 3)
    replies = [FakeResponse(status=504), FakeResponse(status=504),
               FakeResponse(GOOD)]

    def post(url, data=None, headers=None, timeout=None):
        return replies.pop(0)

    monkeypatch.setattr(compare.requests, "post", post)
    _data, _date, from_cache = compare._load_osm()
    assert from_cache is False
    assert replies == [], "every round should have been used"


def test_an_implausibly_small_reply_is_not_accepted(paths, monkeypatch):
    # overpass.osm.ch serves a Switzerland extract and answers a Guelph bbox
    # with HTTP 200 and zero elements. Believing it would report every City
    # hydrant as missing from OSM -- 3,537 fictional gaps.
    monkeypatch.setattr(config, "OVERPASS_URLS",
                        ("https://regional.example/api", "https://good.example/api"))
    post = _post({"regional.example": FakeResponse({"elements": []}),
                  "good.example": FakeResponse(GOOD)})
    monkeypatch.setattr(compare.requests, "post", post)

    data, _date, from_cache = compare._load_osm()
    assert from_cache is False
    assert len(data["elements"]) == len(GOOD["elements"])


def test_a_reply_from_months_old_data_is_not_accepted(paths, monkeypatch):
    # overpass.private.coffee answered the Toronto sibling on 2026-09-29 in
    # full, with OSM as of 2026-05-06; its page showed May as this week. It
    # did the same with Guelph's hydrants on 2026-10-09 (OSM of 2026-05-31).
    monkeypatch.setattr(config, "OVERPASS_URLS",
                        ("https://lagging.example/api", "https://good.example/api"))
    stale = {**GOOD, "osm3s": {"timestamp_osm_base": "2026-05-06T03:25:00Z"}}
    post = _post({"lagging.example": FakeResponse(stale),
                  "good.example": FakeResponse(GOOD)})
    monkeypatch.setattr(compare.requests, "post", post)

    _data, osm_date, from_cache = compare._load_osm()
    assert from_cache is False
    assert osm_date.startswith(OSM_BASE[:10])
    assert [u.split("/")[2] for u in post.calls] == ["lagging.example", "good.example"]


def test_a_good_fetch_records_when_and_where_it_came_from(paths, monkeypatch):
    monkeypatch.setattr(config, "OVERPASS_URLS", ("https://good.example/api",))
    monkeypatch.setattr(compare.requests, "post",
                        _post({"good.example": FakeResponse(GOOD)}))

    _data, osm_date, _from_cache = compare._load_osm()
    with open(config.OSM_FETCH_PATH, encoding="utf-8") as f:
        sidecar = json.load(f)
    # The date the page prints is the OSM database timestamp the mirror states
    # about its own reply, NOT the day the fetch happened: a mirror can answer
    # in two seconds with data from last week, and "today" would hide that.
    assert osm_date == f"{OSM_BASE[:10]} {OSM_BASE[11:16]}Z"
    assert sidecar["mirror"] == "good.example"
    assert sidecar["timestamp_osm_base"] == OSM_BASE
    assert sidecar["osm_base"] == osm_date


def test_the_cache_is_used_only_after_every_mirror_fails(paths, monkeypatch):
    with open(config.OSM_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(GOOD, f)
    with open(config.OSM_FETCH_PATH, "w", encoding="utf-8") as f:
        json.dump({"fetched": "2026-08-03", "mirror": "old.example"}, f)

    monkeypatch.setattr(config, "OVERPASS_URLS",
                        ("https://a.example/api", "https://b.example/api"))
    monkeypatch.setattr(config, "OVERPASS_ROUNDS", 2)
    post = _post({"a.example": FakeResponse(status=504),
                  "b.example": FakeResponse(status=504)})
    monkeypatch.setattr(compare.requests, "post", post)
    monkeypatch.setattr(net, "wait_for_link", lambda wait=True: None)

    _data, fetched, from_cache = compare._load_osm()
    assert len(post.calls) == 4, "both mirrors, both rounds"
    # The date carried out is the cache's own, not today's -- that value is what
    # the gap page prints, and printing today's would be the original lie.
    assert (fetched, from_cache) == ("2026-08-03", True)


def test_with_no_cache_and_no_mirror_the_run_is_told_to_fail(paths, monkeypatch):
    monkeypatch.setattr(config, "OVERPASS_URLS", ("https://a.example/api",))
    monkeypatch.setattr(config, "OVERPASS_ROUNDS", 1)
    monkeypatch.setattr(compare.requests, "post",
                        _post({"a.example": FakeResponse(status=504)}))
    monkeypatch.setattr(net, "wait_for_link", lambda wait=True: None)

    with pytest.raises(compare.OsmUnavailable):
        compare._load_osm()


def test_being_offline_is_not_reported_as_an_overpass_outage(paths, monkeypatch):
    # No link means the fetch never happened; that is a 75 elsewhere in the
    # pipeline, not a broken Overpass, and it must not be confused with one.
    with open(config.OSM_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(GOOD, f)
    monkeypatch.setattr(config, "OVERPASS_URLS", ("https://a.example/api",))
    monkeypatch.setattr(config, "OVERPASS_ROUNDS", 1)
    monkeypatch.setattr(compare.requests, "post",
                        _post({"a.example": requests.ConnectionError("offline")}))

    def no_link(wait=True):
        raise net.LinkUnavailable("no usable link")

    monkeypatch.setattr(net, "wait_for_link", no_link)
    _data, _fetched, from_cache = compare._load_osm()
    assert from_cache is True


def test_a_mirror_without_an_osm3s_block_still_dates_the_page(paths, monkeypatch):
    monkeypatch.setattr(config, "OVERPASS_URLS", ("https://terse.example/api",))
    terse = {"elements": GOOD["elements"]}
    monkeypatch.setattr(compare.requests, "post",
                        _post({"terse.example": FakeResponse(terse)}))
    _data, osm_date, _from_cache = compare._load_osm()
    assert osm_date.startswith("20")


def test_the_cache_date_falls_back_to_the_file_mtime(paths, monkeypatch):
    # A cache written before the sidecar existed still has to date itself.
    with open(config.OSM_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(GOOD, f)
    os.utime(config.OSM_CACHE_PATH, (1754247600, 1754247600))  # 2026-08-03 local
    assert compare._cache_date().startswith("20")


# --- what the reader sees ---------------------------------------------------

def test_a_stale_comparison_says_so_on_the_page():
    note = site._osm_note({"osm_stale": True, "osm_date": "2026-08-03"})
    assert "2026-08-03" in note and "class=\"stale\"" in note


def test_a_fresh_comparison_adds_nothing():
    assert site._osm_note({"osm_stale": False, "osm_date": "2026-08-17"}) == ""


# --- matching ---------------------------------------------------------------
#
# Positions are built as metre offsets from one City hydrant, so each test
# reads as the street layout it describes.

BASE_LAT, BASE_LON = 43.5448, -80.2482
TAGGED = {"fire_hydrant:type": "pillar", "colour": "yellow",
          "fire_hydrant:position": "green"}


def _at(north_m=0.0, east_m=0.0):
    lat = BASE_LAT + north_m / 111_195
    lon = BASE_LON + east_m / (111_195 * 0.7248)  # cos(43.54 deg)
    return lat, lon


def _city(hid, north_m=0, east_m=0):
    lat, lon = _at(north_m, east_m)
    return {"hydrant_id": hid, "location_id": f"H40-{hid:03d}",
            "objectid": hid, "lat": lat, "lon": lon}


def _node(oid, north_m=0, east_m=0, **tags):
    lat, lon = _at(north_m, east_m)
    return {"type": "node", "id": oid, "lat": lat, "lon": lon,
            "tags": {"emergency": "fire_hydrant", **tags}}


def _tagged(oid, north_m=0, east_m=0):
    return _node(oid, north_m, east_m, **TAGGED)


def _run(city, elements):
    gaps, counts = compare._match(city, compare._osm_hydrants({"elements": elements}))
    return {(g["properties"]["hydrant_id"] or g["properties"]["osm_url"],
             g["properties"]["status"]) for g in gaps}, counts, gaps


def test_a_tagged_hydrant_beside_the_citys_is_not_a_gap():
    gaps, counts, _ = _run([_city(1)], [_tagged(1, 1.4)])
    assert gaps == set()
    assert counts["matched"] == 1
    assert sum(counts[s] for s in compare.STATUSES) == 0


def test_no_osm_hydrant_nearby_is_missing():
    gaps, counts, _ = _run([_city(1)], [_tagged(1, north_m=500)])
    assert (1, "missing") in gaps and counts["missing"] == 1


def test_between_near_m_and_far_m_is_far():
    gaps, _counts, rows = _run([_city(1)], [_tagged(1, north_m=config.NEAR_M + 5)])
    assert gaps == {(1, "far")}
    assert rows[0]["properties"]["distance_m"] == pytest.approx(config.NEAR_M + 5, abs=0.2)


def test_beyond_far_m_the_city_hydrant_is_missing_and_the_osm_one_osm_only():
    # The City layer is municipal hydrants only; an OSM hydrant nowhere near
    # one is most likely on private land, not wrong.
    gaps, counts, rows = _run([_city(1)], [_tagged(7, north_m=config.FAR_M + 30)])
    assert gaps == {(1, "missing"), ("https://www.openstreetmap.org/node/7", "osm_only")}
    only = [r for r in rows if r["properties"]["status"] == "osm_only"][0]
    assert only["properties"]["nearest_city_m"] == config.FAR_M + 30
    assert counts["osm_only"] == 1


def test_nearest_pair_first_keeps_one_osm_hydrant_from_answering_for_two():
    # Two City hydrants 8 m apart (a corner, both sides); one OSM hydrant 2 m
    # from the first. Within NEAR_M of both, it is only the first's.
    gaps, counts, _ = _run([_city(1), _city(2, east_m=8)], [_tagged(1, east_m=-2)])
    assert gaps == {(2, "missing")}
    assert counts["matched"] == 1


def test_nearest_pair_first_is_not_city_order_first():
    # City 1 is scanned first, and OSM a (4 m from it) is its nearest. But a
    # is 2 m from City 2, and OSM b is 7 m from City 1 and 13 m from City 2.
    # Pairing in City order gives City 1 a and leaves City 2 "far"; nearest
    # pair first matches both.
    gaps, counts, _ = _run([_city(1), _city(2, east_m=6)],
                           [_tagged(1, east_m=4), _tagged(2, east_m=-7)])
    assert gaps == set()
    assert counts["matched"] == 2


def test_a_second_osm_hydrant_beside_a_matched_one_is_a_duplicate():
    # Seen on 2026-10-09: a node 11 m from a City hydrant a nearer node took.
    gaps, counts, rows = _run([_city(1)], [_tagged(1, 1), _tagged(2, north_m=11)])
    assert gaps == {(1, "duplicate")}
    assert rows[0]["properties"]["other_url"].endswith("/node/2")
    assert rows[0]["properties"]["other_distance_m"] == 11
    assert counts["duplicate"] == 1 and counts["osm_only"] == 0


def test_tag_gaps_are_one_row_each_counted_on_its_own():
    gaps, counts, rows = _run([_city(1), _city(2, north_m=200)],
                              [_node(1, 1, colour="yellow"),
                               _node(2, 201, **{"fire_hydrant:type": "pillar",
                                                "colour": "red"})])
    assert gaps == {(1, "notype"), (2, "noposition")}
    lacks = {r["properties"]["hydrant_id"]: r["properties"]["lacks"] for r in rows}
    assert lacks == {1: ["notype", "noposition"], 2: ["noposition"]}
    assert (counts["notype"], counts["nocolour"], counts["noposition"]) == (1, 0, 2)


def test_a_far_hydrants_tags_are_not_checked():
    # Which hydrant it is is the open question; its tags can wait.
    gaps, counts, _ = _run([_city(1)], [_node(1, north_m=20)])
    assert gaps == {(1, "far")}
    assert counts["notype"] == counts["noposition"] == 0


def test_every_osm_hydrant_is_accounted_for():
    # Matched, far, duplicate or osm_only: none falls between the statuses.
    city = [_city(1), _city(2, north_m=100), _city(3, north_m=200)]
    osm = [_tagged(1, 1), _tagged(2, 0.5), _tagged(3, 115), _tagged(4, 400),
           _tagged(5, 203)]
    _gaps, counts, _ = _run(city, osm)
    assert counts["matched"] + counts["far"] + counts["duplicate"] + \
        counts["osm_only"] == len(osm)


def test_ways_are_placed_at_their_center():
    hydrants = compare._osm_hydrants({"elements": [
        {"type": "way", "id": 7, "center": {"lat": 43.5, "lon": -80.2},
         "tags": {"emergency": "fire_hydrant", "colour": "red", "ref": "9"}},
        {"type": "relation", "id": 8, "tags": {}},   # no position: skipped
    ]})
    assert [(h["otype"], h["lat"], h["lon"], h["tags"]) for h in hydrants] == \
        [("way", 43.5, -80.2, {"colour": "red"})]


def test_the_query_asks_for_every_hydrant_with_a_position():
    q = compare._overpass_query()
    assert 'nwr["emergency"="fire_hydrant"]' in q
    assert q.rstrip().endswith("out center tags;")
