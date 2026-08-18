#!/usr/bin/env python3
"""Assign county FIPS to osmium-extracted cameras and write snapshot + manifest."""
import json
from pathlib import Path
from datetime import datetime
import sys

# Ensure repo root is on sys.path when run as a script
repo = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo))

from data_pipeline.pipelines import overpass_cameras


def main():
    repo = Path(__file__).resolve().parents[2]
    src = repo / 'data' / 'snapshots' / 'cameras.geojson'
    if not src.exists():
        raise SystemExit(f'Input not found: {src}')

    with open(src, 'r', encoding='utf8') as fh:
        fc = json.load(fh)

    counties_path = repo / 'data' / 'tiger_counties.geojson'
    counties = overpass_cameras.load_counties_geojson(counties_path)
    # Perform spatial join here to avoid geopandas version NA attribute issues
    import geopandas as gpd
    import pandas as pd
    from shapely.geometry import Point

    features = fc.get('features', [])
    pts = [Point(f['geometry']['coordinates']) for f in features]
    props = [f.get('properties', {}) for f in features]
    gdf = gpd.GeoDataFrame(props, geometry=pts, crs='EPSG:4326')
    joined = gpd.sjoin(gdf, counties[['county_fips', 'geometry']], how='left', predicate='within')
    out_features = []
    for idx, row in joined.iterrows():
        p = features[idx]
        properties = p.get('properties', {})
        cf = row.get('county_fips')
        if cf is not None and not pd.isna(cf):
            properties['county_fips'] = str(cf)
        else:
            properties['county_fips'] = None
        out_features.append({'type': 'Feature', 'geometry': p['geometry'], 'properties': properties})
    assigned = {'type': 'FeatureCollection', 'features': out_features}

    ts = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    out_dir = repo / 'data' / 'snapshots'
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f'cameras_snapshot_{ts}_osmium.geojson'
    with open(out_file, 'w', encoding='utf8') as fh:
        json.dump(assigned, fh)

    manifest = {
        'created_at': ts,
        'source': 'osmium_us',
        'file': str(out_file).replace('\\', '/'),
        'feature_count': len(assigned.get('features', [])),
    }
    manifest_file = out_dir / f'cameras_snapshot_{ts}_osmium.manifest.json'
    with open(manifest_file, 'w', encoding='utf8') as fh:
        json.dump(manifest, fh)

    print('Wrote snapshot', out_file)
    print('Wrote manifest', manifest_file)
    print('feature_count', manifest['feature_count'])


if __name__ == '__main__':
    main()
