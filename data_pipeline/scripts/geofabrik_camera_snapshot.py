"""Download a Geofabrik California extract and export real ALPR camera points.

This is the non-Overpass fallback route for a real OSM-derived camera snapshot.
It downloads the smaller SoCal or NorCal extracts, keeps only ALPR-tagged POIs,
assigns county FIPS, and writes a timestamped snapshot under data/snapshots.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests
from pyrosm import OSM
from shapely.geometry import Point

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / 'data'
GEOFABRIK_DIR = DATA_DIR / 'geofabrik'
GEOFABRIK_DIR.mkdir(parents=True, exist_ok=True)
PBF_URL = 'https://download.geofabrik.de/north-america/us/california/socal-latest.osm.pbf'
PBF_PATH = GEOFABRIK_DIR / 'socal-latest.osm.pbf'


def download_extract():
    if PBF_PATH.exists():
        print(f'Using existing extract: {PBF_PATH} ({PBF_PATH.stat().st_size} bytes)')
        return
    print(f'Downloading {PBF_URL} -> {PBF_PATH}')
    resp = requests.get(PBF_URL, stream=True, timeout=120)
    resp.raise_for_status()
    with PBF_PATH.open('wb') as f:
        total = 0
        for chunk in resp.iter_content(chunk_size=1024 * 1024):
            if chunk:
                f.write(chunk)
                total += len(chunk)
                print(f'downloaded {total} bytes', end='\r')
    print('')
    print(f'Download complete: {PBF_PATH} ({PBF_PATH.stat().st_size} bytes)')


def load_alpr_points():
    osm = OSM(str(PBF_PATH))
    gdf = osm.get_pois(
        custom_filter={'surveillance:type': ['ALPR']},
        extra_attributes=['surveillance:type', 'camera:type', 'amenity', 'operator', 'name', 'ref', 'source'],
    )
    if gdf.empty:
        return gdf
    # Some OSM data may use lowercase or other variants; try a second pass.
    if 'surveillance:type' not in gdf.columns:
        gdf2 = osm.get_pois(
            custom_filter={'surveillance:type': ['alpr']},
            extra_attributes=['surveillance:type', 'camera:type', 'amenity', 'operator', 'name', 'ref', 'source'],
        )
        gdf = pd.concat([gdf, gdf2], ignore_index=True)
    gdf = gdf[gdf.geometry.notna()].copy()
    return gdf


def assign_counties(gdf: gpd.GeoDataFrame):
    counties_path = ROOT / 'data' / 'tiger_counties.geojson'
    if not counties_path.exists():
        from data_pipeline.utils.tiger_counties import download_and_prepare
        download_and_prepare(output_path=counties_path)
    counties = gpd.read_file(str(counties_path)).to_crs(epsg=4326)
    if 'GEOID' in counties.columns:
        counties['county_fips'] = counties['GEOID'].astype(str)
    else:
        counties['county_fips'] = counties['STATEFP'].astype(str).str.zfill(2) + counties['COUNTYFP'].astype(str).str.zfill(3)

    points = gpd.GeoDataFrame(gdf, geometry='geometry', crs='EPSG:4326')
    # Keep only point geometries
    points = points[points.geometry.geom_type == 'Point'].copy()
    joined = gpd.sjoin(points, counties[['county_fips', 'geometry']], how='left', predicate='within')
    joined['county_fips'] = joined['county_fips'].astype(str)
    return joined


def write_snapshot(gdf):
    ts = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    snapshot_dir = ROOT / 'data' / 'snapshots'
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    outgeo = snapshot_dir / f'cameras_snapshot_{ts}_geofabrik.geojson'
    manifest = snapshot_dir / f'cameras_snapshot_{ts}_geofabrik.manifest.json'
    # Drop geometry to simple GeoJSON feature collection
    features = []
    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom is None or geom.geom_type != 'Point':
            continue
        props = row.drop(labels='geometry').to_dict()
        props['source'] = 'geofabrik_osm'
        props['camera_type'] = props.get('camera:type') or props.get('surveillance:type') or 'ALPR'
        features.append({
            'type': 'Feature',
            'geometry': {'type': 'Point', 'coordinates': [float(geom.x), float(geom.y)]},
            'properties': props,
        })

    fc = {'type': 'FeatureCollection', 'features': features}
    outgeo.write_text(json.dumps(fc, ensure_ascii=False))
    manifest.write_text(json.dumps({
        'created_at': ts,
        'source': 'geofabrik_osm_extract',
        'file': str(outgeo.relative_to(ROOT)),
        'extract_url': PBF_URL,
        'feature_count': len(features),
    }, indent=2))
    print(f'Wrote real OSM snapshot with {len(features)} points to {outgeo}')
    return outgeo


def main():
    download_extract()
    gdf = load_alpr_points()
    print('ALPR rows before county join:', len(gdf))
    if gdf.empty:
        raise RuntimeError('No ALPR features found in the Geofabrik extract. The tag may not be present in this region.')
    gdf = assign_counties(gdf)
    outgeo = write_snapshot(gdf)
    return outgeo


if __name__ == '__main__':
    main()
