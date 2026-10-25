"""Configuration constants for the Toronto poster columns tile layer build.

Single source of truth. No logic here.

A clone of guelph-hydrants-layer: the same pipeline (download -> slim ->
compare -> vector + raster -> site -> publish), pointed at the City of
Toronto's two street-furniture postering datasets instead of Guelph's
hydrants. Both are points, and neither carries a number a mapper can read off
the structure, so the OSM comparison matches by distance alone, as hydrants
does. What differs: the City side is two CKAN files merged into one layer with
a ``kind``, and the OSM side accepts two tagging families, so the comparison
reports position only.
"""

import os

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_DIR, "data")
BUILD_DIR = os.path.join(PROJECT_DIR, "build")
SITE_DIR = os.path.join(BUILD_DIR, "site")
ASSETS_DIR = os.path.join(PROJECT_DIR, "assets")
LOGS_DIR = os.path.join(PROJECT_DIR, "logs")

MBTILES_PATH = os.path.join(BUILD_DIR, "posters.mbtiles")
SLIM_PATH = os.path.join(DATA_DIR, "posters-slim.geojsonl")
COUNT_PATH = os.path.join(DATA_DIR, "posters.count")
LAST_DOWNLOAD_PATH = os.path.join(DATA_DIR, ".last-download.json")

VECTOR_TILE_DIR = os.path.join(SITE_DIR, "tiles", "vector")
RASTER_TILE_DIR = os.path.join(SITE_DIR, "tiles", "raster")

# Data source: two City of Toronto open-data packages, one layer. CKAN static
# files, not ArcGIS paging: each package is asked for its resource list
# (package_show) and the WGS84 GeoJSON is picked from it by name, so a
# republish that mints new resource ids does not break the download. Both
# packages also list a "datastore dump" whose format is GeoJSON too; that one
# is a CSV-shaped export, and the name filter is what keeps it out.
CKAN_API = "https://ckan0.cf.opendata.inter.prod-toronto.ca/api/3/action"
# kind -> (CKAN package name, floor). The floor refuses a pull that falls
# short: 834 structures and 1,662 shelter boards on 2026-10-24, and a file
# under ~90% of that is a truncated or wrong file, not the City removing a
# tenth of its street furniture between two semi-annual refreshes.
SOURCES = {
    "column": ("street-furniture-poster-structure", 750),
    "shelter_board": ("street-furniture-poster-board", 1500),
}
RESOURCE_SUFFIX = "- 4326.geojson"   # e.g. "Poster structure data - 4326.geojson"
DATASET_PAGES = {
    "column": "https://open.toronto.ca/dataset/street-furniture-poster-structure/",
    "shelter_board": "https://open.toronto.ca/dataset/street-furniture-poster-board/",
}
# This layer REDISTRIBUTES City data as published tiles, and the licence
# attaches a required attribution to that. It is carried on the landing page,
# the gap page and the history page. See the README section "Licence"; it is a
# condition, not a courtesy.
LICENSE_URL = "https://open.toronto.ca/open-data-licence/"
LICENSE_NOTICE = (
    "Contains information licensed under the Open Government Licence "
    "– Toronto."
)
# Plain-ASCII attribution embedded in tile metadata (it is passed through the
# WSL shell, where the en dash in LICENSE_NOTICE is not safe).
ATTRIBUTION = "(c) City of Toronto, Open Government Licence - Toronto"

# GitHub Pages target. PAGES_URL carries NO trailing slash: every tile URL on
# the site is built as f"{PAGES_URL}/tiles/...", and a trailing slash would
# emit "...//tiles/...", which is the one thing on the page a reader copies
# verbatim into their editor.
GITHUB_REPO = "skfd/toronto-poster-columns-layer"
PAGES_URL = "https://skfd.github.io/toronto-poster-columns-layer"

# WSL distro that has tippecanoe installed (see wsl-setup.md).
WSL_DISTRO = "Ubuntu"

# Vector tiles. iD requests tiles at (map zoom - 1) and does NOT overzoom, so
# tiles must be generated natively through the zooms used for mapping. A
# poster column is a point a mapper only looks for at street zooms.
VECTOR_MINZOOM = 12
VECTOR_MAXZOOM = 19
VECTOR_LAYER_NAME = "posters"

# Raster tiles. Editors overzoom z17 -> z18+. Below z15 a city's worth of
# street furniture is a haze, not a reference; see raster.py.
RASTER_ZOOMS = [15, 16, 17]

# Source property keys, shared by both datasets. None of them is a key for
# matching: ID ("PO-00022", "SH-03579"), SITEID and BARCODE are the City's
# asset numbers, not something a mapper standing at the column can check, and
# they do not belong in OSM's ref. They are carried so a reviewer can name a
# row, nothing more.
ID_KEY = "ID"
SITE_ID_KEY = "SITEID"
ASSET_TYPE_KEY = "ASSETTYPE"     # columns: PPC (828) or Collar (6); boards: shelter model
# The City's status. Columns carry it in STATUS; for a shelter board the
# board's own state is POSTERBOARDSTATUS (STATUS is the shelter's).
# "Existing" or "Temporarily Removed" -- every row is kept, the status is shown.
STATUS_KEYS = {"column": "STATUS", "shelter_board": "POSTERBOARDSTATUS"}
ADDRESS_KEYS = ("ADDRESSNUMBERTEXT", "ADDRESSSTREET")
FRONTING_KEY = "FRONTINGSTREET"
FROM_KEY = "FROMSTREET"

# --- OSM comparison (gap-review page) ---
# Postering spots are pulled from OSM via Overpass and matched against the
# City points by distance, nearest pair first, one to one; the gaps feed
# build/site/gaps/.
#
# The mirror policy is the parks layer's, unchanged and for the same reasons:
# overpass.kumi.systems and overpass.private.coffee have both been caught
# serving months-stale data, which is the worse failure because it looks
# exactly like success. private.coffee did it with Guelph's hydrants on
# 2026-10-09: HTTP 200, a full reply, OSM as of 2026-05-31.
OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
)
OVERPASS_TIMEOUT = 300
OVERPASS_ROUNDS = 3
OVERPASS_ROUND_WAIT = 60
# Floor on a reply's element count. The first probe (2026-10-24) carried
# 1,153 elements -- every advertising=* and information board in the bbox,
# billboards and history plaques included -- and a reply under half that is a
# wrong-region or truncated answer. Taking an empty reply at face value would
# report all 2,496 City points as missing from OSM.
OSM_MIN_ELEMENTS = 575
# Oldest OSM data a reply may carry (its osm3s.timestamp_osm_base) and still be
# compared against. A healthy instance is minutes behind.
OSM_MAX_AGE_DAYS = 3
# Overpass rejects the default requests User-Agent (HTTP 406); identify the tool.
USER_AGENT = "toronto-poster-columns-layer/0.1 (toronto@comentality.com)"
# Toronto bounding box (S, W, N, E), toronto-parks-layer's. Every City point
# is inside it (checked 2026-10-24: none of the 2,496 outside).
TORONTO_BBOX = (43.58, -79.64, 43.86, -79.12)
# Downtown, where the City's columns are thickest; where the maps open.
TORONTO_CENTER = (43.6510, -79.3960)
OSM_CACHE_PATH = os.path.join(DATA_DIR, "osm-posters.json")
# When the cached Overpass reply was fetched, from where, and -- more usefully
# -- the OSM database timestamp the reply declares about itself.
OSM_FETCH_PATH = os.path.join(DATA_DIR, ".osm-fetch.json")
GAPS_GEOJSON_PATH = os.path.join(DATA_DIR, "gaps.geojson")
GAPS_COUNT_PATH = os.path.join(DATA_DIR, "gaps.count.json")

# What in OSM counts as one of these. Either tagging family is accepted, and
# the checker does not nag about which was used:
#   * any advertising=* (except "no"), and
#   * a board: tourism=information + information=board, or any
#     board_type=notice.
# Any of them answers for a City point it is paired with. Only the ones that
# could be a postering spot are reported when nothing pairs with them
# (osm_only) or when they sit beside a point already answered for
# (duplicate): an unpaired billboard or history plaque is just something
# else, and listing the city's 500-odd billboards as "OSM only" would bury
# the handful worth a look.
POSTERING_ADVERTISING = ("column", "pillar", "poster_box", "board")
POSTERING_BOARD_TYPES = ("notice",)
# Tags carried onto a gap row, so the page shows what matched.
OSM_TAGS_SHOWN = ("advertising", "tourism", "information", "board_type",
                  "operator", "name")

# Distances, in metres, hydrants' unchanged. Measured on 2026-10-24, the
# nearest accepted OSM feature to each City column: 176 within 5 m, 229
# within 10 m, 257 within 20 m, 273 within 30 m -- a flat tail past 10 m.
# Shelter boards: 7 / 15 / 45 / 68. Their curve is shallow because OSM maps
# the shelter (1,001 of 1,662 boards sit within 10 m of an OSM shelter), not
# the board on it. 19 of the 68 features within 30 m of a shelter board are
# advertising=billboard, most likely the shelter's own ad panel; the brief
# says any advertising=* answers, so they do, and the gap row names the tag.
#   NEAR_M -- an OSM feature this close is the City's: matched.
#   FAR_M  -- one between NEAR_M and this is "far": probably the same
#             structure, but one of the two points is in the wrong place. A
#             postering-type OSM feature within this of a City point that a
#             nearer one already took is a "duplicate"; beyond it, "osm_only".
NEAR_M = 10
FAR_M = 30

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

# --- Import chunks (import page) ---
# The City points missing from OSM, cut into JOSM-loadable chunks, one
# changeset each. The import's paperwork (the community discussion, the wiki
# page, the licence review) is someone else's; what is here is only the
# technical half, and every choice in it is meant to be reviewed there.
#
# A chunk holds at most this many new nodes. Nothing in JOSM or the OSM API
# comes near it (a changeset takes 10,000 changes); it is how many points a
# reviewer can check against imagery before uploading in one sitting.
IMPORT_MAX_PER_CHUNK = 250
# Node tags per kind. No ref and no City ID, deliberately: see "No ref, on
# purpose" in the README.
IMPORT_TAGS = {
    "column": {"advertising": "column", "operator": "City of Toronto"},
    "shelter_board": {"advertising": "board", "operator": "City of Toronto"},
}
# Changeset tags JOSM is handed with each chunk; the comment is per chunk.
IMPORT_CHANGESET_TAGS = {
    "source": "City of Toronto Open Data",
    "import": "yes",
}
IMPORT_COMMENT = "Import City of Toronto {what}, chunk {name} of {total}"
