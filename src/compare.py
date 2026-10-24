"""Compare the City hydrants against the hydrants already in OSM.

Pulls fire hydrants from OpenStreetMap (Overpass) within Guelph, then pairs
them with the City's by distance alone: nearest pair first, one to one, within
FAR_M. There is no ID to key on -- the City's HYDRANTID is an asset number,
not painted on the hydrant, so no OSM hydrant carries it. The result is
written to data/gaps.geojson, one row per City hydrant that needs work, plus
one per OSM hydrant that is nowhere near a City one:

  * "missing"    -- no OSM hydrant within FAR_M (add the hydrant);
  * "far"        -- the paired OSM hydrant is NEAR_M-FAR_M away (probably the
                    same hydrant; one of the two points is off);
  * "duplicate"  -- a second OSM hydrant within FAR_M of a City hydrant that a
                    nearer one already took (one of the two is surplus);
  * "notype"     -- paired within NEAR_M, but no fire_hydrant:type;
  * "nocolour"   -- paired within NEAR_M, but no colour;
  * "noposition" -- paired within NEAR_M, but no fire_hydrant:position;
  * "osm_only"   -- an OSM hydrant more than FAR_M from every City hydrant.
                    The City layer is municipal hydrants only, so this is
                    most likely a private one (a campus, a plaza) -- flagged
                    for a look, not called wrong.

A paired hydrant lacking several tags is one row: its status is the first in
config.TAG_CHECKS order, its ``lacks`` lists every one, and each is counted.
A duplicate is reported on the City hydrant, so a City hydrant that has both a
duplicate and a tag gap carries the duplicate (the bigger problem).

Distances are equirectangular metres -- exact enough at city scale, and no GIS
dependency. A flaky Overpass falls back to the cached response, but only after
every mirror has been tried several times -- see _load_osm.
"""

import json
import math
import os
import time
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlsplit

import requests
from addressvault import net

from src import config, history

STATUSES = ("missing", "far", "duplicate", "notype", "nocolour", "noposition",
            "osm_only")
_SPATIAL_CELL = 0.0005  # degrees; ~55 m north-south, ~40 m east-west


def compare():
    """Build data/gaps.geojson + summary from City vs OSM. Returns the summary."""
    data, osm_date, from_cache = _load_osm()
    osm = _osm_hydrants(data)
    print(f"OSM hydrants:        {len(osm):,}")
    city = list(_city_hydrants())
    print(f"City hydrants:       {len(city):,}")

    gaps, counts = _match(city, osm)
    _write_gaps(gaps)

    summary = {"osm_hydrants": len(osm), "city": len(city),
               "osm_date": osm_date, "osm_stale": from_cache, **counts}
    with open(config.GAPS_COUNT_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print("Gaps: " + ", ".join(f"{counts[s]:,} {s}" for s in STATUSES))
    print(f"Matched within {config.NEAR_M} m: {counts['matched']:,}")
    if from_cache:
        print(f"NOTE: compared against cached OSM data from {osm_date}, "
              f"not a live Overpass fetch.")
    history.record(summary)
    return summary


# --- OSM source -------------------------------------------------------------

def _overpass_query(at=None):
    """The Overpass QL for hydrants; ``at`` (ISO instant) asks for OSM as it
    stood then -- an attic query, used by the history backfill.

    nwr, not node: every Guelph hydrant is a node today, but one drawn as a
    vertex of a way or (wrongly) as an area should still count as mapped,
    and "out center" gives each element a single lat/lon.
    """
    s, w, n, e = config.GUELPH_BBOX
    bbox = f"{s},{w},{n},{e}"
    settings = "[out:json][timeout:180]"
    if at:
        settings += f'[date:"{at}"]'
    return (
        settings + ";\n"
        f'nwr["emergency"="fire_hydrant"]({bbox});\n'
        "out center tags;"
    )


class OsmUnavailable(Exception):
    """Every mirror refused, on a machine that has a working link."""


def _load_osm():
    """Return (data, fetch_date, from_cache) for OSM hydrants.

    Every mirror is tried, and the whole list is retried: the thing being worked
    around is a loaded instance shedding one request, which clears in seconds.
    In the parks sibling one POST was once the entire effort, and two 504s a
    week apart left its gap page comparing against a fortnight-old OSM without
    failing anything.

    Falling back to the cache still beats no gap page, but it is reported rather
    than shrugged off -- ``from_cache`` reaches the published page, and an online
    machine that could not reach any mirror raises so the run can exit non-zero
    and be retried by the scheduler.
    """
    query = _overpass_query()
    print("Querying Overpass for OSM hydrants ...")
    for attempt in range(config.OVERPASS_ROUNDS):
        if attempt:
            print(f"  no mirror answered; retrying the list in "
                  f"{config.OVERPASS_ROUND_WAIT}s "
                  f"({attempt + 1} of {config.OVERPASS_ROUNDS})")
            time.sleep(config.OVERPASS_ROUND_WAIT)
        for url in config.OVERPASS_URLS:
            data = _try_overpass(url, query)
            if data is None:
                continue
            with open(config.OSM_CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f)
            osm_base = _osm_base(data)
            _save_fetch(date.today().isoformat(), url, osm_base, data)
            return data, osm_base, False

    # Nothing answered. Ask why before deciding what it means: no link is not a
    # failed build -- the run may as well not have happened -- while a healthy
    # link and no mirror is a real outage worth retrying.
    cached = _load_cache()
    try:
        net.wait_for_link(wait=False)
    except net.LinkUnavailable as e:
        print(f"Warning: no usable link ({e}); Overpass was never reachable.")
        if cached:
            return (*cached, True)
        raise

    if cached:
        print(f"Warning: no Overpass mirror answered in "
              f"{config.OVERPASS_ROUNDS} rounds; falling back to OSM data "
              f"from {cached[1]}.")
        return (*cached, True)
    raise OsmUnavailable(
        f"no Overpass mirror answered in {config.OVERPASS_ROUNDS} rounds "
        f"and there is no cached OSM data"
    )


def _try_overpass(url, query):
    """One attempt at one mirror; None if it failed or answered implausibly."""
    host = urlsplit(url).netloc
    started = time.time()
    try:
        resp = requests.post(
            url,
            data={"data": query},
            headers={"User-Agent": config.USER_AGENT},
            timeout=config.OVERPASS_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        print(f"  {host}: {type(e).__name__}: {str(e).splitlines()[0][:120]}")
        return None

    count = len(data.get("elements", []))
    if count < config.OSM_MIN_ELEMENTS:
        # HTTP 200 is not proof of an answer. A regional instance replies to a
        # Guelph bbox with a valid, empty element list, and taking that at face
        # value would report every City hydrant as missing from OSM.
        print(f"  {host}: {count:,} elements, under the "
              f"{config.OSM_MIN_ELEMENTS:,} floor -- ignoring this reply")
        return None
    base = _osm_base_time(data)
    if base and datetime.now(timezone.utc) - base > timedelta(days=config.OSM_MAX_AGE_DAYS):
        # Nor is a full reply proof of a current one. A lagging mirror answers
        # the query in full from data months old, and the page would present
        # that as this week's OSM.
        print(f"  {host}: OSM data from {_osm_base(data)}, older than "
              f"{config.OSM_MAX_AGE_DAYS} days -- ignoring this reply")
        return None
    print(f"  {host}: {count:,} elements in {time.time() - started:.0f}s, "
          f"OSM base {_osm_base(data)}")
    return data


def _load_cache():
    """(data, fetch_date) for the cached Overpass reply, or None."""
    if not os.path.isfile(config.OSM_CACHE_PATH):
        return None
    with open(config.OSM_CACHE_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data, _cache_date()


def _osm_base(data):
    """How current the OSM half of the diff actually is.

    Overpass states this about its own reply, as ``osm3s.timestamp_osm_base``:
    the moment of the last minutely diff the answering mirror had applied. That
    is the honest date for the page, and it is not the same as "today" -- a
    mirror can answer instantly with data from last week, which is precisely the
    failure this project has been bitten by. Trimmed to the minute for display;
    the raw value goes in the sidecar. Falls back to today's date if a mirror
    omits the block.
    """
    stamp = ((data.get("osm3s") or {}).get("timestamp_osm_base") or "").strip()
    if len(stamp) >= 16:
        return f"{stamp[:10]} {stamp[11:16]}Z"
    return date.today().isoformat()


def _osm_base_time(data):
    """The same timestamp as an aware datetime, or None if absent or garbled."""
    stamp = ((data.get("osm3s") or {}).get("timestamp_osm_base") or "").strip()
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None


def _cache_date():
    """How current the cached reply is: the sidecar, else the file's mtime."""
    if os.path.isfile(config.OSM_FETCH_PATH):
        with open(config.OSM_FETCH_PATH, encoding="utf-8") as f:
            sidecar = json.load(f)
        for key in ("osm_base", "fetched"):
            if sidecar.get(key):
                return sidecar[key]
    stamp = os.path.getmtime(config.OSM_CACHE_PATH)
    return date.fromtimestamp(stamp).isoformat()


def _save_fetch(fetched, url, osm_base, data):
    with open(config.OSM_FETCH_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "fetched": fetched,
            "mirror": urlsplit(url).netloc,
            "osm_base": osm_base,
            "timestamp_osm_base":
                (data.get("osm3s") or {}).get("timestamp_osm_base"),
        }, f, indent=2)



def _osm_hydrants(data):
    """Flatten the reply into hydrants: position, the checked tags, identity."""
    out = []
    for el in data.get("elements", []):
        tags = el.get("tags") or {}
        if "lat" in el and "lon" in el:
            lat, lon = el["lat"], el["lon"]
        elif el.get("center"):
            lat, lon = el["center"]["lat"], el["center"]["lon"]
        else:
            continue
        out.append({
            "lat": lat,
            "lon": lon,
            "tags": {k: tags[k] for _s, k in config.TAG_CHECKS if tags.get(k)},
            "otype": el.get("type"),
            "oid": el.get("id"),
        })
    return out


# --- City source ------------------------------------------------------------

def _city_hydrants():
    with open(config.SLIM_PATH, encoding="utf-8") as f:
        for line in f:
            feat = json.loads(line)
            props = feat.get("properties") or {}
            lon, lat = feat["geometry"]["coordinates"][:2]
            yield {
                "hydrant_id": props.get("hydrant_id"),
                "location_id": props.get("location_id"),
                "objectid": props.get("objectid"),
                "lat": lat,
                "lon": lon,
            }


# --- Matching ---------------------------------------------------------------

def _match(city, osm):
    """One gap row per City hydrant that needs work, plus OSM-only hydrants.

    Returns (gaps, counts). ``counts`` has one entry per status, plus
    "matched" (paired within NEAR_M, whatever its tags).
    """
    pairs = _pair(city, osm)               # {city index: (osm index, metres)}
    taken = {j for j, _d in pairs.values()}

    # Every OSM hydrant nobody paired is either a second one beside a City
    # hydrant, or one nowhere near any.
    city_grid = _grid(city)
    duplicates = {}                        # {city index: [osm index, ...]}
    osm_only = []
    for j, o in enumerate(osm):
        if j in taken:
            continue
        near = _nearest(o, city, city_grid)
        if near is not None and near[1] <= config.FAR_M:
            duplicates.setdefault(near[0], []).append(j)
        else:
            osm_only.append((j, near[1] if near else None))

    gaps = []
    counts = {s: 0 for s in STATUSES}
    counts["matched"] = 0
    for i, c in enumerate(city):
        match, d = (osm[pairs[i][0]], pairs[i][1]) if i in pairs else (None, None)
        extra = {}
        lacks = []
        if match is None:
            status = "missing"
        elif d > config.NEAR_M:
            status = "far"
        else:
            counts["matched"] += 1
            lacks = [s for s, k in config.TAG_CHECKS if k not in match["tags"]]
            status = lacks[0] if lacks else None
        if i in duplicates:
            other = osm[duplicates[i][0]]
            extra["other_url"] = _osm_url(other)
            extra["other_distance_m"] = round(_dist(c, other))
            status = "duplicate"
            counts["duplicate"] += 1
        if status is None:
            continue  # a tagged OSM hydrant is right here
        if status in ("missing", "far"):
            counts[status] += 1
        for s in lacks:
            counts[s] += 1
        if lacks:
            extra["lacks"] = lacks
        gaps.append(_gap_feature(c, status, match, d, extra))

    for j, d in osm_only:
        gaps.append(_osm_only_feature(osm[j], d))
        counts["osm_only"] += 1
    return gaps, counts


def _pair(city, osm):
    """{city index: (osm index, metres)}, nearest pair first, one to one.

    Every City-OSM pair within FAR_M is a candidate; the closest pair is
    settled first and both sides leave the pool. That is what keeps one OSM
    hydrant from answering for two City hydrants on the same corner, and a
    second OSM hydrant from hiding behind a first.
    """
    grid = _grid(osm)
    candidates = []
    for i, c in enumerate(city):
        for j in _around(c, grid):
            d = _dist(c, osm[j])
            if d <= config.FAR_M:
                candidates.append((d, i, j))
    candidates.sort()
    pairs, used = {}, set()
    for d, i, j in candidates:
        if i in pairs or j in used:
            continue
        pairs[i] = (j, d)
        used.add(j)
    return pairs


def _grid(points):
    grid = {}
    for k, p in enumerate(points):
        grid.setdefault(_cell(p), []).append(k)
    return grid


def _cell(p):
    return (int(math.floor(p["lat"] / _SPATIAL_CELL)),
            int(math.floor(p["lon"] / _SPATIAL_CELL)))


def _around(p, grid):
    """Indices in ``grid`` in the 3x3 cells around ``p`` -- everything within
    FAR_M, since a cell is wider than FAR_M in both directions."""
    cy, cx = _cell(p)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            yield from grid.get((cy + dy, cx + dx), ())


def _nearest(p, points, grid):
    """(index, metres) of the nearest of ``points`` to ``p``.

    The grid answers anything within FAR_M; past that the exact distance only
    goes on the osm_only row, so a full scan is fine for the handful there.
    """
    best = min(((k, _dist(p, points[k])) for k in _around(p, grid)),
               key=lambda t: t[1], default=None)
    if best is not None and best[1] <= config.FAR_M:
        return best
    return min(((k, _dist(p, q)) for k, q in enumerate(points)),
               key=lambda t: t[1], default=None)


def _osm_url(o):
    return f"https://www.openstreetmap.org/{o['otype']}/{o['oid']}"


def _gap_feature(c, status, match, d, extra):
    props = {
        "hydrant_id": c["hydrant_id"],
        "location_id": c["location_id"],
        "status": status,
    }
    if c["hydrant_id"] is None:
        props["objectid"] = c["objectid"]
    if match:
        props["osm_url"] = _osm_url(match)
        props["osm_lat"] = round(match["lat"], 6)
        props["osm_lon"] = round(match["lon"], 6)
        props["distance_m"] = round(d, 1)
        props["osm_tags"] = match["tags"]
    props.update(extra)
    return {
        "type": "Feature",
        "properties": props,
        "geometry": {"type": "Point",
                     "coordinates": [round(c["lon"], 6), round(c["lat"], 6)]},
    }


def _osm_only_feature(o, nearest_m):
    props = {
        "hydrant_id": None,
        "location_id": None,
        "status": "osm_only",
        "osm_url": _osm_url(o),
        "osm_tags": o["tags"],
    }
    if nearest_m is not None:
        props["nearest_city_m"] = round(nearest_m)
    return {
        "type": "Feature",
        "properties": props,
        "geometry": {"type": "Point",
                     "coordinates": [round(o["lon"], 6), round(o["lat"], 6)]},
    }


def _write_gaps(gaps):
    with open(config.GAPS_GEOJSON_PATH, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": gaps}, f)


# --- Geometry ---------------------------------------------------------------

def _dist(a, b):
    """Metres between two {lat, lon}; equirectangular, fine at city scale."""
    lat0 = math.radians((a["lat"] + b["lat"]) / 2)
    dx = math.radians(b["lon"] - a["lon"]) * math.cos(lat0)
    dy = math.radians(b["lat"] - a["lat"])
    return 6371008.8 * math.hypot(dx, dy)
