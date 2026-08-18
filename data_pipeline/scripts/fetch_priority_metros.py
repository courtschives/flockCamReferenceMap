"""Fetch ALPR camera points for a prioritized list of US metro bboxes.

This is a fast-path to get real camera data onto the map quickly by
targeting major metro areas first instead of a full-US run.
"""
from pathlib import Path
import json
from datetime import datetime
import sys
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_pipeline.pipelines.overpass_cameras import fetch_overpass, load_counties_geojson, assign_county_fips

METROS = {
    'new_york': (40.4774, -74.2591, 40.9176, -73.7004),
    'los_angeles': (33.7037, -118.6682, 34.3373, -118.1553),
    'chicago': (41.6445, -87.9401, 42.0230, -87.5237),
    'san_francisco': (37.6391, -123.1738, 37.9298, -122.2818),
    'washington_dc': (38.7916, -77.1198, 39.0030, -76.9094),
    'boston': (42.2279, -71.1912, 42.4704, -70.9222),
    'seattle': (47.4910, -122.4594, 47.7341, -122.2247),
    'miami': (25.7099, -80.5540, 25.9426, -80.1393),
    'atlanta': (33.6407, -84.5518, 33.9126, -84.2897),
    'philadelphia': (39.8670, -75.2803, 40.1379, -74.9558),
}


def chunk_bbox_grid(south, west, north, east, step_deg=0.5):
    lat = south
    while lat < north:
        lon = west
        lat2 = min(lat + step_deg, north)
        while lon < east:
            lon2 = min(lon + step_deg, east)
            yield (lat, lon, lat2, lon2)
            lon += step_deg
        lat += step_deg


def main(out_path=None, delay=1.0, metros=None):
    repo_root = Path(__file__).resolve().parents[2]
    out_dir = repo_root / 'data' / 'output'
    out_dir.mkdir(parents=True, exist_ok=True)
    if out_path is None:
        out_path = out_dir / 'cameras_priority_metros.geojson'
    else:
        out_path = Path(out_path)

    all_features = []
    if metros is None:
        metros = ['san_francisco', 'los_angeles', 'new_york', 'chicago']
    for name in metros:
        bbox = METROS.get(name)
        if bbox is None:
            print(f'Unknown metro: {name}')
            continue
        print(f'Fetching metro {name} bbox={bbox}')
        # subdivide into small tiles for reliability
        for tbbox in chunk_bbox_grid(*bbox, step_deg=0.5):
            try:
                fc = fetch_overpass(tbbox)
                feats = fc.get('features', [])
                if feats:
                    print(f'  tile {tbbox} got {len(feats)} features')
                    all_features.extend(feats)
            except Exception as e:
                print(f'  tile fetch failed for {tbbox}: {e}')
            finally:
                import time
                time.sleep(delay)

    combined = {'type': 'FeatureCollection', 'features': all_features}
    counties_path = repo_root / 'data' / 'tiger_counties.geojson'
    if counties_path.exists():
        try:
            counties = load_counties_geojson(str(counties_path))
            combined = assign_county_fips(combined, counties)
        except Exception as e:
            print(f'County assignment failed: {e}')

    out_path.write_text(json.dumps(combined))
    print(f'Wrote {len(combined.get("features", []))} features to {out_path}')


if __name__ == '__main__':
    main()
