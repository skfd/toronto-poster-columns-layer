"""Download the Guelph Hydrants GeoJSON from the City's ArcGIS service.

The bus stops sibling's download step, with one structural difference: this
layer does not fit in one reply. The service caps a query at maxRecordCount
(1,000) and the layer holds ~3,500 hydrants, so the rows are fetched in pages
ordered by OBJECTID and assembled into one FeatureCollection. The service is
asked for its count first, and the assembled rows must add up to it -- a page
lost to a hiccup would otherwise report a few hundred hydrants as missing from
OSM, and look exactly like a good run.

An ArcGIS FeatureServer `/query` is generated per request, so it has no
Last-Modified worth caching on. What is compared is a **sha256 of the
assembled FeatureCollection**. Identical hash means the City has not touched
the layer, and the existing dated file is kept -- which also keeps DATA_DATE
meaning "when the City data last changed" rather than "when the build last
ran".

Every request is gated on a usable link first (``addressvault.net``, the same
gate the address vault pulls behind). The weekly trigger is what makes that
worth doing: a run lost to a dead link is not retried for a week.
"""

import hashlib
import json
import os
import time
from datetime import date

import requests
from addressvault import net

from src import config

# Four pages of ~250 KB -- a retry costs a couple of seconds when the link is
# healthy and buys back a week when it is not.
RETRIES = 3
RETRY_WAIT = 30


def download(force=False):
    """Download the latest Hydrants GeoJSON.

    Returns (status, filepath) where status is "DOWNLOADED" or "SKIPPED".
    Raises ``net.LinkUnavailable`` when the host has no usable link: nothing was
    attempted, so the caller exits 75 rather than reporting a build failure.
    """
    os.makedirs(config.DATA_DIR, exist_ok=True)

    # Ask before doing anything. Offline or metered, nothing below can work, and
    # finding out here costs a second instead of a 600 s read timeout. Never
    # block waiting for the link: the task carries a hard ExecutionTimeLimit, so
    # a wait would be killed mid-sleep -- retrying is the scheduler's job.
    net.wait_for_link(wait=False)

    print("Querying the Hydrants FeatureServer ...")
    features = fetch_all()
    body = json.dumps({"type": "FeatureCollection", "features": features},
                      separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(body).hexdigest()

    sidecar = _load_sidecar()
    if not force and sidecar and sidecar.get("sha256") == digest:
        existing = os.path.join(config.DATA_DIR, sidecar.get("filename", ""))
        if os.path.isfile(existing):
            print("Unchanged since the last download.")
            return "SKIPPED", existing

    # No server-side edit date exists on this service (the layer has no
    # editingInfo and no last_edited_date field), so the file is dated by the
    # day the change was first seen here.
    filename = f"hydrants-{date.today().isoformat()}.geojson"
    filepath = os.path.join(config.DATA_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(body)
    print(f"Done: {filepath} ({len(body) // 1024:,} KB)")

    _save_sidecar(digest, len(body), filename)
    return "DOWNLOADED", filepath


def fetch_all(fetch=None):
    """Every feature in the layer, page by page; raises on a short extract."""
    fetch = fetch or _fetch
    expected = _count(fetch(_url(returnCountOnly="true", f="json")))
    print(f"  the service reports {expected:,} rows")
    features = []
    while True:
        page = _check_page(fetch(_url(
            outFields="*", outSR="4326", f="geojson", orderByFields="OBJECTID",
            resultOffset=str(len(features)),
            resultRecordCount=str(config.PAGE_SIZE),
        )))
        features.extend(page["features"])
        more = (page.get("properties") or {}).get("exceededTransferLimit") \
            or page.get("exceededTransferLimit")
        if not more or not page["features"]:
            break
    print(f"  {len(features):,} features")
    if len(features) != expected:
        raise RuntimeError(
            f"Paged {len(features):,} features but the service counts "
            f"{expected:,}. The extract is partial or the layer changed "
            f"mid-download -- not trusting it."
        )
    ids = [(f.get("properties") or {}).get(config.OBJECT_ID_KEY) for f in features]
    if len(set(ids)) != len(ids):
        raise RuntimeError("A page repeated rows (duplicate OBJECTID) -- not trusting it.")
    if not features:
        raise RuntimeError("The service returned no hydrants.")
    return features


def _url(**params):
    query = "&".join(f"{k}={v}" for k, v in {"where": "1%3D1", **params}.items())
    return f"{config.QUERY_URL}?{query}"


def _fetch(url):
    """GET ``url``, retrying a dropped connection. Returns the raw body."""
    for attempt in range(RETRIES + 1):
        try:
            resp = requests.get(
                url,
                headers={"User-Agent": config.USER_AGENT},
                timeout=600,
            )
            resp.raise_for_status()
            return resp.content
        except requests.RequestException as e:
            if attempt == RETRIES:
                # Out of retries. If the link itself is down then this was never
                # a City failure -- say so, and the run exits 75 instead of
                # logging a build error against a service never reached at all.
                net.wait_for_link(wait=False)
                raise
            print(f"  query failed ({e}); retrying in {RETRY_WAIT}s")
            time.sleep(RETRY_WAIT)


def _parse(body):
    """JSON, or a RuntimeError. An ArcGIS service answers an error with HTTP
    200 and a JSON body carrying an ``error`` object, so raise_for_status
    proves nothing."""
    try:
        doc = json.loads(body)
    except ValueError as e:
        raise RuntimeError(f"The service did not return JSON: {e}")
    if "error" in doc:
        raise RuntimeError(f"The service returned an error: {doc['error']}")
    return doc


def _count(body):
    doc = _parse(body)
    if not isinstance(doc.get("count"), int):
        raise RuntimeError(f"Expected a row count, got {doc!r:.200}")
    return doc["count"]


def _check_page(body):
    doc = _parse(body)
    if doc.get("type") != "FeatureCollection":
        raise RuntimeError(f"Expected a FeatureCollection, got {doc.get('type')!r}")
    doc["features"] = doc.get("features") or []
    return doc


def _load_sidecar():
    if os.path.isfile(config.LAST_DOWNLOAD_PATH):
        with open(config.LAST_DOWNLOAD_PATH, encoding="utf-8") as f:
            return json.load(f)
    return None


def _save_sidecar(digest, size, filename):
    with open(config.LAST_DOWNLOAD_PATH, "w", encoding="utf-8") as f:
        json.dump(
            {"sha256": digest, "bytes": size, "filename": filename}, f, indent=2
        )
