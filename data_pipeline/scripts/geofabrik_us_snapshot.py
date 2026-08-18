"""Download Geofabrik US extract and extract all ALPR camera points.

Warning: the US extract is large (multiple GB). Ensure you have disk
space and bandwidth. This script streams the download and processes the
PBF with `pyrosm` to avoid Overpass rate limits.
"""
from pathlib import Path
import json
from datetime import datetime
import requests
from pyrosm import OSM
import geopandas as gpd

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / 'data' / 'geofabrik'
DATA_DIR.mkdir(parents=True, exist_ok=True)
PBF_URL = 'https://download.geofabrik.de/north-america/us-latest.osm.pbf'
PBF_PATH = DATA_DIR / 'us-latest.osm.pbf'


def download_if_missing():
    if PBF_PATH.exists():
        print('Using existing extract:', PBF_PATH)
        return
    print('Downloading', PBF_URL)
    resp = requests.get(PBF_URL, stream=True, timeout=120)
    resp.raise_for_status()
    with PBF_PATH.open('wb') as f:
        total = 0
        for chunk in resp.iter_content(chunk_size=1024 * 1024):
            if chunk:
                f.write(chunk)
                total += len(chunk)
                print(f'downloaded {total} bytes', end='\r')
    print('\nDownload complete')


def extract_alpr():
    osm = OSM(str(PBF_PATH))
    print('Reading POIs and filtering for ALPR...')
    gdf = osm.get_pois(custom_filter={'surveillance:type': ['ALPR']}, extra_attributes=['surveillance:type','camera:type','operator','name','ref','source'])
    print('Found', len(gdf), 'POIs')
    return gdf


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
    pts = gpd.GeoDataFrame(gdf, geometry='geometry', crs='EPSG:4326')
    pts = pts[pts.geometry.notna()].copy()
    joined = gpd.sjoin(pts, counties[['county_fips','geometry']], how='left', predicate='within')
    joined['county_fips'] = joined['county_fips'].astype(str)
    return joined


def write_snapshot(gdf: gpd.GeoDataFrame):
    ts = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    outdir = ROOT / 'data' / 'snapshots'
    outdir.mkdir(parents=True, exist_ok=True)
    outgeo = outdir / f'cameras_snapshot_{ts}_us_geofabrik.geojson'
    manifest = outdir / f'cameras_snapshot_{ts}_us_geofabrik.manifest.json'
    features = []
    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom is None:
            continue
        props = row.drop(labels='geometry').to_dict()
        props['source'] = 'geofabrik_us'
        features.append({'type':'Feature','geometry':{'type':'Point','coordinates':[float(geom.x),float(geom.y)]},'properties':props})
    outgeo.write_text(json.dumps({'type':'FeatureCollection','features':features}, ensure_ascii=False))
    manifest.write_text(json.dumps({'created_at':ts,'source':'geofabrik_us','file':str(outgeo.relative_to(ROOT)),'feature_count':len(features)}, indent=2))
    print('Wrote', len(features), 'features to', outgeo)
    return outgeo


def main():
    download_if_missing()
    gdf = extract_alpr()
    if gdf.empty:
        print('No ALPR features found in US extract')
        return
    joined = assign_counties(gdf)
    write_snapshot(joined)


if __name__ == '__main__':
    main()
