"""Chunked extractor for the US Geofabrik PBF.

This script reads the local `us-latest.osm.pbf` in tiles (lat/lon grid),
extracts ALPR POIs per tile using `pyrosm`, assigns county FIPS, and
writes incremental partial outputs and a resumeable progress file.

Run with the `flockmap` conda env. Example:

  conda run -n flockmap python data_pipeline/scripts/geofabrik_us_snapshot_chunked.py --tile-deg 2.5

The script writes partial GeoJSONs into `data/snapshots/` and a final
manifest when complete.
"""
from pathlib import Path
import json
from datetime import datetime
import argparse
import math
import time

import geopandas as gpd
from pyrosm import OSM

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / 'data' / 'geofabrik'
PBF_PATH = DATA_DIR / 'us-latest.osm.pbf'
SNAP_DIR = ROOT / 'data' / 'snapshots'
SNAP_DIR.mkdir(parents=True, exist_ok=True)


def tiles_for_bbox(xmin, ymin, xmax, ymax, tile_deg):
    x = xmin
    while x < xmax:
        y = ymin
        x2 = min(x + tile_deg, xmax)
        while y < ymax:
            y2 = min(y + tile_deg, ymax)
            yield (x, y, x2, y2)
            y += tile_deg
        x += tile_deg


def load_progress(progress_path):
    if progress_path.exists():
        return json.loads(progress_path.read_text())
    return {'done_tiles': [], 'features': 0}


def save_progress(progress_path, prog):
    progress_path.write_text(json.dumps(prog, indent=2))


def assign_counties(gdf: gpd.GeoDataFrame):
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
    if pts.empty:
        return pts
    joined = gpd.sjoin(gpd.GeoDataFrame(pts, geometry='geometry', crs='EPSG:4326'), counties[['county_fips','geometry']], how='left', predicate='within')
    joined['county_fips'] = joined['county_fips'].astype(str)
    return joined


def append_features(out_path: Path, features):
    # simple append to NDJSON-like GeoJSON array: keep a partial file and rewrite whole when small
    if not out_path.exists():
        out = {'type':'FeatureCollection','features':[]}
    else:
        out = json.loads(out_path.read_text())
    out['features'].extend(features)
    out_path.write_text(json.dumps(out, ensure_ascii=False))


def main(tile_deg=2.5, delay=0.5):
    if not PBF_PATH.exists():
        raise SystemExit(f'PBF missing: {PBF_PATH} — run the us download first')

    osm = OSM(str(PBF_PATH))
    # continental US bbox roughly
    xmin, ymin, xmax, ymax = -125.0, 24.0, -66.5, 50.0
    tiles = list(tiles_for_bbox(xmin, ymin, xmax, ymax, tile_deg))

    progress_path = SNAP_DIR / 'geofabrik_us_chunked.progress.json'
    partial_out = SNAP_DIR / 'cameras_snapshot_us_geofabrik_partial.geojson'
    prog = load_progress(progress_path)

    features_total = prog.get('features', 0)

    for t in tiles:
        tkey = f'{t[0]}_{t[1]}_{t[2]}_{t[3]}'
        if tkey in prog.get('done_tiles', []):
            continue
        print('Processing tile', tkey)
        try:
            # create a tile-scoped OSM reader with bounding_box and query POIs inside it
            osm_tile = OSM(str(PBF_PATH), bounding_box=[t[0], t[1], t[2], t[3]])
            gdf = osm_tile.get_pois(custom_filter={'surveillance:type': ['ALPR']}, extra_attributes=['surveillance:type','camera:type','operator','name','ref','source','camera:direction','camera:field_of_view','fov','osm_id'])
        except Exception as e:
            print('Tile error:', e)
            time.sleep(delay)
            continue

        if gdf is None or gdf.empty:
            prog.setdefault('done_tiles', []).append(tkey)
            save_progress(progress_path, prog)
            time.sleep(delay)
            continue

        joined = assign_counties(gdf)
        features = []
        for _, row in joined.iterrows():
            geom = row.geometry
            if geom is None:
                continue
            props = row.drop(labels='geometry').to_dict()
            props['source'] = 'geofabrik_us'
            features.append({'type':'Feature','geometry':{'type':'Point','coordinates':[float(geom.x),float(geom.y)]},'properties':props})

        append_features(partial_out, features)
        features_total += len(features)
        prog.setdefault('done_tiles', []).append(tkey)
        prog['features'] = features_total
        save_progress(progress_path, prog)
        print('Tile done, wrote', len(features), 'features (total', features_total, ')')
        time.sleep(delay)

    # finalize: write final snapshot with timestamped name
    ts = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    final_geo = SNAP_DIR / f'cameras_snapshot_{ts}_us_geofabrik.geojson'
    final_manifest = SNAP_DIR / f'cameras_snapshot_{ts}_us_geofabrik.manifest.json'
    if partial_out.exists():
        partial = json.loads(partial_out.read_text())
        final_geo.write_text(json.dumps(partial, ensure_ascii=False))
    final_manifest.write_text(json.dumps({'created_at': ts, 'source': 'geofabrik_us', 'file': str(final_geo.relative_to(ROOT)), 'feature_count': features_total}, indent=2))
    # cleanup progress
    if progress_path.exists():
        progress_path.unlink()
    print('Finished chunked extraction — wrote', features_total, 'features to', final_geo)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--tile-deg', type=float, default=2.5, help='tile size in degrees')
    p.add_argument('--delay', type=float, default=0.5, help='seconds to sleep between tiles')
    args = p.parse_args()
    main(tile_deg=args.tile_deg, delay=args.delay)
