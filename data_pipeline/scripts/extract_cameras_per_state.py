"""Per-state ALPR camera extraction with real OSM IDs - resumable.

Root cause of why the whole-US single-pass approach (extract_cameras_with_ids.py)
and bbox-chunked approaches over us-latest.osm.pbf both failed: pyrosm's PBF
reader builds a lookup table of every node in the SOURCE FILE (188 million
nodes for the full US) before any bounding_box filtering is applied - so
bbox-chunking the *same* nationwide file never helps, every chunk pays the
same fixed cost. Real fix: use files that are genuinely smaller at the
source. Geofabrik publishes one PBF per US state; each is scoped to that
state's actual node count, so no chunk ever approaches the 188M-node problem.
Confirmed on the smallest case (Rhode Island, 49.5MB): 12 seconds, no issue.

Resumable: downloads and per-state results are both cached to disk and
skipped on a re-run, so this can be safely re-launched if interrupted.
"""
from pathlib import Path
from datetime import datetime
import json
import sys
import time

import requests
import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pyrosm import OSM

RAW_DIR = ROOT / 'data' / 'raw' / 'state_pbfs'
PARTIAL_DIR = ROOT / 'data' / 'snapshots' / 'state_partials'
SNAP_DIR = ROOT / 'data' / 'snapshots'
RAW_DIR.mkdir(parents=True, exist_ok=True)
PARTIAL_DIR.mkdir(parents=True, exist_ok=True)

GEOFABRIK_BASE = 'https://download.geofabrik.de/north-america/us'

# Geofabrik's US state PBF slugs (DC is bundled into "district-of-columbia").
STATE_SLUGS = [
    'alabama', 'alaska', 'arizona', 'arkansas', 'california', 'colorado', 'connecticut',
    'delaware', 'district-of-columbia', 'florida', 'georgia', 'hawaii', 'idaho', 'illinois',
    'indiana', 'iowa', 'kansas', 'kentucky', 'louisiana', 'maine', 'maryland', 'massachusetts',
    'michigan', 'minnesota', 'mississippi', 'missouri', 'montana', 'nebraska', 'nevada',
    'new-hampshire', 'new-jersey', 'new-mexico', 'new-york', 'north-carolina', 'north-dakota',
    'ohio', 'oklahoma', 'oregon', 'pennsylvania', 'rhode-island', 'south-carolina',
    'south-dakota', 'tennessee', 'texas', 'utah', 'vermont', 'virginia', 'washington',
    'west-virginia', 'wisconsin', 'wyoming',
]


def download_state_pbf(slug, retries=3):
    dest = RAW_DIR / f'{slug}.osm.pbf'
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    url = f'{GEOFABRIK_BASE}/{slug}-latest.osm.pbf'
    tmp = dest.with_suffix('.pbf.part')
    last_exc = None
    for attempt in range(retries):
        print(f'  Downloading {slug}{" (retry " + str(attempt) + ")" if attempt else ""}...', flush=True)
        try:
            resp = requests.get(url, stream=True, timeout=300)
            resp.raise_for_status()
            with open(tmp, 'wb') as fh:
                for chunk in resp.iter_content(chunk_size=1024 * 1024):
                    fh.write(chunk)
            tmp.rename(dest)
            return dest
        except Exception as exc:
            last_exc = exc
            print(f'  Download failed ({exc}), will retry' if attempt < retries - 1 else f'  Download failed after {retries} attempts', flush=True)
            tmp.unlink(missing_ok=True)
            time.sleep(3 * (attempt + 1))
    raise last_exc


def extract_state(slug, counties_gdf, name_col, state_col):
    out_path = PARTIAL_DIR / f'{slug}.geojson'
    if out_path.exists():
        return json.loads(out_path.read_text(encoding='utf-8'))['features']

    pbf_path = download_state_pbf(slug)
    t0 = time.time()
    osm = OSM(str(pbf_path))
    pois = osm.get_pois(
        custom_filter={'surveillance:type': ['ALPR']},
        extra_attributes=['id', 'operator', 'camera:type', 'camera:brand', 'camera:direction',
                           'direction', 'camera:orientation', 'surveillance:type', 'source']
    )
    if pois is None or len(pois) == 0:
        out_path.write_text(json.dumps({'type': 'FeatureCollection', 'features': []}), encoding='utf-8')
        print(f'  {slug}: 0 features ({time.time()-t0:.0f}s)', flush=True)
        return []

    pts = pois[pois.geometry.notna()].copy()
    # Some ALPR features are mapped as ways (LineString/Polygon), not a single node -
    # collapse those to their centroid so every downstream geometry is a Point and
    # `geom.x`/`geom.y` is always valid (this crashed on ~9 states before the fix).
    non_point = pts.geometry.geom_type != 'Point'
    if non_point.any():
        pts.loc[non_point, 'geometry'] = pts.loc[non_point, 'geometry'].centroid
    joined = gpd.sjoin(gpd.GeoDataFrame(pts, geometry='geometry', crs='EPSG:4326'),
                        counties_gdf[['county_fips', 'geometry']], how='left', predicate='within')

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
            'county_fips': str(row['county_fips']) if pd.notna(row.get('county_fips')) else None,
        }
        features.append({'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [float(geom.x), float(geom.y)]}, 'properties': props})

    out_path.write_text(json.dumps({'type': 'FeatureCollection', 'features': features}), encoding='utf-8')
    print(f'  {slug}: {len(features)} features ({time.time()-t0:.0f}s)', flush=True)
    return features


def main():
    from data_pipeline.utils.tiger_counties import download_and_prepare
    counties_path = ROOT / 'data' / 'tiger_counties.geojson'
    if not counties_path.exists():
        download_and_prepare(output_path=counties_path)
    counties_gdf = gpd.read_file(str(counties_path)).to_crs(epsg=4326)
    if 'GEOID' in counties_gdf.columns:
        counties_gdf['county_fips'] = counties_gdf['GEOID'].astype(str)
    else:
        counties_gdf['county_fips'] = counties_gdf['STATEFP'].astype(str).str.zfill(2) + counties_gdf['COUNTYFP'].astype(str).str.zfill(3)
    name_col = 'NAME' if 'NAME' in counties_gdf.columns else 'NAMELSAD'
    state_col = 'STATE_NAME' if 'STATE_NAME' in counties_gdf.columns else None

    t_start = time.time()
    all_features = []
    for i, slug in enumerate(STATE_SLUGS):
        print(f'[{i+1}/{len(STATE_SLUGS)}] {slug}', flush=True)
        try:
            feats = extract_state(slug, counties_gdf, name_col, state_col)
            all_features.extend(feats)
        except Exception as exc:
            print(f'  ERROR on {slug}: {exc}', flush=True)
            continue

    ts = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    out_geo = SNAP_DIR / f'cameras_snapshot_{ts}_perstate_withid.geojson'
    out_manifest = SNAP_DIR / f'cameras_snapshot_{ts}_perstate_withid.manifest.json'
    with open(out_geo, 'w', encoding='utf-8') as fh:
        json.dump({'type': 'FeatureCollection', 'features': all_features}, fh)
    with open(out_manifest, 'w', encoding='utf-8') as fh:
        json.dump({'created_at': ts, 'source': 'pyrosm_us_perstate_withid',
                    'file': str(out_geo.relative_to(ROOT)).replace('\\', '/'),
                    'feature_count': len(all_features)}, fh)
    print(f'DONE: {len(all_features)} total features in {time.time()-t_start:.0f}s -> {out_geo}', flush=True)


if __name__ == '__main__':
    main()
