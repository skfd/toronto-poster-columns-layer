"""Download the City of Toronto's two postering datasets from CKAN.

The hydrants sibling's download step, reshaped by the source: this layer is two
CKAN packages, not one ArcGIS layer, and CKAN serves static files. Each package
is asked for its resource list (``package_show``) and the WGS84 GeoJSON is
picked out by name -- the resource ids are not hard-coded, so a republish that
mints new ones does not break the download. Both files are fetched, every
feature is stamped with its ``kind`` (``column`` or ``shelter_board``), and the
two are merged into one FeatureCollection.

Each file is checked against its floor (config.SOURCES) before the merge. A
file that falls short would report the missing rows to mappers as nothing --
quietly, and looking exactly like a good run -- so the run stops instead.

What is compared between runs is a **sha256 of the merged FeatureCollection**.
Identical hash means the City has not touched either dataset, and the existing
dated file is kept. The file is dated by the newer of the two resources'
``last_modified``, so DATA_DATE means "when the City last published" rather
than "when the build last ran".

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

# Two files of ~1 MB -- a retry costs a couple of seconds when the link is
# healthy and buys back a week when it is not.
RETRIES = 3
RETRY_WAIT = 30


def download(force=False):
    """Download and merge the latest postering GeoJSONs.

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

    features, published = fetch_all()
    body = json.dumps({"type": "FeatureCollection", "features": features},
                      separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(body).hexdigest()

    sidecar = _load_sidecar()
    if not force and sidecar and sidecar.get("sha256") == digest:
        existing = os.path.join(config.DATA_DIR, sidecar.get("filename", ""))
        if os.path.isfile(existing):
            print("Unchanged since the last download.")
            return "SKIPPED", existing

    filename = f"posters-{published or date.today().isoformat()}.geojson"
    filepath = os.path.join(config.DATA_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(body)
    print(f"Done: {filepath} ({len(body) // 1024:,} KB)")

    _save_sidecar(digest, len(body), filename)
    return "DOWNLOADED", filepath


def fetch_all(fetch=None):
    """(features, published) for every source; raises on a short file.

    ``published`` is the newest resource last_modified (YYYY-MM-DD), or None.
    """
    fetch = fetch or _fetch
    features = []
    dates = []
    for kind, (package, floor) in config.SOURCES.items():
        resource = _resource(_parse(fetch(
            f"{config.CKAN_API}/package_show?id={package}")), package)
        print(f"Fetching {resource['name']} ...")
        doc = _parse(fetch(resource["url"]))
        rows = doc.get("features") if doc.get("type") == "FeatureCollection" else None
        if rows is None:
            raise RuntimeError(f"{package}: expected a FeatureCollection, "
                               f"got {doc.get('type')!r}")
        print(f"  {len(rows):,} {kind} features")
        if len(rows) < floor:
            raise RuntimeError(
                f"{package} has {len(rows):,} features, under the floor of "
                f"{floor:,}. The file is partial or the wrong one -- not "
                f"trusting it."
            )
        ids = [(r.get("properties") or {}).get(config.ID_KEY) for r in rows]
        if None in ids:
            raise RuntimeError(f"{package} has a row with no {config.ID_KEY} -- "
                               f"not the file expected.")
        if len(set(ids)) != len(ids):
            raise RuntimeError(f"{package} repeats an {config.ID_KEY} -- not trusting it.")
        for r in rows:
            r["properties"] = {**(r.get("properties") or {}), "kind": kind}
        features.extend(rows)
        if resource.get("last_modified"):
            dates.append(resource["last_modified"][:10])
    return features, max(dates) if dates else None


def _resource(doc, package):
    """The package's WGS84 GeoJSON resource.

    Matched on the name, not the format: the package's "datastore dump" is
    listed with format GeoJSON too, and it is not this file.
    """
    resources = (doc.get("result") or {}).get("resources") or []
    hits = [r for r in resources
            if (r.get("name") or "").endswith(config.RESOURCE_SUFFIX)
            and not r.get("datastore_active")]
    if len(hits) != 1:
        names = ", ".join(r.get("name") or "?" for r in resources)
        raise RuntimeError(
            f"{package}: expected one resource named '*{config.RESOURCE_SUFFIX}', "
            f"found {len(hits)} among: {names}"
        )
    return hits[0]


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
            print(f"  request failed ({e}); retrying in {RETRY_WAIT}s")
            time.sleep(RETRY_WAIT)


def _parse(body):
    """JSON, or a RuntimeError. CKAN answers a failed action with a JSON body
    whose ``success`` is false, so a 200 is not the whole story."""
    try:
        doc = json.loads(body)
    except ValueError as e:
        raise RuntimeError(f"The City's server did not return JSON: {e}")
    if doc.get("success") is False:
        raise RuntimeError(f"CKAN returned an error: {doc.get('error')}")
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
