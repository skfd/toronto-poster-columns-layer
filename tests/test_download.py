"""Unit tests for the download link gate, the CKAN lookup, and the file checks.

Carried over from the hydrants sibling: the link gate, the retry, and the
hash cache. What this layer changes is the source. It is two CKAN packages,
and each is asked for its resource list before anything is fetched, so the
resource that gets fetched is chosen by this code, not hard-coded -- which
makes choosing the wrong one a real failure. A CKAN package lists more than
one GeoJSON: the WGS84 file, a 2952 (MTM) projection of it, and a datastore
dump whose *format* says GeoJSON too. And CKAN, like ArcGIS, answers a failed
action with a 200 and a ``success: false`` body.

The floors are monkeypatched down to a handful of rows: what is under test is
that a short file stops the run, not that the real floors are 750 and 1,500.
"""

import json
import os
import sys
from urllib.parse import parse_qs, urlparse

import pytest
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from addressvault import net  # noqa: E402
from src import config, download as dl  # noqa: E402

COLUMNS = "street-furniture-poster-structure"
BOARDS = "street-furniture-poster-board"
FILES = "https://example.invalid/files"


def _feature(fid, **props):
    return {"type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-79.39, 43.65]},
            "properties": {config.ID_KEY: fid, **props}}


def _collection(features):
    return {"type": "FeatureCollection", "features": features}


def _resources(package, last_modified="2026-03-01T09:00:00.000000"):
    """The resource list a Toronto package carries: the datastore dump (format
    GeoJSON, but not the file), the WGS84 file, and the MTM projection."""
    return [
        {"name": package, "format": "GeoJSON", "datastore_active": True,
         "url": f"{FILES}/{package}/datastore-dump.geojson",
         "last_modified": "2026-10-01T00:00:00.000000"},
        {"name": f"{package} - 4326.geojson", "format": "GeoJSON",
         "datastore_active": False,
         "url": f"{FILES}/{package}/4326.geojson",
         "last_modified": last_modified},
        {"name": f"{package} - 2952.geojson", "format": "GeoJSON",
         "datastore_active": False,
         "url": f"{FILES}/{package}/2952.geojson",
         "last_modified": "2026-10-01T00:00:00.000000"},
    ]


class FakeResponse:
    def __init__(self, body, status_code=200):
        self.content = body
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Server Error")


def _ckan(packages=None, files=None):
    """A requests.get that answers like the City's CKAN.

    ``packages`` maps package name -> its resource list (package_show's
    ``result.resources``); ``files`` maps a resource URL -> the document it
    serves. Defaults: both packages with the standard three resources, two
    columns and two shelter boards in the 4326 files. The dump and the 2952
    file serve a decoy row, so a test reading the output can tell which file
    was taken. Anything not listed is a 404.
    """
    if packages is None:
        packages = {COLUMNS: _resources(COLUMNS), BOARDS: _resources(BOARDS)}
    if files is None:
        files = {}
        for package, resources in packages.items():
            for r in resources:
                files[r["url"]] = _collection([_feature(f"DECOY-{r['url']}")])
        files[f"{FILES}/{COLUMNS}/4326.geojson"] = _collection(
            [_feature("PO-00001", STATUS="Existing"),
             _feature("PO-00002", STATUS="Existing")])
        files[f"{FILES}/{BOARDS}/4326.geojson"] = _collection(
            [_feature("SH-00001", POSTERBOARDSTATUS="Existing"),
             _feature("SH-00002", POSTERBOARDSTATUS="Temporarily Removed")])
    calls = []

    def get(url, headers=None, timeout=None):
        calls.append(url)
        if url.startswith(f"{config.CKAN_API}/package_show"):
            package = parse_qs(urlparse(url).query)["id"][0]
            if package not in packages:
                return FakeResponse(json.dumps({
                    "success": False,
                    "error": {"message": "Not found", "__type": "Not Found Error"},
                }).encode())
            return FakeResponse(json.dumps({
                "success": True,
                "result": {"name": package, "resources": packages[package]},
            }).encode())
        if url in files:
            return FakeResponse(json.dumps(files[url]).encode())
        return FakeResponse(b"Not Found", status_code=404)

    get.calls = calls
    return get


@pytest.fixture(autouse=True)
def no_wait(monkeypatch):
    monkeypatch.setattr(dl, "RETRY_WAIT", 0)


@pytest.fixture(autouse=True)
def usable_link(monkeypatch):
    """Leave the gate open by default; the tests that care close it."""
    monkeypatch.setattr("addressvault.net.wait_for_link", lambda **k: None)


@pytest.fixture(autouse=True)
def small_floors(monkeypatch):
    """The real packages, floors of two rows: a fixture of 1,500 boards would
    test nothing a fixture of two does not."""
    monkeypatch.setattr(config, "SOURCES", {
        "column": (COLUMNS, 2),
        "shelter_board": (BOARDS, 2),
    })


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        config, "LAST_DOWNLOAD_PATH", str(tmp_path / ".last-download.json")
    )
    return tmp_path


def offline_gate(monkeypatch):
    monkeypatch.setattr(
        "addressvault.net.wait_for_link",
        lambda **k: (_ for _ in ()).throw(net.Offline("link is offline")),
    )


def _written(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)["features"]


def test_a_dead_link_stops_before_any_request(data_dir, monkeypatch):
    # The whole point of the gate: on a weekly trigger, finding out now costs a
    # second, and finding out at the end of a 600 s read costs the slot.
    def boom(*a, **k):
        raise AssertionError("made a request on a dead link")

    offline_gate(monkeypatch)
    monkeypatch.setattr("src.download.requests.get", boom)

    with pytest.raises(net.Offline):
        dl.download()


def test_a_dropped_request_is_retried(data_dir, monkeypatch):
    ckan = _ckan()
    state = {"n": 0}

    def get(url, headers=None, timeout=None):
        state["n"] += 1
        if state["n"] == 2:
            raise requests.ConnectionError("connection dropped")
        return ckan(url)

    monkeypatch.setattr("src.download.requests.get", get)
    status, path = dl.download()
    assert status == "DOWNLOADED"
    # package_show, a dropped file, the file again, then the second package's
    # package_show and file.
    assert state["n"] == 5
    assert os.path.basename(path).startswith("posters-")
    assert len(_written(path)) == 4


def test_out_of_retries_on_a_dead_link_raises_link_unavailable(data_dir, monkeypatch):
    # The retry budget buys ~90 s, nowhere near long enough to outlast an
    # outage. On exhaustion the run must exit 75, not log a build failure
    # against a service that was never reachable.
    monkeypatch.setattr(dl, "RETRIES", 1)
    state = {"n": 0}

    def get(url, headers=None, timeout=None):
        state["n"] += 1
        raise requests.ConnectionError("getaddrinfo failed")

    monkeypatch.setattr("src.download.requests.get", get)
    offline_gate(monkeypatch)

    with pytest.raises(net.Offline):
        dl._fetch(f"{config.CKAN_API}/package_show?id={COLUMNS}")
    assert state["n"] == 2  # the initial attempt plus RETRIES


def test_a_ckan_error_is_not_written_as_data(data_dir, monkeypatch):
    # CKAN can answer a failed action with HTTP 200 and success: false, so
    # raise_for_status proves nothing and the body has to be read. A package
    # renamed by the City is exactly this: the lookup "succeeds" and says no.
    monkeypatch.setattr("src.download.requests.get",
                        _ckan(packages={BOARDS: _resources(BOARDS)}))
    with pytest.raises(RuntimeError, match="CKAN returned an error"):
        dl.download()
    assert not list(data_dir.glob("posters-*.geojson"))


def test_the_geojson_is_picked_by_name_not_format(data_dir, monkeypatch):
    # Three resources per package say format GeoJSON. The datastore dump is a
    # CSV-shaped export and the 2952 file is in metres, not degrees -- either
    # one would be drawn somewhere off the coast of Africa, or not at all.
    ckan = _ckan()
    monkeypatch.setattr("src.download.requests.get", ckan)
    _status, path = dl.download()

    fetched = [u for u in ckan.calls if u.startswith(FILES)]
    assert fetched == [f"{FILES}/{COLUMNS}/4326.geojson",
                       f"{FILES}/{BOARDS}/4326.geojson"]
    ids = [f["properties"][config.ID_KEY] for f in _written(path)]
    assert not [i for i in ids if i.startswith("DECOY")]


@pytest.mark.parametrize("resources, found", [
    # No WGS84 file at all: only the dump and the MTM projection.
    ([r for r in _resources(COLUMNS) if not r["name"].endswith("4326.geojson")], 0),
    # A 4326 name on a datastore resource is still the dump, not the file.
    ([{**r, "datastore_active": True} for r in _resources(COLUMNS)], 0),
    # Two WGS84 files: the City added one, and guessing is not this code's job.
    (_resources(COLUMNS) + [{"name": f"{COLUMNS} (2027) - 4326.geojson",
                             "format": "GeoJSON", "datastore_active": False,
                             "url": f"{FILES}/{COLUMNS}/4326-2027.geojson"}], 2),
])
def test_zero_or_two_matching_resources_raises(data_dir, monkeypatch, resources, found):
    # Either way the package changed shape, and a human should look before a
    # file is chosen for them. The message lists what was there.
    monkeypatch.setattr("src.download.requests.get", _ckan(
        packages={COLUMNS: resources, BOARDS: _resources(BOARDS)}))
    with pytest.raises(RuntimeError, match=f"found {found} among"):
        dl.download()
    assert not list(data_dir.glob("posters-*.geojson"))


def test_a_file_under_its_floor_stops_the_run(data_dir, monkeypatch):
    # A partial file is the dangerous failure: the structures that fell off the
    # end would be reported to mappers as missing from OSM. The columns pass
    # here and the boards fall short -- half a layer is not written either.
    monkeypatch.setattr(config, "SOURCES", {
        "column": (COLUMNS, 2),
        "shelter_board": (BOARDS, 3),
    })
    monkeypatch.setattr("src.download.requests.get", _ckan())
    with pytest.raises(RuntimeError, match="under the floor of 3"):
        dl.download()
    assert not list(data_dir.glob("posters-*.geojson"))
    assert not os.path.exists(config.LAST_DOWNLOAD_PATH)


def test_a_repeated_id_stops_the_run(data_dir, monkeypatch):
    # A repeated ID is a file stitched together wrongly (or a page served
    # twice), and its row count would pass the floor while the layer double
    # counted. Not trusting it.
    files = {f"{FILES}/{COLUMNS}/4326.geojson": _collection(
                 [_feature("PO-00001"), _feature("PO-00001")]),
             f"{FILES}/{BOARDS}/4326.geojson": _collection(
                 [_feature("SH-00001"), _feature("SH-00002")])}
    monkeypatch.setattr("src.download.requests.get", _ckan(files=files))
    with pytest.raises(RuntimeError, match=f"repeats an {config.ID_KEY}"):
        dl.download()
    assert not list(data_dir.glob("posters-*.geojson"))


def test_every_feature_carries_its_kind_and_both_are_merged(data_dir, monkeypatch):
    # The two datasets share an ID key and most property names; once merged,
    # ``kind`` is the only thing that says which is which -- the style, the
    # status key (STATUS vs POSTERBOARDSTATUS) and the gap page all read it.
    monkeypatch.setattr("src.download.requests.get", _ckan())
    _status, path = dl.download()
    features = _written(path)
    assert [(f["properties"][config.ID_KEY], f["properties"]["kind"])
            for f in features] == [("PO-00001", "column"),
                                   ("PO-00002", "column"),
                                   ("SH-00001", "shelter_board"),
                                   ("SH-00002", "shelter_board")]
    # Stamping kind adds a property; it does not replace the City's.
    assert features[3]["properties"]["POSTERBOARDSTATUS"] == "Temporarily Removed"


def test_the_file_is_dated_by_the_newest_resource(data_dir, monkeypatch):
    # DATA_DATE means "when the City last published", not "when the build last
    # ran". The newer of the two WGS84 files wins -- not the dump's or the 2952
    # file's date, which are later still and say nothing about this data.
    monkeypatch.setattr("src.download.requests.get", _ckan(packages={
        COLUMNS: _resources(COLUMNS, last_modified="2026-04-17T08:15:02.123456"),
        BOARDS: _resources(BOARDS, last_modified="2026-02-03T11:00:00.000000"),
    }))
    _status, path = dl.download()
    assert os.path.basename(path) == "posters-2026-04-17.geojson"


def test_an_unchanged_extract_skips_the_write(data_dir, monkeypatch):
    # The cache key is the body hash, not last_modified: CKAN bumps a
    # resource's timestamp on a republish that changes nothing, and that is not
    # a reason to rebuild every tile.
    monkeypatch.setattr("src.download.requests.get", _ckan())
    first_status, first_path = dl.download()
    assert first_status == "DOWNLOADED"

    second_status, second_path = dl.download()
    assert (second_status, second_path) == ("SKIPPED", first_path)
    assert len(list(data_dir.glob("posters-*.geojson"))) == 1


def test_a_changed_extract_is_written(data_dir, monkeypatch):
    monkeypatch.setattr("src.download.requests.get", _ckan())
    dl.download()

    files = {f"{FILES}/{COLUMNS}/4326.geojson": _collection(
                 [_feature("PO-00001"), _feature("PO-00002"), _feature("PO-00003")]),
             f"{FILES}/{BOARDS}/4326.geojson": _collection(
                 [_feature("SH-00001"), _feature("SH-00002")])}
    monkeypatch.setattr("src.download.requests.get", _ckan(files=files))
    status, path = dl.download()
    assert status == "DOWNLOADED"
    assert len(_written(path)) == 5
