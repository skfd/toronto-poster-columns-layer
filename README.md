# Toronto Poster Columns Layer

**Status: empty, nothing built yet.** This README is the brief.

## Goal

A reference overlay of Toronto's **community postering spots**, the places where you
can pin a flyer, for OSM mappers in **JOSM** and **iD**. It comes with a **gap checker**
that lists where OpenStreetMap disagrees with the City. It is the same kind of project
as [`guelph-hydrants-layer`](../guelph-hydrants-layer) (live:
https://guelph-maps.github.io/guelph-hydrants-layer/): vector + raster tiles, a landing
page with "add this layer" instructions, a `/gaps/` page with an interactive map and a
filterable table, and a `/gaps/history.html` chart with one point per weekly run.

It is **not** an import. It is a layer to trace against plus a to-do list. Nothing is
uploaded to OSM.

## Why it is worth it

The City publishes 834 poster columns. On 2026-10-24 OSM had **3** `advertising=column`
in all of Toronto, one with `operator=Astral`. The rest of OSM's 760 `advertising=*` are
billboards (469), boards (221), poster boxes (34) and a few others. Street-imagery
detection can't fill the gap: Mapillary has no class for these, Osmose has no check for
them in Canada, and Panoramax detects only faces, plates and road signs.

## Decisions already made (2026-10-24, with the user)

- **Template:** clone `guelph-hydrants-layer` as the starting commit, the way it was
  cloned from `guelph-bus-stops-layer`. Keep its pipeline
  `download -> slim -> compare -> vector -> raster -> site -> publish`, its tests, and its
  Overpass, link-gate and publish rules. Change only what the data forces.
- **Scope: both City datasets**, in one layer with a `kind` property and two colours:
  - [Street Furniture – Poster Structure](https://open.toronto.ca/dataset/street-furniture-poster-structure/):
    834 rows (740 `Existing`, 94 `Temporarily Removed`); `ASSETTYPE` is `PPC` (828,
    the postering columns) or `Collar` (6). WGS84 CSV:
    `https://ckan0.cf.opendata.inter.prod-toronto.ca/dataset/ccfdb139-b54f-44f9-a1d7-2dde870baaaa/resource/18937890-dcdb-4e04-b341-b16c553d4c46/download/poster-structure-data-4326.csv`
    (a GeoJSON exists in the same package).
  - [Street Furniture – Poster Board](https://open.toronto.ca/dataset/street-furniture-poster-board/):
    1,662 poster boards on transit shelters (IDs `SH-…`), with `STATUS` and
    `POSTERBOARDSTATUS`. WGS84 CSV:
    `https://ckan0.cf.opendata.inter.prod-toronto.ca/dataset/cf706a1d-ef97-4865-b55a-e52432615ba6/resource/b6696467-54d4-4b5b-acff-5b9085d94ff9/download/poster-board-data-4326.csv`
  - Shared fields: `ID`, `ADDRESSNUMBERTEXT`, `ADDRESSSTREET`, `FRONTINGSTREET`, `SIDE`,
    `FROMSTREET`, `DIRECTION`, `SITEID`, `WARD`, `BIA`, `ASSETTYPE`, `STATUS`, `BARCODE`.
    Geometry is a one-point `MultiPoint` in a JSON string.
  - Download is CKAN static, not ArcGIS paging. Resolve the resource URLs through
    `package_show` (`street-furniture-poster-structure`, `street-furniture-poster-board`)
    rather than hard-coding the resource ids, and refuse a pull that falls short of a
    floor (as hydrants does).
- **OSM side: accept either tagging family.** A City feature counts as matched by any
  nearby `advertising=*` **or** a notice board (`tourism=information` +
  `information=board`, or any `board_type=notice`). The checker reports position
  (missing / far / duplicate / osm_only) and does **not** nag about which tag was used.
  Distance thresholds start from hydrants' `NEAR_M=10` / `FAR_M=30`. Re-check them
  against the data: shelter boards sit on a shelter OSM may map as a bus stop or
  `amenity=shelter`, so look at what is actually there before settling a status set.
- **No `ref`.** City `ID`/`SITEID`/`BARCODE` are asset numbers, shown in tiles and on the
  gap page to name a row, never suggested for OSM. Same reasoning as hydrants.
- **Caveat to carry onto the landing page:** the City's postering rules (Municipal Code
  ch. 693, art. IV) allow posters only on City-designated structures. It is
  **unconfirmed** whether the public may post on shelter boards. The columns are the safe
  claim. Don't assert more than that.
- **Home:** public repo `skfd/toronto-poster-columns-layer`, Pages at
  `https://skfd.github.io/toronto-poster-columns-layer/`, alongside the other
  `skfd/toronto-*-layer` repos. Count visits under the shared `osm-toronto` GoatCounter
  site (copy the snippet from `toronto-waterways-layer`'s latest commit).
- **Hands-off authorised:** create the GitHub repo, push, turn on Pages, and register a
  weekly `kk-TorontoPosterColumnsLayer` scheduled task (copy hydrants'
  `schedule-add.ps1`). Licence is Open Government Licence – Toronto; attribution
  "(c) City of Toronto, Open Government Licence - Toronto".

## Done looks like

- Live landing page with working iD and JOSM tile URLs, checked in a browser at a few
  downtown spots against the City's points.
- `/gaps/` filled in from a real Overpass pull, with first-run counts written into this
  README (replacing the empty status line above).
- Tests pass. The weekly task is registered, and one manual `run.py update` has succeeded
  end to end.
