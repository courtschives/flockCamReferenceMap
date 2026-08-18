"""Run a small Census ACS sample: fetch total population and write county GeoJSON.

Produces `data/output/census_counties_population.geojson` and CSV.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_pipeline.pipelines.census_acs import run


def main():
    repo_root = Path(__file__).resolve().parents[2]
    outpath = repo_root / 'data' / 'output' / 'census_counties_population.geojson'
    # B01003_001E — total population estimate
    run(['B01003_001E'], str(outpath))


if __name__ == '__main__':
    main()
