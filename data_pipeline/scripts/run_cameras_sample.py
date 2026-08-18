"""Download TIGER counties and run a small camera sample.

This tries a live Overpass query first. If the public Overpass service is
timing out or rate-limiting, it falls back to a synthetic sample anchored to a
known county from the TIGER file so the end-to-end pipeline still produces a
valid GeoJSON output in the repo.

Produces `data/output/cameras_sample.geojson`.
"""
import json
import sys
from pathlib import Path

import geopandas as gpd
from shapely.geometry import Point

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_pipeline.utils.tiger_counties import download_and_prepare
from data_pipeline.pipelines.overpass_cameras import run


def generate_synthetic_sample(counties_path: Path, outpath: Path):
    counties = gpd.read_file(str(counties_path)).to_crs(epsg=4326)
    if 'GEOID' in counties.columns:
        counties['county_fips'] = counties['GEOID'].astype(str)
    elif 'STATEFP' in counties.columns and 'COUNTYFP' in counties.columns:
        counties['county_fips'] = counties['STATEFP'].astype(str).str.zfill(2) + counties['COUNTYFP'].astype(str).str.zfill(3)
    else:
        raise RuntimeError('County file missing GEOID/STATEFP+COUNTYFP columns')

    sf = counties[counties['GEOID'].astype(str).apply(lambda x: x == '06075')]
    if sf.empty:
        sf = counties.iloc[[0]].copy()

    geom = sf.geometry.iloc[0]
    centroid = geom.centroid
    deltas = [(-0.003, -0.002), (0.001, 0.004), (0.005, -0.001)]
    points = [Point((centroid.x + dx, centroid.y + dy)) for dx, dy in deltas]
    features = []
    demo_fips = sf['county_fips'].iloc[0]
    for idx, point in enumerate(points):
        features.append({
            'type': 'Feature',
            'geometry': {'type': 'Point', 'coordinates': [point.x, point.y]},
            'properties': {
                'camera_id': f'demo_{idx + 1}',
                'county_fips': str(demo_fips),
                'source': 'synthetic_demo',
                'surveillance:type': 'ALPR',
            },
        })
    outpath.parent.mkdir(parents=True, exist_ok=True)
    outpath.write_text(json.dumps({'type': 'FeatureCollection', 'features': features}))
    print(f'Wrote synthetic sample with {len(features)} points to {outpath}')


def maybe_run_live_sample(counties_path: Path, outpath: Path):
    bbox = (37.75, -122.45, 37.80, -122.39)
    try:
        run(str(outpath), bbox=bbox, counties_path=str(counties_path))
        return True
    except Exception as exc:  # pragma: no cover - live API fallback
        print(f'Live Overpass query failed ({type(exc).__name__}: {exc}). Falling back to synthetic sample.')
        return False


def main():
    repo_root = Path(__file__).resolve().parents[2]
    outpath = repo_root / 'data' / 'output' / 'cameras_sample.geojson'
    counties_path = repo_root / 'data' / 'tiger_counties.geojson'
    if not counties_path.exists():
        counties_path = download_and_prepare(output_path=counties_path)
    if not maybe_run_live_sample(counties_path, outpath):
        generate_synthetic_sample(counties_path, outpath)


if __name__ == '__main__':
    main()
