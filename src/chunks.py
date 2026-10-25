"""Split the City points missing from OSM into import chunks.

A chunk is one JOSM layer and one changeset. Chunks are as large as
config.IMPORT_MAX_PER_CHUNK allows and geographically compact: the points are
cut along the longer side of their bounding box, into as few parts as the cap
permits, and each half is cut again until it fits. Every chunk is a rectangle
that overlaps no other chunk of its kind, and the cut is deterministic, so the
same gap list gives the same chunks.

Chunks are recomputed from the gap list on every build. Imported points drop
out of it, so the chunks of next week's build are not this week's.
"""

import math
from xml.sax.saxutils import quoteattr

from src import config


def import_rows(features):
    """The gap rows that belong in an import, grouped by kind.

    Only "missing" points the City lists as Existing: a far or duplicate row
    has an OSM feature already, and a Temporarily Removed one is a point the
    City says is not on the street, so no reviewer could find it.
    """
    out = {kind: [] for kind in config.IMPORT_TAGS}
    for f in features:
        p = f["properties"]
        if (p.get("status") == "missing" and p.get("city_status") == "Existing"
                and p.get("kind") in out):
            out[p["kind"]].append(f)
    return out


def split(features, cap):
    """Cut point features into ceil(n / cap) compact, near-equal groups."""
    if len(features) <= cap:
        return [features] if features else []
    parts = math.ceil(len(features) / cap)
    lons = [f["geometry"]["coordinates"][0] for f in features]
    lats = [f["geometry"]["coordinates"][1] for f in features]
    mid_lat = (min(lats) + max(lats)) / 2
    width = (max(lons) - min(lons)) * math.cos(math.radians(mid_lat))
    axis = 0 if width >= max(lats) - min(lats) else 1
    # The ID breaks ties, so equal coordinates never reorder between builds.
    ordered = sorted(features, key=lambda f: (f["geometry"]["coordinates"][axis],
                                              f["properties"].get("id") or ""))
    left = parts // 2
    cut = round(len(features) * left / parts)
    return split(ordered[:cut], cap) + split(ordered[cut:], cap)


def bbox(features):
    """(south, west, north, east) of point features."""
    lons = [f["geometry"]["coordinates"][0] for f in features]
    lats = [f["geometry"]["coordinates"][1] for f in features]
    return min(lats), min(lons), max(lats), max(lons)


def osm_xml(features, kind):
    """A JOSM-ready .osm file: one new node per point, the kind's import tags.

    The City's ID, site ID and barcode stay out: they are asset numbers no
    mapper can check on the street, so none of them belongs in OSM (see the
    README, "No ref, on purpose").
    """
    tags = "".join(f"\n    <tag k={quoteattr(k)} v={quoteattr(v)}/>"
                   for k, v in config.IMPORT_TAGS[kind].items())
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<osm version="0.6" generator="toronto-poster-columns-layer">']
    for i, f in enumerate(features, 1):
        lon, lat = f["geometry"]["coordinates"]
        lines.append(f'  <node id="-{i}" lat="{lat:.7f}" lon="{lon:.7f}">'
                     f"{tags}\n  </node>")
    lines.append("</osm>")
    return "\n".join(lines) + "\n"
