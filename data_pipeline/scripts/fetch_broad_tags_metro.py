"""Fetch nodes in a metro bbox matching several camera-related OSM tags.

Writes to `data/output/cameras_priority_metros.geojson`.
"""
from pathlib import Path
import json
import sys
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_pipeline.pipelines.overpass_cameras import load_counties_geojson, assign_county_fips
import requests

SF_BBOX = (37.6391, -123.1738, 37.9298, -122.2818)


def fetch_broad(bbox):
    south, west, north, east = bbox
    # Query multiple keys that may indicate cameras
    query = (
        f'[out:json];('
        f'node["surveillance"]({south},{west},{north},{east});'
        f'node["surveillance:type"]({south},{west},{north},{east});'
        f'node["camera"]({south},{west},{north},{east});'
        f'node["traffic_camera"]({south},{west},{north},{east});'
        f'node["monitoring"]({south},{west},{north},{east});'
        f');out tags;'
    )
    headers = {'User-Agent': 'Mozilla/5.0 (compatible; FlockMap/1.0)', 'Accept': 'application/json'}
    OVERPASS_URLS = [
        'https://overpass-api.de/api/interpreter',
        'https://lz4.overpass-api.de/api/interpreter',
        'https://overpass.kumi.systems/api/interpreter',
    ]
    last_exc = None
    data = None
    for overpass in OVERPASS_URLS:
        try:
            resp = requests.post(overpass, data={'data': query}, headers=headers, timeout=120)
            resp.raise_for_status()
            data = resp.json()
            break
        except Exception as e:
            last_exc = e
            continue
    if data is None:
        raise last_exc
    features = []
    for el in data.get('elements', []):
        if el.get('type') == 'node' and 'lat' in el and 'lon' in el:
            features.append({'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [el['lon'], el['lat']]}, 'properties': {**(el.get('tags') or {}), 'osm_id': el.get('id')}})
    return {'type': 'FeatureCollection', 'features': features}


def main():
    repo_root = Path(__file__).resolve().parents[2]
    out_dir = repo_root / 'data' / 'output'
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / 'cameras_priority_metros.geojson'

    print('Fetching broad-tag SF bbox...')
    try:
        fc = fetch_broad(SF_BBOX)
        feats = fc.get('features', [])
        print(f'Got {len(feats)} features')
    except Exception as e:
        print('Fetch failed:', e)
        feats = []

    combined = {'type': 'FeatureCollection', 'features': feats}
    counties_path = repo_root / 'data' / 'tiger_counties.geojson'
    if counties_path.exists() and feats:
        try:
            counties = load_counties_geojson(str(counties_path))
            combined = assign_county_fips(combined, counties)
        except Exception as e:
            print('County assignment failed:', e)

    out_path.write_text(json.dumps(combined))
    print('Wrote', len(combined.get('features', [])), 'features to', out_path)


if __name__ == '__main__':
    main()
