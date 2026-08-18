"""Single-pass nationwide ALPR camera extraction, with real OSM node/way IDs.

The dataset the map currently ships (cameras_snapshot_20260816T144158Z_osmium.geojson)
never captured OSM IDs, so its popups could never link back to the source OSM
feature - any link built from it points at a nonexistent node/way page (this was
already flagged and worked around once by removing the broken link entirely).

Earlier attempts at a full-US extraction used a tile-by-tile chunked approach
(geofabrik_us_snapshot_chunked.py) specifically to manage memory, at the cost of
taking multiple days (each tile re-scans overlapping regions of an 11GB file). A
quick test here showed a single unchunked pass over a small, freshly-downloaded
PBF succeeds in ~12s for 50MB with real `id`/`osm_type` present - scaling that
rate to the full ~11GB US PBF suggests well under an hour for one sequential
pass, which is what this script does instead of tiling.
"""
from pathlib import Path
from datetime import datetime
import json
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pyrosm import OSM
import geopandas as gpd
import pandas as pd

PBF_PATH = ROOT / 'data' / 'geofabrik' / 'us-latest.osm.pbf'
SNAP_DIR = ROOT / 'data' / 'snapshots'


def assign_counties(gdf):
    from data_pipeline.utils.tiger_counties import download_and_prepare
    counties_path = ROOT / 'data' / 'tiger_counties.geojson'
    if not counties_path.exists():
        download_and_prepare(output_path=counties_path)
    counties = gpd.read_file(str(counties_path)).to_crs(epsg=4326)
    if 'GEOID' in counties.columns:
        counties['county_fips'] = counties['GEOID'].astype(str)
    else:
        counties['county_fips'] = counties['STATEFP'].astype(str).str.zfill(2) + counties['COUNTYFP'].astype(str).str.zfill(3)
    pts = gdf[gdf.geometry.notna()].copy()
    joined = gpd.sjoin(gpd.GeoDataFrame(pts, geometry='geometry', crs='EPSG:4326'),
                        counties[['county_fips', 'geometry']], how='left', predicate='within')
    joined['county_fips'] = joined['county_fips'].astype(str)
    return joined


def main():
    if not PBF_PATH.exists():
        raise SystemExit(f'PBF missing: {PBF_PATH}')

    t0 = time.time()
    print(f'Reading {PBF_PATH} ({PBF_PATH.stat().st_size / 1e9:.2f} GB)...', flush=True)
    osm = OSM(str(PBF_PATH))
    pois = osm.get_pois(
        custom_filter={'surveillance:type': ['ALPR']},
        extra_attributes=['id', 'operator', 'camera:type', 'camera:brand', 'camera:direction',
                           'direction', 'camera:orientation', 'surveillance:type', 'source']
    )
    print(f'Extracted {len(pois)} POIs in {time.time()-t0:.0f}s', flush=True)

    joined = assign_counties(pois)
    print(f'County-joined {len(joined)} features', flush=True)

    features = []
    for _, row in joined.iterrows():
        geom = row.geometry
        if geom is None:
            continue
        props = {
            'osm_id': int(row['id']) if pd.notna(row.get('id')) else None,
            'osm_type': row.get('osm_type') or 'node',
            'operator': row.get('operator'),
            'source': row.get('source'),
            'surveillance:type': row.get('surveillance:type'),
            'camera:type': row.get('camera:type'),
            'camera:brand': row.get('camera:brand'),
            'camera:direction': row.get('camera:direction'),
            'direction': row.get('direction'),
            'camera:orientation': row.get('camera:orientation'),
            'county_fips': row.get('county_fips'),
        }
        features.append({'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [float(geom.x), float(geom.y)]}, 'properties': props})

    ts = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    out_geo = SNAP_DIR / f'cameras_snapshot_{ts}_pyrosm_withid.geojson'
    out_manifest = SNAP_DIR / f'cameras_snapshot_{ts}_pyrosm_withid.manifest.json'
    with open(out_geo, 'w', encoding='utf-8') as fh:
        json.dump({'type': 'FeatureCollection', 'features': features}, fh)
    with open(out_manifest, 'w', encoding='utf-8') as fh:
        json.dump({'created_at': ts, 'source': 'pyrosm_us_withid', 'file': str(out_geo.relative_to(ROOT)).replace('\\', '/'),
                    'feature_count': len(features)}, fh)
    print(f'Wrote {len(features)} features to {out_geo} in {time.time()-t0:.0f}s total', flush=True)


if __name__ == '__main__':
    main()
