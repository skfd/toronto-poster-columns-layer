"""Configuration constants for the Guelph hydrants tile layer build.

Single source of truth. No logic here.

Sibling of guelph-bus-stops-layer: the same pipeline (download -> slim ->
compare -> vector + raster -> site -> publish), pointed at the City of Guelph
Hydrants layer instead of Bus Stops. Both are points; what differs is that a
hydrant carries no number a mapper can read off it, so the OSM comparison
matches by distance alone and the raster draws plain dots with no labels.
"""

import os

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_DIR, "data")
BUILD_DIR = os.path.join(PROJECT_DIR, "build")
SITE_DIR = os.path.join(BUILD_DIR, "site")
ASSETS_DIR = os.path.join(PROJECT_DIR, "assets")
LOGS_DIR = os.path.join(PROJECT_DIR, "logs")

MBTILES_PATH = os.path.join(BUILD_DIR, "hydrants.mbtiles")
SLIM_PATH = os.path.join(DATA_DIR, "hydrants-slim.geojsonl")
COUNT_PATH = os.path.join(DATA_DIR, "hydrants.count")
LAST_DOWNLOAD_PATH = os.path.join(DATA_DIR, ".last-download.json")

VECTOR_TILE_DIR = os.path.join(SITE_DIR, "tiles", "vector")
RASTER_TILE_DIR = os.path.join(SITE_DIR, "tiles", "raster")

# Data source: City of Guelph Hydrants (OpenData2 layer 3), 3,537 points on
# 2026-10-09. Same ArcGIS server as the siblings, so the same rules: the
# geometry is stored in EPSG:26917 and outSR=4326 is not optional, and
# f=geojson makes the service do the Esri-JSON -> GeoJSON conversion.
#
# Unlike the bus stops, this layer is bigger than one page: the service's
# maxRecordCount is 1,000, so download.py pages through it by OBJECTID.
FEATURE_SERVER = (
    "https://gismaps.guelph.ca/hosting/rest/services/OpenData/OpenData2"
    "/FeatureServer/3"
)
QUERY_URL = f"{FEATURE_SERVER}/query"
PAGE_SIZE = 1000
# The service's own page. Guelph's open-data catalogue has no stable item page
# for this layer, so the FeatureServer URL is what a reader is pointed at.
DATASET_PAGE = FEATURE_SERVER
# This layer REDISTRIBUTES City data as published tiles, and the licence
# attaches a required attribution to that. It is carried on the landing page,
# the gap page and the history page. See the README section "Licence"; it is a
# condition, not a courtesy.
LICENSE_URL = "https://gismaps.guelph.ca/Images/OpenDataLicenceVersion2.pdf"
LICENSE_NOTICE = (
    "Contains information licensed under the Open Government Licence "
    "– City of Guelph."
)
# Plain-ASCII attribution embedded in tile metadata (it is passed through the
# WSL shell, where the en dash in LICENSE_NOTICE is not safe).
ATTRIBUTION = (
    "Contains information licensed under the Open Government Licence "
    "- City of Guelph"
)

# GitHub Pages target. PAGES_URL carries NO trailing slash: every tile URL on
# the site is built as f"{PAGES_URL}/tiles/...", and a trailing slash would
# emit "...//tiles/...", which is the one thing on the page a reader copies
# verbatim into their editor.
GITHUB_REPO = "guelph-maps/guelph-hydrants-layer"
PAGES_URL = "https://guelph-maps.github.io/guelph-hydrants-layer"

# WSL distro that has tippecanoe installed (see wsl-setup.md).
WSL_DISTRO = "Ubuntu"

# Vector tiles. iD requests tiles at (map zoom - 1) and does NOT overzoom, so
# tiles must be generated natively through the zooms used for mapping. A
# hydrant is a point a mapper only looks for at street zooms.
VECTOR_MINZOOM = 12
VECTOR_MAXZOOM = 19
VECTOR_LAYER_NAME = "hydrants"

# Raster tiles. Editors overzoom z17 -> z18+. Below z15 a city's worth of
# hydrants is a red haze, not a reference; see raster.py.
RASTER_ZOOMS = [15, 16, 17]

# Source property keys read from the Hydrants GeoJSON. None of them is a key
# for matching: HYDRANTID and LOCATIONID are the City's asset numbers, not
# painted on the hydrant, so a mapper standing at one cannot read them and
# they do not belong in OSM's ref. They are carried so a reviewer can name a
# row, nothing more. HYDRANTID is null on 7 of 3,537 rows.
HYDRANT_ID_KEY = "HYDRANTID"     # e.g. 1234
LOCATION_ID_KEY = "LOCATIONID"   # e.g. "H40-053"
MODEL_KEY = "MODEL"              # set on 80 rows, e.g. "Post Hydrant - Series 67"
OBJECT_ID_KEY = "OBJECTID"       # ArcGIS row id; the paging order

# --- OSM comparison (gap-review page) ---
# Hydrants are pulled from OSM via Overpass and matched against the City
# points by distance, nearest pair first, one to one; the gaps feed
# build/site/gaps/.
#
# The mirror policy is the parks layer's, unchanged and for the same reasons:
# overpass.kumi.systems and overpass.private.coffee have both been caught
# serving months-stale data, which is the worse failure because it looks
# exactly like success. private.coffee did it with these very hydrants on
# 2026-10-09: HTTP 200, a full reply, OSM as of 2026-05-31.
OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
)
OVERPASS_TIMEOUT = 300
OVERPASS_ROUNDS = 3
OVERPASS_ROUND_WAIT = 60
# Floor on a reply's element count. The first live reply (2026-10-09) carried
# 150 hydrants, and mappers are adding them, not removing them; a reply under
# half that is a wrong-region or truncated answer. Taking an empty reply at
# face value would report all 3,537 City hydrants as missing from OSM.
OSM_MIN_ELEMENTS = 75
# Oldest OSM data a reply may carry (its osm3s.timestamp_osm_base) and still be
# compared against. A healthy instance is minutes behind.
OSM_MAX_AGE_DAYS = 3
# Overpass rejects the default requests User-Agent (HTTP 406); identify the tool.
USER_AGENT = "guelph-hydrants-layer/0.1 (toronto@comentality.com)"
# Guelph bounding box (S, W, N, E), verbatim from guelph-beholder's config.toml
# -- a touch larger than the city. Every City hydrant is inside it.
GUELPH_BBOX = (43.46, -80.34, 43.60, -80.14)
# Guelph city centre; where the preview and gap maps open.
GUELPH_CENTER = (43.5448, -80.2482)
OSM_CACHE_PATH = os.path.join(DATA_DIR, "osm-hydrants.json")
# When the cached Overpass reply was fetched, from where, and -- more usefully
# -- the OSM database timestamp the reply declares about itself.
OSM_FETCH_PATH = os.path.join(DATA_DIR, ".osm-fetch.json")
GAPS_GEOJSON_PATH = os.path.join(DATA_DIR, "gaps.geojson")
GAPS_COUNT_PATH = os.path.join(DATA_DIR, "gaps.count.json")

# Distances, in metres. Measured on 2026-10-09: 146 of OSM's 150 hydrants sit
# within 30 m of a City hydrant, median 1.4 m, and the missing count barely
# moves with the radius (3,398 at 5 m, 3,384 at 10 m, 3,378 at 30 m).
#   NEAR_M -- an OSM hydrant this close is the City's: matched, and its tags
#             are checked.
#   FAR_M  -- one between NEAR_M and this is "far": probably the same
#             hydrant, but one of the two points is in the wrong place. An OSM
#             hydrant within this of a City hydrant that a nearer OSM hydrant
#             already took is a "duplicate"; beyond it, "osm_only".
NEAR_M = 10
FAR_M = 30

# The tags checked on a matched hydrant, in the order a row reports them. The
# row's status is the first one missing; its ``lacks`` lists all of them, and
# each is counted on its own.
TAG_CHECKS = (
    ("notype", "fire_hydrant:type"),
    ("nocolour", "colour"),
    ("noposition", "fire_hydrant:position"),
)

# --- Gap history (trend page) ---
HISTORY_PATH = os.path.join(DATA_DIR, "history.jsonl")
HISTORY_URL = f"{PAGES_URL}/gaps/history.jsonl"
# Backfill. overpass-api.de keeps OSM's full history and answers the same
# query for a past instant ([date:...]). Weekly points, one attempt per date,
# and a pause between dates -- attic queries are heavier than live ones.
ATTIC_URL = "https://overpass-api.de/api/interpreter"
BACKFILL_SINCE = "2026-06-01"   # a Monday; the parks sibling's start, so the charts line up
BACKFILL_STEP_DAYS = 7          # the weekly schedule's cadence
BACKFILL_PAUSE = 30
