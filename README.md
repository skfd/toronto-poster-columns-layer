# Toronto Poster Columns Layer

Turns the City of Toronto's two street-furniture postering datasets &mdash;
[Poster Structure](https://open.toronto.ca/dataset/street-furniture-poster-structure/)
(834 poster columns) and
[Poster Board](https://open.toronto.ca/dataset/street-furniture-poster-board/)
(1,662 poster boards on transit shelters) &mdash; into map-tile layers that
OpenStreetMap mappers can add to the **JOSM** and **iD** editors as a reference
overlay, plus a gap page listing where OSM disagrees with the City. These are
Toronto's community postering spots: the places you can pin a flyer.

**Live layer and how to add it: https://skfd.github.io/toronto-poster-columns-layer/**

It is a clone of [guelph-hydrants-layer](https://github.com/guelph-maps/guelph-hydrants-layer)
([live](https://guelph-maps.github.io/guelph-hydrants-layer/)): the same
`download -> slim -> compare -> vector -> raster -> site -> publish` pipeline,
the same Overpass, link-gate and publish rules. What differs follows from the
data:

- **download** is CKAN, not ArcGIS paging: each package is asked for its
  resource list (`package_show`), the WGS84 GeoJSON is picked out by name, and
  the two files are merged into one layer with a `kind` (`column` or
  `shelter_board`). A file under its floor (750 / 1,500) stops the run;
- **compare** accepts two OSM tagging families and reports position only;
- **raster** draws two colours, and rings for points the City lists as
  temporarily removed.

It was built because only 3 of the City's columns were tagged
`advertising=column` in OSM on 2026-10-24, and street-imagery detection can't
fill the gap: Mapillary has no class for these, Osmose has no check for them in
Canada, and Panoramax detects only faces, plates and road signs. City open data
is the only source. (Looking past the one tag, OSM turned out to have far more
of the columns than that: see the first run below.)

## What it produces

- **Vector tiles** (MVT, z12-19) &mdash; interactive in iD; click a point to
  read its `kind`, `id`, `site_id`, `asset_type`, `city_status`, `address`,
  `fronting` and `from_street`.
- **Raster tiles** (PNG, z15-17) &mdash; an orange dot per poster column and a
  blue one per shelter board, white edged, 5 px in radius at z17. A point the
  City lists as *Temporarily Removed* (94 columns, 28 boards) is a ring.
- A **landing page** with copy-paste "add this layer" instructions for both
  editors, and the postering-rules caveat below.
- A **gap-review page** (`/gaps/`) on an interactive map and a filterable
  table, and its **history page** (`/gaps/history.html`) charting the counts,
  one point per weekly run.

## Where you may post: the caveat

Toronto's sign by-law,
[Municipal Code Chapter 693](https://www.toronto.ca/legdocs/municode/1184_693.pdf),
keeps posters off City property except on "kiosks", structures the City has
designated for posting, and sets size, fixing and time limits for those
(&sect;&nbsp;693-5.2 and 5.3). The poster columns are those structures. **It is
unconfirmed whether the public may post on the shelter boards.** The landing
page says exactly that and no more.

The brief cited "art. IV"; in the consolidation of 2024-06-03, Article 4 is
Temporary Signs and postering is **Article 5** (Posters and Community Posters),
so the page cites &sect;&nbsp;693-5.2 and 5.3.

## No ref, on purpose

The City's `ID` (`PO-…` for columns, `SH-…` for shelters), `SITEID` and
`BARCODE` are asset numbers. A mapper standing at a column cannot check any of
them, so none belongs in OSM's `ref`. `id` and `site_id` are in the vector
tiles and on the gap page so a row can be named, and the landing page says not
to copy them.

## The gap page

Overpass is asked for everything in the Toronto bounding box that could be a
postering spot (`nwr`, `out center`):

```
nwr["advertising"];
nwr["tourism"="information"]["information"="board"];
nwr["board_type"="notice"];
```

**Either tagging family counts.** A City point is matched by any nearby
`advertising=*` (except `no`) **or** an information/notice board, and the
checker does not nag about which was used. City and OSM points are paired by
distance: every pair within `FAR_M` (30 m) is a candidate, and the closest
pair is settled first, one to one. Then, per City point:

| Status | Meaning | What to do |
|---|---|---|
| `missing` | nothing accepted within 30 m | add it, once you have seen it |
| `far` | its OSM feature is 10-30 m away | check which point is right |
| `duplicate` | a second postering-type OSM feature within 30 m, after a nearer one took this point | one of the two may be surplus |
| `osm_only` | a postering-type OSM feature more than 30 m from every City point | probably a private board -- a look, not a fix |

**Postering-type** means `advertising` = `column`, `pillar`, `poster_box` or
`board`, or `board_type=notice`. Any accepted feature can answer for a City
point, but only a postering-type one is reported when it is left over: an
unpaired billboard or history plaque is simply something else, and listing the
city's ~540 billboards as "OSM only" would bury the handful worth a look.

Each gap row carries the matched feature's `advertising` / `tourism` /
`information` / `board_type` / `operator` / `name`, so the page shows *what*
matched without judging it.

### Shelter boards: OSM has the shelter, not the board

Before settling the statuses, the boards were measured against what OSM has
around them (2026-10-24): **1,001 of the 1,662 shelter boards sit within 10 m
of an OSM shelter** (`amenity=shelter` or a stop with `shelter=yes`), and 1,420
within 10 m of a bus stop or platform &mdash; but only 15 within 10 m of any
accepted board or advertising tagging. A shelter is not a poster board, so it
does not count as a match, and the stops are not in the weekly query (13,000
elements, minutes on an Overpass that was at capacity that day). The finding
is stated on the landing page instead.

Of the features within 30 m of a shelter board, a third (19 of 68) were
`advertising=billboard` &mdash; most likely the shelter's own ad panel, not the
poster board. The brief says any `advertising=*` answers, so they do; the gap
row names the tag, and the counts below show how often it happens.

### Thresholds

`NEAR_M=10` / `FAR_M=30`, hydrants' unchanged. The nearest accepted OSM feature
to each column: 176 within 5 m, 229 within 10 m, 257 within 20 m, 273 within
30 m &mdash; a flat tail past 10 m. Shelter boards: 7 / 15 / 45 / 68.

Distances are equirectangular metres on a 0.0005&deg; grid, no GIS dependency.

The Overpass handling is the parks layer's unchanged: every mirror in
`OVERPASS_URLS` is tried `OVERPASS_ROUNDS` times, a reply under
`OSM_MIN_ELEMENTS` (575, half the first live reply) elements or older than
`OSM_MAX_AGE_DAYS` is refused, the page prints the OSM timestamp the mirror
declares, and a run that fell back to cached OSM says so on the page and exits
70 after publishing.

### What a first run looks like

The first live comparison, on 2026-10-24 against OSM as of 05:15Z (1,152
accepted OSM features, 2,496 City points; City data published 2026-02-20):

| | City | matched | missing | far | duplicate |
|---|--:|--:|--:|--:|--:|
| poster columns | 834 | 227 | 570 | 37 | 18 |
| shelter boards | 1,662 | 12 | 1,620 | 30 | 1 |
| **all** | **2,496** | **239** | **2,190** | **67** | **19** |

plus **28 `osm_only`** (17 `advertising=board`, 5 `poster_box`, 2 `column`,
2 `pillar`, 2 notice boards).

- **The columns are much better mapped than "3 in OSM" suggested.** 227 sit
  within 10 m of something: 155 `advertising=board`, 42 notice boards, 22
  `advertising=poster_box`, 4 information boards with no `board_type`, 2
  history boards, and one each `totem` and `billboard`. 109 of all the matched features carry
  `operator=City of Toronto`.
- **The shelter boards are almost unmapped as boards** (12 matched: 8
  `advertising=board`, one `billboard`, three information boards), though most
  of their shelters are in OSM.
- **The 67 `far` rows** are 37 columns (21 against `advertising=board`) and 30
  shelter boards, 18 of them against an `advertising=billboard` &mdash; the ad
  panel question again.
- **The duplicates** are mostly a column with two notice-board nodes 1-6 m
  apart: perhaps one node per face of the column. A look, not necessarily a
  fix.

## Setup

1. Install Python dependencies:
   ```
   pip install -r requirements.txt
   ```
2. Set up WSL2 + tippecanoe once &mdash; see [wsl-setup.md](wsl-setup.md).
3. GitHub Pages serves the `gh-pages` branch (root); it was switched on with
   `gh api -X POST repos/skfd/toronto-poster-columns-layer/pages`.

## Usage

```
python run.py download   # fetch both City GeoJSONs via CKAN (smart-cached)
python run.py slim       # normalise to a slim GeoJSONL
python run.py compare    # diff City points against OSM -> data/gaps.geojson
python run.py backfill   # one-off: reconstruct past weeks' gap counts from OSM history
python run.py vector     # build vector (MVT) tiles via WSL tippecanoe
python run.py raster     # build raster (PNG) tiles
python run.py site       # render the landing page (+ the gap-review page)
python run.py publish    # force-push the site to the gh-pages branch

python run.py build      # download + slim + compare + vector + raster + site
python run.py update     # build + publish  (the scheduled entry point)
```

Build output lands in `build/site/`; that directory is what gets published to
an orphan `gh-pages` branch, recreated on every build so history never grows.

## Tile endpoints

```
https://skfd.github.io/toronto-poster-columns-layer/tiles/vector/{z}/{x}/{y}.pbf   (z12-19)
https://skfd.github.io/toronto-poster-columns-layer/tiles/raster/{z}/{x}/{y}.png   (z15-17)
```

The vector layer name is `posters`. tippecanoe runs with `-r1`, so no point is
thinned out of the low zooms.

## Scheduling (Windows)

Run as Administrator:

```powershell
.\schedule-add.ps1      # registers a weekly task "kk-TorontoPosterColumnsLayer", Wednesdays 19:30
.\schedule-remove.ps1   # unregisters it
```

Every 16:30 slot is taken by a sibling, and the 19:30 ones on Monday and
Tuesday; Wednesday 19:30 is three hours after guelph-buildings-layer starts, so
no two of them drive tippecanoe in the same WSL instance at once. Exit codes
and the restart policy are the parks layer's: **75** when there is no usable
link (nothing was fetched or published), **70** after publishing when the gap
page had to fall back to cached OSM.

## Tests

```
python tests\test_tilemath.py
python tests\test_slim.py
python tests\test_raster.py
pytest                       # the above, plus the download / compare / history / publish tests
```

## Licence / attribution

Postering data is &copy; City of Toronto, published under the
[Open Government Licence &ndash; Toronto](https://open.toronto.ca/open-data-licence/),
which is ODbL-compatible and already accepted for the Toronto address import.

**This project redistributes City data** as published tiles on a public URL,
and the licence attaches a required attribution to that. The landing page, the
gap page and the history page all carry, visibly:

> Contains information licensed under the Open Government Licence – Toronto.

linked to the licence text. The tile metadata carries
"(c) City of Toronto, Open Government Licence - Toronto". This is a condition
of use, not a courtesy: if you fork this, the notice travels with it.

This is not an import: the layer puts the City's points in front of a mapper,
who adds what they have seen.
