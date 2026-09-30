# Flock Camera Cross-Reference Map

An interactive US map cross-referencing ALPR (Flock) camera locations
with county-level population/race, religion, and crime data, so patterns
between them can be visually explored.

**To view the live map, go to: https://flockcam-censusdata-referencemap.netlify.app/**

## What's on the map

- **Cameras** — ALPR camera locations from OpenStreetMap
- **Population** — total population and race/ethnicity breakdown, county-level (Census ACS)
- **Religion** — religious tradition breakdown, county-level (2020 U.S. Religion Census)
- **Crime** — hate crime rate (county-level, largest ~100 counties + state capitals) and general offense rate (state-level) (FBI Crime Data Explorer)

Each layer can be toggled and adjusted independently, and a "Focus state"
control dims every other state to help hone in on one area. See the
"Sources" section under each layer in the map's side panel for exact data
provenance and methodology notes.

## Project structure

- `data_pipeline/` — Python scripts that fetch and normalize each data source
- `data/output/` — the generated static site (what's actually deployed)

The site is static (no backend) - `data_pipeline/scripts/make_checkpoint_map.py`
regenerates `data/output/` from the processed data sources, and that folder
is what Netlify publishes.
## How it works

The site is fully static - no backend or database. Python scripts in
`data_pipeline/` fetch each source offline, normalize everything to a common
key (5-digit county FIPS code), and `make_checkpoint_map.py` generates the
site into `data/output/`, which Netlify publishes as-is (`netlify.toml`).

### Architecture

    OSM (Geofabrik PBFs) ──┐
    Census ACS API ────────┤
    Religion Census xlsx ──┼─► join to county geometry (FIPS) ─► make_checkpoint_map.py ─► data/output/ ─► Netlify
    FBI CDE API ───────────┘

**County geometry** — Census cartographic boundary file
`cb_2022_us_county_20m` (`utils/tiger_counties.py`). The generalized 20m file
is used instead of full TIGER/Line, which is ~350MB as GeoJSON and too heavy
for a browser.

### Data layers

| Layer | Source | Resolution | Pipeline |
|---|---|---|---|
| Cameras | OpenStreetMap via Geofabrik `.osm.pbf` extracts | Point | `scripts/extract_cameras_per_state.py`, `scripts/merge_camera_snapshots.py` |
| Population & race | Census ACS 5-Year 2020–2024 (`B01003`, `B02001`, `B03003`) | County | `pipelines/census_acs.py` |
| Religion | 2020 U.S. Religion Census (ASARB/ARDA) county summary + group detail | County | `pipelines/religion_census.py` |
| Crime | FBI Crime Data Explorer API, 2022–2023 | County (hate crime) / State (offense rates) | `pipelines/fbi_crime.py` |

**Cameras.** Points tagged `surveillance:type=ALPR` are extracted offline from
Geofabrik's per-state PBF files using pyrosm, instead of querying the live
Overpass API (which timed out and rate-limited at national scale). Per-state
files are needed because pyrosm builds a lookup of every node in the source
file first - running it on the full US file (~188M nodes) ran out of memory.
The 13 largest states still exceeded memory, so the deployed snapshot merges
the per-state extraction (38 states, with OSM IDs) with an earlier nationwide
osmium extraction for those 13 states (no OSM IDs, broader surveillance tags).
Each point is assigned a county by a GeoPandas spatial join.

**Population & race.** Race percentages are each group's share of total
county population. Hispanic/Latino comes from a separate table (`B03003`)
because Census treats it as an ethnicity, independent of race.

**Religion.** 372 reporting bodies are grouped into 12 traditions (Catholic,
Evangelical, Mainline, Historically Black Protestant, LDS, etc.). These
figures count adherents *claimed by congregations*, not survey
self-identification, so the leftover share is labeled "Not Claimed by Any
Religious Body" rather than "unaffiliated". Percentages are capped at 100%
(some counties report more adherents than residents).

**Crime.**
- *Hate crime* is built from real agency-level data (`/hate-crime/agency/{ori}`),
  matched to counties using the CDE agency directory, and converted to a rate
  per 100k per year. It covers only the 100 most populous counties plus each
  state capital's county, to limit API calls. Every other county is null and
  rendered as "no data" - never zero.
- *Offense rates* (violent, property, homicide, robbery, burglary, motor
  vehicle theft) come from the state endpoint and apply to every county in
  that state. The agency-level summary endpoint was found to return
  state-level numbers for every agency, so county precision isn't available.

### Frontend

`make_checkpoint_map.py` uses folium to generate a Leaflet page
(`checkpoint_map.html` + `checkpoint_map.js`) and writes each layer as its
own JSON file (`checkpoint_cameras.json`, `checkpoint_counties.json`,
`checkpoint_religion.json`, `checkpoint_crime.json`), which the page loads
in the browser.

- **Cameras:** Leaflet.markercluster with canvas rendering, so all ~151K
  points ship without sampling. Markers are colored by OSM `operator` and
  show a view cone when a camera direction is tagged.
- **County layers:** choropleths with quantile breaks, a variable selector,
  class count, and an opacity slider per layer. Null values are drawn in a
  separate gray "no data" style.
- **Focus state:** a visual mask that dims all other states; no data is
  filtered out.

### Rebuilding

API keys go in `credentials.txt` at the repo root (not committed):

    CENSUS_API_KEY=...
    DATA_GOV_API_KEY=...

    pip install -r data_pipeline/requirements.txt folium pyrosm
    python -m data_pipeline.pipelines.census_acs --vars B01003_001E,B02001_002E,B02001_003E,B02001_004E,B02001_005E,B02001_006E,B02001_008E,B03003_003E --out data/output/census_counties_population.geojson
    python -m data_pipeline.pipelines.religion_census --group-detail <2020_USRC_Group_Detail.xlsx> --county-summary <2020_USRC_Summaries.xlsx> --out data/output/religion_counties.geojson
    python data_pipeline/pipelines/fbi_crime.py
    python data_pipeline/scripts/extract_cameras_per_state.py
    python data_pipeline/scripts/merge_camera_snapshots.py
    python data_pipeline/scripts/make_checkpoint_map.py

### Known limitations

- Camera coverage is only as complete as OpenStreetMap's crowdsourced tagging.
  About 20K of the ~151K points are non-ALPR surveillance devices (general
  cameras, gunshot detectors) from the fallback extraction for the 13 largest
  states.
- About 125K cameras have no `operator` tag and show as "unknown".
- Intermediate snapshots and PBF files (`data/snapshots/`, `data/geofabrik/`)
  aren't committed; only the generated site in `data/output/` is.

### Attribution

Camera data © OpenStreetMap contributors, ODbL. Census and FBI data are
public domain. Religion data: 2020 U.S. Religion Census, ASARB.
