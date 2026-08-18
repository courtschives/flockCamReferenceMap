"""Fetch ALPR camera points from OSM Overpass and save GeoJSON.

This is a conservative, resumable stub that supports querying a single bbox.
For full-US extraction, callers should chunk the country into tiles and
call `fetch_overpass` per tile to avoid Overpass timeouts.
"""
import json
import requests
from time import sleep
from pathlib import Path
import geopandas as gpd
from shapely.geometry import Point

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

def fetch_overpass(bbox, timeout=180, retries=3):
    """Fetch nodes with surveillance:type=ALPR within bbox.

    bbox: (south, west, north, east)
    Returns GeoJSON FeatureCollection.
    """
    south, west, north, east = bbox
    # Request JSON output explicitly and use tolerant headers
    query = f"[out:json];node[\"surveillance:type\"=\"ALPR\"]({south},{west},{north},{east});out tags;"
    headers = {
        'User-Agent': 'Mozilla/5.0 (compatible; FlockMap/1.0)',
        'Accept': 'application/json, text/plain, */*',
    }
    last_error = None
    for attempt in range(retries):
        for overpass_url in OVERPASS_URLS:
            try:
                resp = requests.post(overpass_url, data={'data': query}, headers=headers, timeout=timeout)
                resp.raise_for_status()
                text = resp.text
                # Overpass sometimes returns non-JSON (HTML error pages); guard against that
                if not text or text.strip().startswith('<'):
                    raise requests.RequestException('Non-JSON response from Overpass')
                try:
                    data = resp.json()
                except ValueError:
                    # try fallback to parsing as text -> empty
                    raise requests.RequestException('Invalid JSON from Overpass')
                return {'type': 'FeatureCollection', 'features': [
                    {
                        'type': 'Feature',
                        'geometry': {'type': 'Point', 'coordinates': [el['lon'], el['lat']]},
                        'properties': {**(el.get('tags', {}) or {}), 'osm_id': el.get('id')},
                    }
                    for el in data.get('elements', [])
                    if el.get('type') == 'node' and 'lat' in el and 'lon' in el
                ]}
            except requests.RequestException as exc:
                last_error = exc
                continue
        if attempt < retries - 1:
            sleep(10 * (attempt + 1))
    raise last_error

def chunk_bbox_grid(south, west, north, east, step_deg=1.0):
    """Yield bbox tuples covering the extent in a simple lat/lon grid.

    step_deg: size of each grid cell in degrees (approx). Default 1°.
    """
    lat = south
    while lat < north:
        lon = west
        lat2 = min(lat + step_deg, north)
        while lon < east:
            lon2 = min(lon + step_deg, east)
            yield (lat, lon, lat2, lon2)
            lon += step_deg
        lat += step_deg

def load_counties_geojson(path=None):
    """Load county geometries as a GeoDataFrame. If not present, raise an error.

    Expect path to a GeoJSON or shapefile. Default: repo data/tiger_counties.geojson
    """
    repo_root = Path(__file__).resolve().parents[2]
    if path is None:
        path = repo_root / 'data' / 'tiger_counties.geojson'
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f'County geometries not found at {path}. Run the helper to download TIGER counties.')
    gdf = gpd.read_file(str(path))
    # Normalize column names: try 'GEOID' or combine STATEFP+COUNTYFP
    if 'GEOID' in gdf.columns:
        gdf['county_fips'] = gdf['GEOID'].astype(str)
    elif 'STATEFP' in gdf.columns and 'COUNTYFP' in gdf.columns:
        gdf['county_fips'] = gdf['STATEFP'].astype(str).str.zfill(2) + gdf['COUNTYFP'].astype(str).str.zfill(3)
    else:
        raise RuntimeError('Unknown county GEOID columns in counties file')
    return gdf.to_crs(epsg=4326)

def assign_county_fips(feature_collection, counties_gdf):
    """Assign county_fips to each point feature via spatial join.

    Returns a new FeatureCollection where each feature.properties has 'county_fips'.
    """
    features = feature_collection.get('features', [])
    if not features:
        return feature_collection
    pts = [Point(f['geometry']['coordinates']) for f in features]
    props = [f.get('properties', {}) for f in features]
    gdf = gpd.GeoDataFrame(props, geometry=pts, crs='EPSG:4326')
    joined = gpd.sjoin(gdf, counties_gdf[['county_fips', 'geometry']], how='left', predicate='within')
    out_features = []
    for idx, row in joined.iterrows():
        p = features[idx]
        properties = p.get('properties', {})
        cf = row.get('county_fips')
        if cf is not None and cf is not gpd.NA:
            properties['county_fips'] = str(cf)
        else:
            properties['county_fips'] = None
        out_features.append({'type': 'Feature', 'geometry': p['geometry'], 'properties': properties})
    return {'type': 'FeatureCollection', 'features': out_features}

def run_full_us(output_path, step_deg=1.0, counties_path=None, delay=1.0):
    """Run a chunked Overpass extraction across continental US extents (approx).

    This is conservative and may still hit Overpass limits; use modest `step_deg`.
    Writes output GeoJSON with county_fips assigned (if counties provided).
    """
    # Approx bounding box for continental US
    south, west, north, east = 24.0, -125.0, 50.0, -66.0
    all_features = []
    for bbox in chunk_bbox_grid(south, west, north, east, step_deg=step_deg):
        try:
            fc = fetch_overpass(bbox)
        except Exception as e:
            print(f'Warning: fetch failed for bbox {bbox}: {e}')
            continue
        all_features.extend(fc.get('features', []))
        sleep(delay)
    combined = {'type': 'FeatureCollection', 'features': all_features}
    if counties_path:
        counties = load_counties_geojson(counties_path)
        combined = assign_county_fips(combined, counties)
    outp = Path(output_path)
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(combined))
    print(f'Wrote {len(combined["features"])} features to {outp}')

def run(output_path, bbox=None, counties_path=None):
    """Run pipeline: require bbox for safety unless running full_us helper."""
    outp = Path(output_path)
    outp.parent.mkdir(parents=True, exist_ok=True)
    if bbox is not None:
        geom = fetch_overpass(bbox)
        if counties_path:
            counties = load_counties_geojson(counties_path)
            geom = assign_county_fips(geom, counties)
        outp.write_text(json.dumps(geom))
        print(f"Wrote {len(geom['features'])} features to {outp}")
    else:
        raise ValueError('bbox is required for safety. For full US run, call run_full_us()')

if __name__ == '__main__':
    # example usage: python overpass_cameras.py --bbox "south,west,north,east" --out output/cameras.geojson
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--bbox', help='south,west,north,east')
    p.add_argument('--out', help='output GeoJSON path', default='output/cameras.geojson')
    p.add_argument('--counties', help='path to counties geojson for FIPS assignment')
    p.add_argument('--full-us', action='store_true', help='run chunked full-US extraction (slow)')
    p.add_argument('--step-deg', type=float, default=1.0, help='grid step for chunking in degrees')
    args = p.parse_args()
    if args.full_us:
        run_full_us(args.out, step_deg=args.step_deg, counties_path=args.counties)
    else:
        if not args.bbox:
            raise SystemExit('Provide --bbox or --full-us')
        bbox = tuple(map(float, args.bbox.split(',')))
        run(args.out, bbox=bbox, counties_path=args.counties)
