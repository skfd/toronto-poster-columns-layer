"""Unit tests for the OSM comparison: the Overpass fetch, and the matching.

The Overpass half is carried over from the parks sibling, where it pins the
failure that actually happened: on 2026-08-10 and again on 2026-08-17
overpass-api.de answered 504, the single attempt gave up, the run silently
compared against a fortnight-old cache and reported success. The matching half
is the hydrants sibling's -- by distance alone, nearest pair first, one to one
-- with this layer's own twist: two OSM tagging families answer for a City
point, and only the postering-type ones are reported when nothing pairs with
them.
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
        "elements": [{"type": "node", "id": i, "lat": 43.65, "lon": -79.39,
                      "tags": {"advertising": "board"}}
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
    monkeypatch.setattr(config, "OSM_CACHE_PATH", str(tmp_path / "osm-posters.json"))
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
    # overpass.osm.ch serves a Switzerland extract and answers a bbox outside
    # it with HTTP 200 and zero elements (it did so to the Guelph sibling).
    # Believing it here would report every City point as missing from OSM --
    # 2,496 fictional gaps.
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
# Positions are built as metre offsets from one City column downtown, so each
# test reads as the street layout it describes.

BASE_LAT, BASE_LON = config.TORONTO_CENTER          # 43.6510, -79.3960
COLUMN = {"advertising": "column"}
# The other family: a notice board drawn as an information board.
BOARD = {"tourism": "information", "information": "board",
         "board_type": "notice"}


def _at(north_m=0.0, east_m=0.0):
    lat = BASE_LAT + north_m / 111_195
    lon = BASE_LON + east_m / (111_195 * 0.7234)  # cos(43.65 deg)
    return lat, lon


def _city(cid, north_m=0, east_m=0, kind="column"):
    lat, lon = _at(north_m, east_m)
    return {"id": cid, "kind": kind, "city_status": "Existing",
            "address": "100 Queen St W", "lat": lat, "lon": lon}


def _node(oid, north_m=0, east_m=0, **tags):
    """An OSM node; a poster column unless ``tags`` say otherwise."""
    lat, lon = _at(north_m, east_m)
    return {"type": "node", "id": oid, "lat": lat, "lon": lon,
            "tags": tags or dict(COLUMN)}


def _run(city, elements):
    gaps, counts = compare._match(city, compare._osm_features({"elements": elements}))
    return {(g["properties"]["id"] or g["properties"]["osm_url"],
             g["properties"]["status"]) for g in gaps}, counts, gaps


def test_an_osm_column_beside_the_citys_is_not_a_gap():
    gaps, counts, _ = _run([_city("PO-1")], [_node(1, 1.4)])
    assert gaps == set()
    assert counts["matched"] == 1
    assert sum(counts[s] for s in compare.STATUSES) == 0


def test_either_tagging_family_answers_for_a_city_point():
    # The brief accepts both, and the checker does not nag about which: an
    # advertising=board on one corner, a notice board on the next.
    gaps, counts, _ = _run([_city("PO-1"), _city("PO-2", north_m=200)],
                           [_node(1, 1, advertising="board"),
                            _node(2, 201, **BOARD)])
    assert gaps == set()
    assert counts["matched"] == 2


def test_advertising_no_is_not_accepted():
    # advertising=no says there is none here -- the opposite of an answer.
    assert compare._osm_features({"elements": [_node(1, advertising="no")]}) == []
    gaps, counts, _ = _run([_city("PO-1")], [_node(1, 1, advertising="no")])
    assert gaps == {("PO-1", "missing")} and counts["missing"] == 1


def test_no_osm_feature_nearby_is_missing():
    gaps, counts, _ = _run([_city("PO-1")], [_node(1, north_m=500)])
    assert ("PO-1", "missing") in gaps and counts["missing"] == 1


def test_between_near_m_and_far_m_is_far():
    gaps, _counts, rows = _run([_city("PO-1")], [_node(1, north_m=config.NEAR_M + 5)])
    assert gaps == {("PO-1", "far")}
    props = rows[0]["properties"]
    assert props["distance_m"] == pytest.approx(config.NEAR_M + 5, abs=0.2)
    # The row names the City point and says what it was paired with.
    assert {k: props[k] for k in ("id", "kind", "city_status", "address")} == \
        {"id": "PO-1", "kind": "column", "city_status": "Existing",
         "address": "100 Queen St W"}
    assert props["osm_tags"] == COLUMN


def test_beyond_far_m_the_city_point_is_missing_and_the_osm_one_osm_only():
    # The City's lists are its own street furniture; a column-like OSM feature
    # nowhere near one is most likely a private board, not wrong.
    gaps, counts, rows = _run([_city("PO-1")], [_node(7, north_m=config.FAR_M + 30)])
    assert gaps == {("PO-1", "missing"),
                    ("https://www.openstreetmap.org/node/7", "osm_only")}
    only = [r for r in rows if r["properties"]["status"] == "osm_only"][0]
    assert only["properties"]["nearest_city_m"] == config.FAR_M + 30
    assert counts["osm_only"] == 1


def test_nearest_pair_first_keeps_one_osm_feature_from_answering_for_two():
    # Two City columns 8 m apart (a corner, both sides); one OSM column 2 m
    # from the first. Within NEAR_M of both, it is only the first's.
    gaps, counts, _ = _run([_city("PO-1"), _city("PO-2", east_m=8)],
                           [_node(1, east_m=-2)])
    assert gaps == {("PO-2", "missing")}
    assert counts["matched"] == 1


def test_nearest_pair_first_is_not_city_order_first():
    # City 1 is scanned first, and OSM a (4 m from it) is its nearest. But a
    # is 2 m from City 2, and OSM b is 7 m from City 1 and 13 m from City 2.
    # Pairing in City order gives City 1 a and leaves City 2 "far"; nearest
    # pair first matches both.
    gaps, counts, _ = _run([_city("PO-1"), _city("PO-2", east_m=6)],
                           [_node(1, east_m=4), _node(2, east_m=-7)])
    assert gaps == set()
    assert counts["matched"] == 2


def test_a_second_osm_column_beside_a_matched_one_is_a_duplicate():
    gaps, counts, rows = _run([_city("PO-1")], [_node(1, 1), _node(2, north_m=11)])
    assert gaps == {("PO-1", "duplicate")}
    assert rows[0]["properties"]["other_url"].endswith("/node/2")
    assert rows[0]["properties"]["other_distance_m"] == 11
    assert counts["duplicate"] == 1 and counts["osm_only"] == 0


def test_a_far_point_with_a_duplicate_is_counted_once():
    # Duplicate wins the row, and the header counts rows: on the first run a
    # shelter board 23 m from one board and 26 m from another was counted as
    # both far and duplicate, so the header summed to one more than the table.
    gaps, counts, _ = _run([_city("SH-1", kind="shelter_board")],
                           [_node(1, north_m=23), _node(2, north_m=-26)])
    assert gaps == {("SH-1", "duplicate")}
    assert (counts["far"], counts["duplicate"]) == (0, 1)
    assert counts["by_kind"]["shelter_board"]["far"] == 0


def test_an_unpaired_billboard_is_neither_duplicate_nor_osm_only():
    # Toronto has hundreds of billboards and history plaques. One beside a
    # column already answered for, or one in the middle of nowhere, is just
    # something else; listing them would bury the handful worth a look.
    gaps, counts, _ = _run(
        [_city("PO-1")],
        [_node(1, 1),
         _node(2, north_m=11, advertising="billboard"),
         _node(3, north_m=500, advertising="billboard"),
         _node(4, north_m=-500, tourism="information", information="board")])
    assert gaps == set()
    assert counts["duplicate"] == counts["osm_only"] == 0
    assert counts["matched"] == 1


def test_a_billboard_does_answer_for_a_city_point():
    # Any advertising=* answers when it pairs: on a shelter that is most
    # likely the shelter's own ad panel. The row names the tag, so a reviewer
    # can tell.
    gaps, counts, rows = _run(
        [_city("SH-1", kind="shelter_board"),
         _city("SH-2", north_m=200, kind="shelter_board")],
        [_node(1, 3, advertising="billboard"),
         _node(2, 220, advertising="billboard")])
    assert gaps == {("SH-2", "far")}
    assert counts["matched"] == 1 and counts["missing"] == 0
    assert rows[0]["properties"]["osm_tags"] == {"advertising": "billboard"}


def test_by_kind_splits_the_counts_per_city_kind():
    city = [_city("PO-1"), _city("PO-2", north_m=200),
            _city("SH-3", north_m=400, kind="shelter_board"),
            _city("SH-4", north_m=600, kind="shelter_board")]
    osm = [_node(1, 1),                        # PO-1 matched
           _node(3, 420),                      # SH-3 far
           _node(4, 601), _node(5, 612),       # SH-4 matched, and a duplicate
           _node(9, 2000)]                     # osm_only: no City kind
    _gaps, counts, _ = _run(city, osm)
    assert counts["by_kind"] == {
        "column": {"city": 2, "missing": 1, "far": 0, "duplicate": 0,
                   "matched": 1},
        "shelter_board": {"city": 2, "missing": 0, "far": 1, "duplicate": 1,
                          "matched": 1},
    }
    for key in ("missing", "far", "duplicate", "matched"):
        assert counts[key] == sum(k[key] for k in counts["by_kind"].values())
    assert counts["osm_only"] == 1


def test_every_postering_osm_feature_is_accounted_for():
    # Matched, far, duplicate or osm_only: no column or notice board falls
    # between the statuses. (An unpaired billboard does, on purpose.)
    city = [_city("PO-1"), _city("PO-2", north_m=100), _city("PO-3", north_m=200)]
    postering = [_node(1, 1), _node(2, 0.5), _node(3, 115), _node(4, 400),
                 _node(5, 203, **BOARD)]
    billboard = [_node(6, 800, advertising="billboard")]
    _gaps, counts, _ = _run(city, postering + billboard)
    assert counts["matched"] + counts["far"] + counts["duplicate"] + \
        counts["osm_only"] == len(postering)


def test_ways_are_placed_at_their_center():
    features = compare._osm_features({"elements": [
        {"type": "way", "id": 7, "center": {"lat": 43.65, "lon": -79.39},
         "tags": {"advertising": "column", "operator": "Astral", "ref": "9"}},
        {"type": "relation", "id": 8, "tags": dict(COLUMN)},  # no position
        {"type": "node", "id": 9, "lat": 43.65, "lon": -79.39,
         "tags": {"amenity": "bench"}},                       # not accepted
    ]})
    assert [(f["otype"], f["lat"], f["lon"], f["tags"], f["postering"])
            for f in features] == \
        [("way", 43.65, -79.39, {"advertising": "column", "operator": "Astral"},
          True)]


def test_the_query_asks_for_both_families_with_a_position():
    q = compare._overpass_query()
    s, w, n, e = config.TORONTO_BBOX
    bbox = f"({s},{w},{n},{e})"
    assert f'nwr["advertising"]{bbox}' in q
    assert f'nwr["tourism"="information"]["information"="board"]{bbox}' in q
    assert f'nwr["board_type"="notice"]{bbox}' in q
    assert q.rstrip().endswith("out center tags;")
