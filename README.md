# Flock Camera Cross-Reference Map

An interactive US map cross-referencing ALPR (Flock-style) camera locations
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
