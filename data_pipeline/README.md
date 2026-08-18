# Data pipeline — Phase 1

This folder contains scripts to pull and normalize public data sources into
county-level GeoJSON as described in PROJECT_CONTEXT.md.

Run individual pipeline scripts under `pipelines/`. Each script exposes a
`run()` function and accepts command-line args for input/output paths.
