"""Filter the Hydrants GeoJSON into a slim newline-delimited GeoJSON.

The source file is a ~800 KB GeoJSON FeatureCollection; it is parsed as a
stream with ijson for consistency with the sibling projects. Every point is
kept, one compact Feature per line, in data/hydrants-slim.geojsonl -- the input
to both tile builders and to the gap tool.

There is no key to check here, unlike the bus stops: nothing is matched on an
ID, only on position, so a row with no HYDRANTID (7 on 2026-10-09) is still a
hydrant. There is no status filter either -- the layer has no status field.
"""

import json
import os

import ijson

from src import config

# Sanity bounds for the slimmed feature count (3,537 hydrants on 2026-10-09).
MIN_EXPECTED = 3000
MAX_EXPECTED = 4500


def slim(src_path):
    """Stream the GeoJSON into data/hydrants-slim.geojsonl.

    Keeps Point features, with `hydrant_id`, `location_id`, `model` and
    `objectid` properties where the City has them. Returns the slim file path.
    Raises if the feature count is implausible.
    """
    print(f"Slimming {src_path} ...")
    os.makedirs(config.DATA_DIR, exist_ok=True)

    count = 0
    skipped = 0
    with open(src_path, "rb") as src, \
            open(config.SLIM_PATH, "w", encoding="utf-8") as out:
        for feature in ijson.items(src, "features.item"):
            props_in = feature.get("properties") or {}
            geom = feature.get("geometry") or {}
            if geom.get("type") != "Point" or not geom.get("coordinates"):
                skipped += 1
                continue

            props_out = {}
            hydrant_id = props_in.get(config.HYDRANT_ID_KEY)
            if hydrant_id is not None:
                props_out["hydrant_id"] = int(hydrant_id)
            for key, name in ((config.LOCATION_ID_KEY, "location_id"),
                              (config.MODEL_KEY, "model")):
                value = str(props_in.get(key) or "").strip()
                if value:
                    props_out[name] = value
            # The ArcGIS row id. It can renumber when the layer is republished,
            # so nothing keys on it; it names the row for a reviewer when the
            # City left HYDRANTID blank.
            objectid = props_in.get(config.OBJECT_ID_KEY)
            if objectid is not None:
                props_out["objectid"] = int(objectid)

            lon, lat = geom["coordinates"][:2]
            out.write(json.dumps({
                "type": "Feature",
                # ~0.1 m. The service hands back 14 decimal places.
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
