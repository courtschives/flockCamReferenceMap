"""Aggressively fetch ALPR camera points for a single metro bbox with retries.

Targets San Francisco by default. Writes `data/output/cameras_priority_metros.geojson`.
"""
from pathlib import Path
import json
import time
import sys
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_pipeline.pipelines.overpass_cameras import fetch_overpass, load_counties_geojson, assign_county_fips

SF_BBOX = (37.6391, -123.1738, 37.9298, -122.2818)


def main(bbox=SF_BBOX, out_name='cameras_priority_metros.geojson'):
    repo_root = Path(__file__).resolve().parents[2]
    out_dir = repo_root / 'data' / 'output'
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / out_name

    attempts = 5
    delay = 5
    all_features = []
    for attempt in range(attempts):
        try:
            print(f'Attempt {attempt+1}/{attempts} fetching bbox={bbox}')
            fc = fetch_overpass(bbox)
            feats = fc.get('features', [])
            print(f'  got {len(feats)} features')
            all_features.extend(feats)
            if feats:
                break
        except Exception as e:
            print(f'  fetch error: {e}')
        time.sleep(delay)

    combined = {'type': 'FeatureCollection', 'features': all_features}
    counties_path = repo_root / 'data' / 'tiger_counties.geojson'
    if counties_path.exists() and all_features:
        try:
            counties = load_counties_geojson(str(counties_path))
            combined = assign_county_fips(combined, counties)
        except Exception as e:
            print(f'County assignment failed: {e}')

    out_path.write_text(json.dumps(combined))
    print(f'Wrote {len(combined.get("features", []))} features to {out_path}')


if __name__ == '__main__':
    main()
