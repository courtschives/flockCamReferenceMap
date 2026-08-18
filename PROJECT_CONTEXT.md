# Surveillance/Demographic Overlay Map — Project Context

## Goal
Build a public, interactive US web map that overlays ALPR (Flock-style) camera
locations with public demographic datasets (population, race, crime, religion,
voting patterns, LGBTQ+ population estimates) so users can toggle layers on/off
and control opacity to visually identify overlap/patterns. Modeled loosely on
dontgetflocked.com/maps (FlockHopper) but with multiple demographic layers,
not just cameras.

v1 priority: FUNCTIONAL, not polished. Aesthetics/UX pass comes later.

## Architecture
- Static site, no backend/database. All data pre-processed offline into
  static tile files, hosted on a CDN.
- Frontend: MapLibre GL JS (open-source, no licensing fees) — handles
  layer toggling and per-layer opacity via native paint properties.
- Tile format: PMTiles (single static archive per layer, built with
  `tippecanoe`), so no tile server is needed — just static file hosting.
- Hosting: Netlify (already connected to GitHub).
- Data pipeline: offline scripts (Python recommended — `pandas`,
  `geopandas`) that pull each source, normalize to a common geography key
  (county FIPS code; state FIPS for the LGBTQ+ layer, since that's the
  finest public resolution available), and export GeoJSON → PMTiles.
  Cameras are the one point-level layer; everything else is county (or
  state) choropleth fill.

## Data sources (confirmed current as of Aug 2026)

| Layer | Source | Resolution | Access | Notes |
|---|---|---|---|---|
| ALPR cameras | OpenStreetMap Overpass API, query `surveillance:type=ALPR` | Point | No key | ~128K US points; large queries need chunking by region to avoid Overpass timeouts |
| Population, race/ethnicity | Census Bureau ACS 5-Year Estimates, 2020–2024 vintage (released Jan 29, 2026) | Tract/block group | Census API key | Use tract or county depending on join strategy |
| Crime | FBI Crime Data Explorer (NIBRS) | Agency/county | api.data.gov key | Coverage is uneven — not all agencies report; must be flagged in UI, not treated as "low crime" |
| Religion | ARDA U.S. Religion Census | County | Free bulk download | Most recent conducted: 2020 (next is 2030) |
| Voting patterns | MIT Election Data & Science Lab, county returns | County/precinct | Free (Harvard Dataverse account for bulk file) | Using election RESULTS, not party registration — registration data is state-dependent, patchy, sometimes fee-gated |
| LGBTQ+ population | Williams Institute (UCLA), Gallup-based estimates | State / MSA ONLY | Free download, no key | Hard resolution ceiling — no finer public dataset exists; do not attempt to disaggregate below state/MSA |

## Build phases
1. Data pipeline scripts — one per source, normalize to county FIPS, output GeoJSON
2. Tile generation — GeoJSON → PMTiles via tippecanoe
3. Frontend — MapLibre site: base map, layer list, toggle + opacity slider per layer
4. Sources/attribution page — generated from a manifest (origin, vintage, license per layer)
5. Local testing — verify each layer renders/toggles correctly
6. Deploy — GitHub → Netlify

## Known risks / open issues
- Overpass API size/rate limits on full-US camera queries — needs chunked queries
- Crime layer has real reporting gaps, not just sparse data — must be visually/textually flagged
- Full census-tract-resolution PMTiles nationwide (~85K tracts) may be large; consider starting at county level, adding tract detail later
- Attribution/license requirements differ per source (OSM is ODbL — attribution + share-alike; Census/FBI are public domain; MIT Election Lab and Williams Institute expect citation) — must be respected before public launch
- LGBTQ+ layer must stay at state/MSA level — this is a data-availability constraint, not a stylistic choice

## Current status
Planning complete, moving execution to VS Code agent. API keys obtained
(Census, api.data.gov). GitHub + Netlify accounts set up and linked.
No code written yet.