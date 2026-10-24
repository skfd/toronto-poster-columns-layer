"""Unit tests for the download link gate, the paging, and the ArcGIS checks.

Carried over from the bus stops sibling, plus what this layer adds: the
Hydrants layer is three and a half times the service's maxRecordCount, so the
download pages through it, and the pages have to add up to the service's own
count. An ArcGIS service lies with a 200: it answers an error, and a truncated
page, with the same status code as a good extract.
"""

import json
import os
import re
import sys

import pytest
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from addressvault import net  # noqa: E402
from src import config, download as dl  # noqa: E402


def _feature(i):
    return {"type": "Feature",
            "geometry": {"type": "Point", "coordinates": [0, 0]},
            "properties": {"OBJECTID": i + 1}}


class FakeResponse:
    def __init__(self, body, status_code=200):
        self.content = body
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Server Error")


def _service(n=2500, count=None, page_size=1000):
    """A requests.get that answers like the FeatureServer: a count query, and
    pages of at most ``page_size`` by resultOffset, the GeoJSON way (the
    truncation flag in ``properties``)."""
    rows = [_feature(i) for i in range(n)]
    calls = []

    def get(url, headers=None, timeout=None):
        calls.append(url)
        if "returnCountOnly=true" in url:
            return FakeResponse(json.dumps({"count": n if count is None else count}).encode())
        offset = int(re.search(r"resultOffset=(\d+)", url).group(1))
        page = rows[offset:offset + page_size]
        doc = {"type": "FeatureCollection", "features": page}
        if offset + page_size < n:
            doc["properties"] = {"exceededTransferLimit": True}
        return FakeResponse(json.dumps(doc).encode())

    get.calls = calls
    return get


@pytest.fixture(autouse=True)
def no_wait(monkeypatch):
    monkeypatch.setattr(dl, "RETRY_WAIT", 0)


@pytest.fixture(autouse=True)
def usable_link(monkeypatch):
    """Leave the gate open by default; the tests that care close it."""
    monkeypatch.setattr("addressvault.net.wait_for_link", lambda **k: None)


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


def test_a_dead_link_stops_before_any_request(data_dir, monkeypatch):
    # The whole point of the gate: on a weekly trigger, finding out now costs a
    # second, and finding out at the end of a 600 s read costs the slot.
    def boom(*a, **k):
        raise AssertionError("made a request on a dead link")

    offline_gate(monkeypatch)
    monkeypatch.setattr("src.download.requests.get", boom)

    with pytest.raises(net.Offline):
        dl.download()


def test_a_dropped_query_is_retried(data_dir, monkeypatch):
    service = _service()
    state = {"n": 0}

    def get(url, headers=None, timeout=None):
        state["n"] += 1
        if state["n"] == 2:
            raise requests.ConnectionError("connection dropped")
        return service(url)

    monkeypatch.setattr("src.download.requests.get", get)
    status, path = dl.download()
    assert status == "DOWNLOADED"
    assert state["n"] == 5  # the count, a dropped page, then three pages
    assert os.path.basename(path).startswith("hydrants-")


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
    monkeypatch.setattr(
        "addressvault.net.wait_for_link",
        lambda **k: (_ for _ in ()).throw(net.Offline("link is offline")),
    )

    with pytest.raises(net.Offline):
        dl._fetch("http://example.invalid/query")
    assert state["n"] == 2  # the initial attempt plus RETRIES


def test_an_arcgis_error_is_not_written_as_data(data_dir, monkeypatch):
    # ArcGIS answers "Invalid or missing input parameters" with HTTP 200, so
    # raise_for_status proves nothing and the body has to be read.
    body = json.dumps({"error": {"code": 400, "message": "Invalid URL"}}).encode()
    monkeypatch.setattr("src.download.requests.get",
                        lambda *a, **k: FakeResponse(body))
    with pytest.raises(RuntimeError, match="error"):
        dl.download()
    assert not list(data_dir.glob("hydrants-*.geojson"))


def test_the_layer_is_paged_through_by_objectid(data_dir, monkeypatch):
    # maxRecordCount is 1,000 and the layer holds ~3,500: one query would
    # return the first thousand and set exceededTransferLimit -- inside
    # "properties" in a GeoJSON reply, not at the top.
    service = _service(n=2500)
    monkeypatch.setattr("src.download.requests.get", service)
    _status, path = dl.download()
    with open(path, encoding="utf-8") as f:
        ids = [ft["properties"]["OBJECTID"] for ft in json.load(f)["features"]]
    assert ids == list(range(1, 2501))
    pages = [u for u in service.calls if "resultOffset" in u]
    assert [re.search(r"resultOffset=(\d+)", u).group(1)
            for u in pages] == ["0", "1000", "2000"]
    assert all("orderByFields=OBJECTID" in u for u in pages)


def test_a_short_extract_stops_the_run(data_dir, monkeypatch):
    # A partial extract is the dangerous failure: the hydrants that fell off
    # the end would be reported to mappers as missing from OSM.
    monkeypatch.setattr("src.download.requests.get", _service(n=2500, count=2600))
    with pytest.raises(RuntimeError, match="2,600"):
        dl.download()
    assert not list(data_dir.glob("hydrants-*.geojson"))


def test_an_unchanged_extract_skips_the_write(data_dir, monkeypatch):
    # The cache key is the body hash, not Last-Modified: a /query response has
    # no meaningful Last-Modified, it is generated when you ask.
    monkeypatch.setattr("src.download.requests.get", _service())
    first_status, first_path = dl.download()
    assert first_status == "DOWNLOADED"

    second_status, second_path = dl.download()
    assert (second_status, second_path) == ("SKIPPED", first_path)
    assert len(list(data_dir.glob("hydrants-*.geojson"))) == 1


def test_a_changed_extract_is_written(data_dir, monkeypatch):
    monkeypatch.setattr("src.download.requests.get", _service(n=126))
    dl.download()
    monkeypatch.setattr("src.download.requests.get", _service(n=127))
    status, _path = dl.download()
    assert status == "DOWNLOADED"
