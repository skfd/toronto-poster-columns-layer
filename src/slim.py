"""Filter the merged postering GeoJSON into a slim newline-delimited GeoJSON.

The source file is a ~1.3 MB GeoJSON FeatureCollection; it is parsed as a
stream with ijson for consistency with the sibling projects. Every point is
kept, one compact Feature per line, in data/posters-slim.geojsonl -- the input
to both tile builders and to the gap tool.

The City stores each point as a one-point MultiPoint; it is written out as a
Point. There is no status filter: a "Temporarily Removed" column is still a
City postering spot (94 columns and 28 shelter boards on 2026-10-24), and the
status travels with it so the tiles and the gap page can say so.
"""

import json
import os

import ijson

from src import config

# Sanity bounds for the slimmed feature count (2,496 points on 2026-10-24).
# The per-dataset floors in config.SOURCES are the finer check; this one
# catches a merge gone wrong.
MIN_EXPECTED = 2250
MAX_EXPECTED = 3500


def slim(src_path):
    """Stream the GeoJSON into data/posters-slim.geojsonl.

    Keeps point features, with ``kind``, ``id``, ``site_id``, ``asset_type``,
    ``city_status``, ``address``, ``fronting`` and ``from_street`` properties
    where the City has them. Returns the slim file path. Raises if the feature
    count is implausible.
    """
    print(f"Slimming {src_path} ...")
    os.makedirs(config.DATA_DIR, exist_ok=True)

    count = 0
    skipped = 0
    with open(src_path, "rb") as src, \
            open(config.SLIM_PATH, "w", encoding="utf-8") as out:
        for feature in ijson.items(src, "features.item"):
            props_in = feature.get("properties") or {}
            point = _point(feature.get("geometry") or {})
            kind = props_in.get("kind")
            if point is None or kind not in config.STATUS_KEYS:
                skipped += 1
                continue

            props_out = {"kind": kind}
            for key, name in ((config.ID_KEY, "id"),
                              (config.SITE_ID_KEY, "site_id"),
                              (config.ASSET_TYPE_KEY, "asset_type"),
                              (config.STATUS_KEYS[kind], "city_status"),
                              (config.FRONTING_KEY, "fronting"),
                              (config.FROM_KEY, "from_street")):
                value = _text(props_in.get(key))
                if value:
                    props_out[name] = value
            address = " ".join(v for v in (_text(props_in.get(k))
                                           for k in config.ADDRESS_KEYS) if v)
            if address:
                props_out["address"] = address

            lon, lat = point
            out.write(json.dumps({
                "type": "Feature",
                # ~0.1 m. The City hands back 12 decimal places.
                "geometry": {"type": "Point",
                             "coordinates": [round(float(lon), 6),
                                             round(float(lat), 6)]},
                "properties": props_out,
            }) + "\n")
            count += 1

    with open(config.COUNT_PATH, "w", encoding="utf-8") as f:
        f.write(str(count))

    print(f"Done: {config.SLIM_PATH} ({count:,} features, {skipped:,} skipped)")
    if not MIN_EXPECTED <= count <= MAX_EXPECTED:
        raise RuntimeError(
            f"Slim feature count {count:,} is outside the expected range "
            f"{MIN_EXPECTED:,}-{MAX_EXPECTED:,} -- aborting."
        )
    return config.SLIM_PATH


def _point(geom):
    """(lon, lat) of a Point or a one-point MultiPoint, else None."""
    coords = geom.get("coordinates")
    if geom.get("type") == "Point" and coords:
        return coords[:2]
    if geom.get("type") == "MultiPoint" and coords and len(coords) == 1:
        return coords[0][:2]
    return None


def _text(value):
    """A stripped string, with the City's literal "None" read as blank."""
    value = str(value if value is not None else "").strip()
    return "" if value == "None" else value
